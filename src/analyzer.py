"""Groq-backed analysis orchestration with bounded retries and schema repair.

Privacy: logs contain only counts and mode, never document text, filenames or keys.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    Groq,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from . import prompts, validator
from .config import Settings
from .document_processor import ExtractedDocument, build_chunks
from .schemas import (
    ChunkExtraction,
    DocumentAnalysis,
    EvidenceAudit,
    TokenUsage,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]


class AnalysisError(RuntimeError):
    """User-facing analysis failure. Message is safe to display."""


class ConfigurationError(AnalysisError):
    """Missing or invalid configuration (e.g. no API key)."""


class StructuredOutputError(AnalysisError):
    """The model output could not be validated even after one repair attempt."""


@dataclass
class AnalysisResult:
    analysis: DocumentAnalysis
    evidence: EvidenceAudit
    mode: str
    chunks_analyzed: int
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis.model_dump(mode="json"),
            "evidence_audit": self.evidence.model_dump(mode="json"),
            "metadata": {
                "mode": self.mode,
                "chunks_analyzed": self.chunks_analyzed,
                "model": self.model,
                "token_usage": self.usage.model_dump(mode="json"),
                "warnings": self.warnings,
            },
        }


def build_groq_client(settings: Settings) -> Groq:
    if not settings.is_configured:
        raise ConfigurationError(
            "GROQ_API_KEY is not configured. Copy .env.example to .env, add your Groq API key, "
            "and restart the application."
        )
    return Groq(
        api_key=settings.groq_api_key,
        timeout=settings.request_timeout_seconds,
        max_retries=0,  # retries are handled here with a bounded policy
    )


def analyze_document(
    document: ExtractedDocument,
    settings: Settings,
    progress: ProgressCallback | None = None,
    client: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> AnalysisResult:
    """Analyze an extracted document. `client` is injectable for offline tests."""
    if not settings.is_configured and client is None:
        raise ConfigurationError(
            "GROQ_API_KEY is not configured. Copy .env.example to .env, add your Groq API key, "
            "and restart the application."
        )
    groq_client = client or build_groq_client(settings)
    notify = progress or (lambda _message: None)
    usage = TokenUsage()

    if document.char_count <= settings.direct_analysis_chars:
        notify("Analyzing document with Groq...")
        messages = prompts.build_direct_prompt(document.full_text, document.filename)
        content, usage = _chat(
            groq_client,
            messages,
            settings,
            max_tokens=settings.max_output_tokens,
            sleep=sleep,
        )
        analysis, repair_usage = _validate_with_repair(
            content, DocumentAnalysis, DocumentAnalysis.model_json_schema(), groq_client, messages, settings, sleep
        )
        usage = usage.add(repair_usage)
        mode = "direct"
        chunks_analyzed = 1
        chunk_warnings: list[str] = []
    else:
        mode = "chunked"
        chunks, chunk_warnings = build_chunks(
            document,
            chunk_chars=settings.chunk_chars,
            overlap_chars=settings.chunk_overlap_chars,
            max_chunks=settings.max_chunks,
        )
        chunk_payloads: list[dict[str, Any]] = []
        page_labels: list[str] = []
        for chunk in chunks:
            notify(f"Analyzing section {chunk.index + 1} of {len(chunks)} ({chunk.label})...")
            messages = prompts.build_chunk_prompt(chunk.text, chunk.label, chunk.index + 1, len(chunks))
            content, call_usage = _chat(
                groq_client,
                messages,
                settings,
                max_tokens=min(settings.max_output_tokens, 4096),
                sleep=sleep,
            )
            usage = usage.add(call_usage)
            extraction, repair_usage = _validate_with_repair(
                content,
                ChunkExtraction,
                ChunkExtraction.model_json_schema(),
                groq_client,
                messages,
                settings,
                sleep,
            )
            usage = usage.add(repair_usage)
            chunk_payloads.append(extraction.model_dump(mode="json"))
            page_labels.append(chunk.label)

        notify("Consolidating section findings...")
        messages = prompts.build_consolidation_prompt(chunk_payloads, document.filename, page_labels, document.truncated)
        content, call_usage = _chat(
            groq_client,
            messages,
            settings,
            max_tokens=settings.max_output_tokens,
            sleep=sleep,
        )
        usage = usage.add(call_usage)
        analysis, repair_usage = _validate_with_repair(
            content, DocumentAnalysis, DocumentAnalysis.model_json_schema(), groq_client, messages, settings, sleep
        )
        usage = usage.add(repair_usage)
        chunks_analyzed = len(chunks)

    analysis = validator.normalize_analysis(analysis)
    analysis.document_filename = document.filename
    analysis.analysis_date = date.today()

    warnings = list(document.warnings) + chunk_warnings
    if mode == "chunked":
        warnings.append(
            f"Long-document mode: {chunks_analyzed} bounded section(s) were analyzed and consolidated. "
            "Cross-section requirements may be split or merged."
        )
    if analysis.complexity_assessment.level != analysis.executive_summary.overall_complexity:
        warnings.append(
            "The summary complexity and the detailed complexity assessment differ; review both before relying on either."
        )
    analysis.limitations.append(
        "AI-generated analysis. Every requirement, citation and recommendation requires human review."
    )
    if mode == "chunked":
        analysis.limitations.append(
            "Long-document mode consolidates section-level extractions; some requirements spanning sections may be incomplete."
        )

    notify("Verifying citations against extracted page text...")
    evidence = validator.verify_citations(analysis, document)
    logger.info(
        "analysis complete mode=%s chunks=%d citations=%d verified=%d tokens=%d",
        mode,
        chunks_analyzed,
        evidence.total,
        evidence.verified,
        usage.total_tokens,
    )
    return AnalysisResult(
        analysis=analysis,
        evidence=evidence,
        mode=mode,
        chunks_analyzed=chunks_analyzed,
        model=settings.groq_model,
        usage=usage,
        warnings=warnings,
    )


def _chat(
    client: Any,
    messages: list[dict[str, str]],
    settings: Settings,
    max_tokens: int,
    sleep: Callable[[float], None],
) -> tuple[str, TokenUsage]:
    """Call Groq with a small bounded retry policy for transient failures only."""
    last_error: Exception | None = None
    for attempt in range(settings.max_retries + 1):
        try:
            completion = client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                temperature=settings.temperature,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
                timeout=settings.request_timeout_seconds,
            )
            content = completion.choices[0].message.content or ""
            usage = _usage_from_completion(completion)
            if not content.strip():
                raise AnalysisError("Groq returned an empty response. Please try again.")
            return content, usage
        except AuthenticationError as exc:
            raise AnalysisError(
                "Groq rejected the API key (authentication failed). Check GROQ_API_KEY in .env and restart."
            ) from exc
        except RateLimitError as exc:
            last_error = exc
            if attempt >= settings.max_retries:
                break
            delay = _retry_delay(exc, attempt)
            logger.warning("Groq rate limit; retrying in %.1fs (attempt %d)", delay, attempt + 1)
            sleep(delay)
        except (APITimeoutError, APIConnectionError) as exc:
            last_error = exc
            if attempt >= settings.max_retries:
                break
            delay = min(2**attempt, 8)
            logger.warning("Groq transient network error; retrying in %ds", delay)
            sleep(delay)
        except BadRequestError as exc:
            raise AnalysisError(
                "Groq rejected the request as invalid. The selected model may not support the "
                "configured output size. Try a smaller document or check GROQ_MODEL."
            ) from exc
        except APIStatusError as exc:
            last_error = exc
            if exc.status_code < 500 or attempt >= settings.max_retries:
                break
            delay = min(2**attempt, 8)
            logger.warning("Groq server error %s; retrying in %ds", exc.status_code, delay)
            sleep(delay)
        except AnalysisError:
            raise
        except Exception as exc:  # SDK/network surprises must not crash the UI
            logger.error("Unexpected Groq client error: %s", type(exc).__name__)
            raise AnalysisError(
                "The Groq request failed unexpectedly. Check your network connection and try again."
            ) from exc

    if isinstance(last_error, RateLimitError):
        raise AnalysisError(
            "Groq rate limit reached after retries. Wait a minute and try again, or use a smaller document."
        ) from last_error
    if isinstance(last_error, APIStatusError):
        raise AnalysisError(
            f"Groq returned a server error ({last_error.status_code}) after retries. Try again shortly."
        ) from last_error
    raise AnalysisError(
        "Could not reach Groq after retries. Check your network connection and try again."
    ) from last_error


def _retry_delay(error: Exception, attempt: int) -> float:
    header = getattr(getattr(error, "response", None), "headers", None)
    if header is not None:
        try:
            return min(max(float(header.get("retry-after", 0)), 0.5), 10.0)
        except (TypeError, ValueError):
            pass
    return min(2**attempt, 8)


def _usage_from_completion(completion: Any) -> TokenUsage:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


def _validate_with_repair(
    content: str,
    schema: type[BaseModel],
    schema_json: dict,
    client: Any,
    messages: list[dict[str, str]],
    settings: Settings,
    sleep: Callable[[float], None],
) -> tuple[Any, TokenUsage]:
    """Parse + validate; on failure make exactly one repair call, then fail clearly."""
    payload, errors = _parse_and_validate(content, schema)
    if payload is not None:
        return payload, TokenUsage()
    logger.warning("Structured output failed validation (%s); attempting one repair", schema.__name__)

    repair_messages = prompts.build_repair_prompt(content, errors, schema_json, messages[-1]["content"])
    repaired, repair_usage = _chat(
        client,
        repair_messages,
        settings,
        max_tokens=settings.max_output_tokens,
        sleep=sleep,
    )
    payload, repair_errors = _parse_and_validate(repaired, schema)
    if payload is not None:
        logger.info("Repair attempt succeeded for %s", schema.__name__)
        return payload, repair_usage
    raise StructuredOutputError(
        "The AI response did not match the required schema after one repair attempt. "
        "No analysis was produced. Try again, reduce the document size, or use a different GROQ_MODEL. "
        f"Validation summary: {repair_errors[0][:240] if repair_errors else 'unknown error'}"
    )


def _parse_and_validate(content: str, schema: type[BaseModel]) -> tuple[Any | None, list[str]]:
    candidate = _extract_json(content)
    if candidate is None:
        return None, ["Response was not a valid JSON object."]
    try:
        return schema.model_validate(candidate), []
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']} (input: {str(err.get('input'))[:120]})"
            for err in exc.errors()
        ]
        return None, errors or [str(exc)[:500]]


def _extract_json(content: str) -> Any | None:
    """Tolerate accidental code fences, nothing else."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None
