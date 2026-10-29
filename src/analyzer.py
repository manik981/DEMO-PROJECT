"""Agnes-backed analysis orchestration with bounded retries and schema repair.

The Agnes API is OpenAI-compatible. It is called directly with httpx because the
Groq SDK hardcodes its own `/openai/v1/chat/completions` path.

Privacy: logs contain only counts and mode, never document text, filenames or keys.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field, replace
from datetime import date
from types import SimpleNamespace
from typing import Any, Callable

import httpx
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from . import prompts, validator
from .config import Settings
from .document_processor import ExtractedDocument, build_chunks
from .schemas import (
    AdvisoryAnalysis,
    ChunkExtraction,
    DocumentAnalysis,
    EvidenceAudit,
    FindingsAnalysis,
    SummaryAdvisory,
    TokenUsage,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]

_FINDING_FIELDS = (
    "functional_requirements",
    "non_functional_requirements",
    "technical_requirements",
    "missing_information",
    "ambiguities",
    "risks",
)


@dataclass(frozen=True)
class ChatResult:
    """One LLM completion with its real finish reason and usage metadata."""

    content: str
    usage: TokenUsage
    finish_reason: str


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


_STATUS_ERRORS = {
    400: BadRequestError,
    401: AuthenticationError,
    403: AuthenticationError,
    404: NotFoundError,
    422: BadRequestError,
    429: RateLimitError,
}


def _error_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _error_message(body: Any, status_code: int) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str):
            return error
    return f"Agnes API returned HTTP {status_code}."


_http_client: httpx.Client | None = None


def _get_http_client() -> httpx.Client:
    """Reuse one client so TLS setup and connections survive across calls."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client()
    return _http_client


class _AgnesCompletions:
    """Minimal stand-in for `client.chat.completions` used by `_chat`.

    It raises the same Groq exception types so the retry policy and tests keep
    working without the SDK's hardcoded path.
    """

    def __init__(self, settings: Settings) -> None:
        self._url = settings.base_url.rstrip("/") + "/chat/completions"
        self._api_key = settings.api_key

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_completion_tokens: int,
        response_format: dict[str, str],
        timeout: float,
    ) -> Any:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
            "response_format": response_format,
        }
        request = httpx.Request("POST", self._url)
        try:
            response = _get_http_client().post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError(request=request) from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(request=request) from exc

        body = _error_body(response)
        if response.status_code >= 400:
            error_type = _STATUS_ERRORS.get(response.status_code, APIStatusError)
            raise error_type(_error_message(body, response.status_code), response=response, body=body)

        data = body if isinstance(body, dict) else {}
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=message.get("content") or ""),
                    finish_reason=choice.get("finish_reason"),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            ),
        )


def build_llm_client(settings: Settings) -> Any:
    if not settings.is_configured:
        raise ConfigurationError(
            "AGNES_API_KEY is not configured. Copy .env.example to .env, add your Agnes API key, "
            "and restart the application."
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=_AgnesCompletions(settings)))


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
            "AGNES_API_KEY is not configured. Copy .env.example to .env, add your Agnes API key, "
            "and restart the application."
        )
    llm_client = client or build_llm_client(settings)
    notify = progress or (lambda _message: None)
    usage = TokenUsage()

    def section_fallback(reason: str, usage_so_far: TokenUsage) -> AnalysisResult:
        """Re-analyze the same document section-by-section and merge the results."""
        notify("Retrying in bounded section mode...")
        result = analyze_document(
            document,
            replace(settings, direct_analysis_chars=0),
            progress=progress,
            client=llm_client,
            sleep=sleep,
        )
        result.usage = usage_so_far.add(result.usage)
        result.warnings.append(reason)
        return result

    if document.char_count <= settings.direct_analysis_chars:
        mode = "direct"
        chunks_analyzed = 1
        chunk_warnings = []
        notify("Extracting requirements and risks with Agnes...")
        messages = prompts.build_findings_prompt(
            document.full_text, document.filename, settings.max_findings_per_category
        )
        chat = _chat(
            llm_client,
            messages,
            settings,
            max_tokens=settings.max_output_tokens,
            sleep=sleep,
            operation="findings",
            notify=notify,
        )
        usage = usage.add(chat.usage)
        try:
            findings, repair_usage = _validate_with_repair(
                chat.content,
                FindingsAnalysis,
                prompts.findings_schema_outline(),
                llm_client,
                settings,
                sleep,
                finish_reason=chat.finish_reason,
                operation="findings",
                notify=notify,
            )
        except StructuredOutputError as exc:
            if "truncated" not in str(exc):
                raise
            # A dense document can produce more findings than the single response
            # budget allows. Retry the same document in bounded section mode; this
            # preserves completeness instead of dropping the analysis.
            return section_fallback(
                "The full-document response exceeded the output limit, so bounded section mode was used.",
                usage,
            )
        usage = usage.add(repair_usage)

        # If the model hit the per-category cap, section mode is the pagination
        # path: each section is extracted independently and merged afterwards.
        hit_cap = [
            field
            for field in _FINDING_FIELDS
            if len(getattr(findings, field)) >= settings.max_findings_per_category
        ]
        if findings.has_more or hit_cap:
            if document.char_count > settings.chunk_chars:
                return section_fallback(
                    "Some findings categories reached their configured limit "
                    f"({', '.join(hit_cap) or 'has_more'}), so bounded section mode was used.",
                    usage,
                )
            # A single section cannot be split further; surface the omission
            # explicitly instead of re-running the same capped request.
            chunk_warnings.append(
                "Some findings categories reached the configured limit; raise "
                "MAX_FINDINGS_PER_CATEGORY to capture more from this document."
            )

        # Serialise once and reuse for both the advisory prompt and final assembly.
        findings_payload = findings.model_dump(mode="json")

        # The advisory stage is a second call because one combined response would
        # be too large to validate reliably. It reuses compact findings and never
        # resends the document.
        notify("Generating clarification questions and recommendations...")
        messages = prompts.build_advisory_prompt(
            _compact_findings(findings_payload),
            document.filename,
            max_findings=settings.max_findings_per_category,
        )
        try:
            chat = _chat(
                llm_client,
                messages,
                settings,
                max_tokens=settings.max_output_tokens,
                sleep=sleep,
                operation="advisory",
                notify=notify,
            )
            usage = usage.add(chat.usage)
            advisory, repair_usage = _validate_with_repair(
                chat.content,
                AdvisoryAnalysis,
                prompts.advisory_schema_outline(),
                llm_client,
                settings,
                sleep,
                finish_reason=chat.finish_reason,
                operation="advisory",
                notify=notify,
            )
        except AnalysisError as exc:
            # Findings are already validated; losing them because a secondary
            # stage failed would discard the whole analysis.
            logger.warning("advisory_stage_failed error=%s", type(exc).__name__)
            chunk_warnings.append(
                "Clarification questions, recommendations and the complexity assessment could not be "
                "generated, so they are omitted. Validated requirements, gaps and risks are still shown."
            )
            analysis = _assemble_analysis(
                findings_payload, _unavailable_advisory(findings_payload["executive_summary"])
            )
        else:
            usage = usage.add(repair_usage)
            analysis = _assemble_analysis(findings_payload, advisory.model_dump(mode="json"))
    else:
        mode = "chunked"
        chunks, chunk_warnings = build_chunks(
            document,
            chunk_chars=settings.chunk_chars,
            overlap_chars=settings.chunk_overlap_chars,
            max_chunks=settings.max_chunks,
        )
        extractions: list[ChunkExtraction] = []
        for chunk in chunks:
            notify(f"Analyzing section {chunk.index + 1} of {len(chunks)} ({chunk.label})...")
            messages = prompts.build_chunk_prompt(
                chunk.text,
                chunk.label,
                chunk.index + 1,
                len(chunks),
                settings.max_findings_per_category,
            )
            chat = _chat(
                llm_client,
                messages,
                settings,
                max_tokens=settings.max_output_tokens,
                sleep=sleep,
                operation=f"chunk_{chunk.index + 1}",
                notify=notify,
            )
            usage = usage.add(chat.usage)
            extraction, repair_usage = _validate_with_repair(
                chat.content,
                ChunkExtraction,
                prompts.chunk_schema_outline(),
                llm_client,
                settings,
                sleep,
                finish_reason=chat.finish_reason,
                operation=f"chunk_{chunk.index + 1}",
                notify=notify,
            )
            usage = usage.add(repair_usage)
            extractions.append(extraction)

        capped_sections = [
            str(extraction_index + 1)
            for extraction_index, extraction in enumerate(extractions)
            if extraction.has_more
            or any(
                len(getattr(extraction, field)) >= settings.max_findings_per_category
                for field in _FINDING_FIELDS
            )
        ]
        if capped_sections:
            chunk_warnings.append(
                f"Section(s) {', '.join(capped_sections)} reached the configured findings limit; "
                "some findings may be omitted. Raise MAX_FINDINGS_PER_CATEGORY or reduce CHUNK_CHARS."
            )

        notify("Consolidating section findings...")
        try:
            merged, duplicates_removed = validator.merge_chunk_extractions(extractions)
        except Exception:
            # Keep every validated section result rather than losing the run to a
            # consolidation defect; normalize_analysis still dedupes and renumbers.
            logger.exception("chunk_consolidation_failed sections=%d", len(extractions))
            merged = {
                field: [
                    item.model_dump(mode="json")
                    for extraction in extractions
                    for item in getattr(extraction, field)
                ]
                for field in _FINDING_FIELDS
            }
            duplicates_removed = 0
            chunk_warnings.append(
                "Section findings could not be consolidated automatically; "
                "all section results were kept and may contain duplicates."
            )
        if duplicates_removed:
            chunk_warnings.append(
                f"{duplicates_removed} duplicate finding(s) from overlapping sections were merged."
            )

        notify("Generating executive summary and recommendations...")
        messages = prompts.build_advisory_prompt(
            {
                "findings": _compact_findings(merged),
                "section_summaries": [extraction.chunk_summary for extraction in extractions if extraction.chunk_summary],
            },
            document.filename,
            include_summary=True,
            max_findings=settings.max_findings_per_category,
        )
        try:
            chat = _chat(
                llm_client,
                messages,
                settings,
                max_tokens=settings.max_output_tokens,
                sleep=sleep,
                operation="summary_advisory",
                notify=notify,
            )
            usage = usage.add(chat.usage)
            advisory, repair_usage = _validate_with_repair(
                chat.content,
                SummaryAdvisory,
                prompts.summary_advisory_schema_outline(),
                llm_client,
                settings,
                sleep,
                finish_reason=chat.finish_reason,
                operation="summary_advisory",
                notify=notify,
            )
        except AnalysisError as exc:
            logger.warning("summary_stage_failed error=%s", type(exc).__name__)
            chunk_warnings.append(
                "The executive summary, clarification questions, recommendations and complexity assessment "
                "could not be generated, so they are omitted. Validated section findings are still shown."
            )
            analysis = _assemble_analysis(merged, _unavailable_advisory(None))
        else:
            usage = usage.add(repair_usage)
            analysis = _assemble_analysis(merged, advisory.model_dump(mode="json"))
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
    try:
        evidence = validator.verify_citations(analysis, document)
    except Exception:
        # Citation checking is an audit layer: its failure must not discard a
        # validated analysis.
        logger.exception("citation_verification_failed")
        evidence = EvidenceAudit(checks=[], total=0, verified=0, verification_rate=0.0)
        warnings.append(
            "Citation verification failed, so evidence checks are unavailable. "
            "The analysis itself is unchanged."
        )
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
        model=settings.model,
        usage=usage,
        warnings=warnings,
    )


def _compact_findings(findings: dict[str, Any]) -> dict[str, Any]:
    """Trim evidence/citation fields for the advisory call to stay within token limits."""
    def pick(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
        return [{key: item.get(key) for key in keys if key in item} for item in items]

    compact = {
        "functional_requirements": pick(
            findings.get("functional_requirements", []), ("id", "description", "category", "priority")
        ),
        "non_functional_requirements": pick(
            findings.get("non_functional_requirements", []), ("id", "category", "description", "status", "priority")
        ),
        "technical_requirements": pick(
            findings.get("technical_requirements", []), ("id", "technology", "category", "status", "notes")
        ),
        "missing_information": pick(
            findings.get("missing_information", []), ("id", "topic", "why_it_matters", "priority")
        ),
        "ambiguities": pick(findings.get("ambiguities", []), ("id", "kind", "description", "status")),
        "risks": pick(
            findings.get("risks", []), ("id", "description", "category", "severity", "basis", "mitigation")
        ),
    }
    if "executive_summary" in findings:
        compact["executive_summary"] = findings["executive_summary"]
    return compact


def _unavailable_advisory(summary: dict[str, Any] | None) -> dict[str, Any]:
    """Explicit placeholders for a failed advisory stage. Never invents findings."""
    executive_summary = summary or {
        "project_title": "Executive summary unavailable",
        "project_overview": (
            "The executive summary could not be generated because that stage failed. "
            "The validated section findings below are still shown."
        ),
        "business_objective": "Not generated.",
        "intended_users": [],
        "project_category": "Unknown",
        "overall_complexity": "Unknown",
        "complexity_rationale": "Not generated.",
    }
    return {
        "executive_summary": executive_summary,
        "clarification_questions": [],
        "solution_recommendations": {
            "potential_architecture": "Not generated: the recommendation stage failed.",
            "technology_options": [],
            "integration_considerations": [],
            "security_recommendations": [],
            "implementation_phases": [],
            "dependencies_and_assumptions": [],
        },
        "complexity_assessment": {
            "level": executive_summary["overall_complexity"],
            "reasons": ["The detailed complexity assessment was not generated."],
            "complexity_drivers": [],
            "major_unknowns": [],
        },
        "limitations": ["The advisory stage failed, so recommendations are unavailable."],
    }


def _assemble_analysis(findings: dict[str, Any], advisory: dict[str, Any]) -> DocumentAnalysis:
    """Combine validated stage outputs into the final schema (one last validation)."""
    payload = {
        "executive_summary": advisory.get("executive_summary") or findings.get("executive_summary"),
        "functional_requirements": findings["functional_requirements"],
        "non_functional_requirements": findings["non_functional_requirements"],
        "technical_requirements": findings["technical_requirements"],
        "missing_information": findings["missing_information"],
        "ambiguities": findings["ambiguities"],
        "risks": findings["risks"],
        "clarification_questions": advisory["clarification_questions"],
        "solution_recommendations": advisory["solution_recommendations"],
        "complexity_assessment": advisory["complexity_assessment"],
        "limitations": advisory.get("limitations", []),
    }
    try:
        return DocumentAnalysis.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputError(
            "The combined analysis failed final schema validation, so no report was produced."
        ) from exc


def _chat(
    client: Any,
    messages: list[dict[str, str]],
    settings: Settings,
    max_tokens: int,
    sleep: Callable[[float], None],
    *,
    operation: str = "analysis",
    notify: ProgressCallback | None = None,
) -> ChatResult:
    """Call the configured LLM with one bounded retry policy for transient failures only.

    This is the only layer that retries; the SDK client is created with
    max_retries=0 so backoff is not stacked.
    """
    last_error: Exception | None = None
    effective_max = _fit_output_budget(messages, max_tokens, settings)
    if effective_max < max_tokens:
        logger.info("Completion budget reduced from %d to %d tokens for request limits", max_tokens, effective_max)
    for attempt in range(settings.max_retries + 1):
        started = time.perf_counter()
        try:
            completion = client.chat.completions.create(
                model=settings.model,
                messages=messages,
                temperature=settings.temperature,
                max_completion_tokens=effective_max,
                response_format={"type": "json_object"},
                timeout=settings.request_timeout_seconds,
            )
        except AuthenticationError as exc:
            _log_request(operation, settings.model, attempt, None, started, "auth_error")
            raise AnalysisError(
                "Agnes rejected the API key (authentication failed). Check AGNES_API_KEY in .env and restart."
            ) from exc
        except BadRequestError as exc:
            _log_request(operation, settings.model, attempt, None, started, "bad_request")
            raise AnalysisError(
                "Agnes rejected the request as invalid. The selected model may not support the "
                "configured output size. Try a smaller document or check AGNES_MODEL."
            ) from exc
        except RateLimitError as exc:
            _log_request(operation, settings.model, attempt, None, started, "rate_limit")
            last_error = exc
            if attempt >= settings.max_retries:
                break
            delay = _retry_delay(exc, attempt)
            logger.warning("Agnes rate limit; retrying in %.1fs (attempt %d)", delay, attempt + 1)
            if notify:
                notify(
                    f"Agnes rate limit; waiting {delay:.0f}s before retry "
                    f"{attempt + 1}/{settings.max_retries}..."
                )
            sleep(delay)
        except (APITimeoutError, APIConnectionError) as exc:
            _log_request(operation, settings.model, attempt, None, started, _error_outcome(exc))
            last_error = exc
            if attempt >= settings.max_retries:
                break
            delay = _transient_delay(attempt)
            logger.warning("Agnes transient network error; retrying in %.1fs", delay)
            if notify:
                notify(f"Agnes connection issue; retrying in {delay:.0f}s...")
            sleep(delay)
        except APIStatusError as exc:
            _log_request(operation, settings.model, attempt, None, started, _error_outcome(exc))
            last_error = exc
            if exc.status_code == 413:
                # Prompt + max completion can still exceed the real TPM ceiling
                # when the prompt estimate is low, so shrink before retrying.
                reduced = max(1024, int(effective_max * 0.7))
                if attempt >= settings.max_retries or reduced >= effective_max:
                    break
                effective_max = reduced
                delay = max(_retry_delay(exc, attempt), 15.0)
                logger.warning(
                    "Agnes token-per-minute limit; reduced completion budget to %d and retrying in %.0fs",
                    effective_max,
                    delay,
                )
                if notify:
                    notify(
                        f"Request exceeds the token budget; reducing output to {effective_max} tokens "
                        f"and waiting {delay:.0f}s..."
                    )
                sleep(delay)
                continue
            if exc.status_code < 500 or attempt >= settings.max_retries:
                break
            delay = _transient_delay(attempt)
            logger.warning("Agnes server error %s; retrying in %.1fs", exc.status_code, delay)
            if notify:
                notify(f"Agnes server error; retrying in {delay:.0f}s...")
            sleep(delay)
        except AnalysisError:
            raise
        except Exception as exc:  # SDK/network surprises must not crash the UI
            _log_request(operation, settings.model, attempt, None, started, "unexpected")
            logger.error("Unexpected LLM client error: %s", type(exc).__name__)
            raise AnalysisError(
                "The Agnes request failed unexpectedly. Check your network connection and try again."
            ) from exc
        else:
            choice = completion.choices[0] if completion.choices else None
            content = (choice.message.content if choice else "") or ""
            finish_reason = getattr(choice, "finish_reason", None) or "unknown"
            usage = _usage_from_completion(completion)
            if not content.strip():
                _log_request(operation, settings.model, attempt, usage, started, "empty_response", finish_reason)
                raise AnalysisError("Agnes returned an empty response. Please try again.")
            _log_request(
                operation,
                settings.model,
                attempt,
                usage,
                started,
                "truncated" if finish_reason == "length" else "success",
                finish_reason,
            )
            return ChatResult(content=content, usage=usage, finish_reason=finish_reason)

    if isinstance(last_error, RateLimitError):
        raise AnalysisError(
            "Agnes rate limit reached after retries. Wait a minute and try again, or use a smaller document."
        ) from last_error
    if isinstance(last_error, APIStatusError):
        if last_error.status_code == 413:
            raise AnalysisError(
                "This request exceeds Agnes's per-minute token limit even after waiting. "
                "Use a smaller document, lower MAX_OUTPUT_TOKENS, or raise MAX_REQUEST_TOKENS "
                "if your Agnes plan allows it."
            ) from last_error
        raise AnalysisError(
            f"Agnes returned an API error ({last_error.status_code}) after retries. Try again shortly."
        ) from last_error
    raise AnalysisError(
        "Could not reach Agnes after retries. Check your network connection and try again."
    ) from last_error


def _log_request(
    operation: str,
    model: str,
    attempt: int,
    usage: TokenUsage | None,
    started: float,
    outcome: str,
    finish_reason: str | None = None,
) -> None:
    """Log non-sensitive request diagnostics. Never include prompt or completion text."""
    logger.info(
        "llm_request operation=%s model=%s attempt=%d outcome=%s "
        "prompt_tokens=%s completion_tokens=%s total_tokens=%s elapsed_ms=%d finish_reason=%s truncated=%s",
        operation,
        model,
        attempt + 1,
        outcome,
        usage.prompt_tokens if usage else None,
        usage.completion_tokens if usage else None,
        usage.total_tokens if usage else None,
        int((time.perf_counter() - started) * 1000),
        finish_reason or "-",
        finish_reason == "length",
    )


def _error_outcome(error: Exception) -> str:
    if isinstance(error, RateLimitError):
        return "rate_limit"
    if isinstance(error, AuthenticationError):
        return "auth_error"
    if isinstance(error, BadRequestError):
        return "bad_request"
    if isinstance(error, APITimeoutError):
        return "timeout"
    if isinstance(error, APIConnectionError):
        return "connection"
    if isinstance(error, APIStatusError):
        return f"http_{error.status_code}"
    return "unexpected"


def _estimate_prompt_tokens(messages: list[dict[str, str]]) -> int:
    characters = sum(len(message.get("content", "")) for message in messages)
    return int(characters / 3.5) + 32 * len(messages)


def _fit_output_budget(messages: list[dict[str, str]], requested: int, settings: Settings) -> int:
    """Keep prompt + completion inside the configured per-request token budget."""
    estimated = _estimate_prompt_tokens(messages)
    available = settings.max_request_tokens - estimated
    if available < 512:
        raise AnalysisError(
            "The document section is too large for the configured request budget. "
            "Reduce CHUNK_CHARS, upload a smaller document, or raise MAX_REQUEST_TOKENS "
            "if your Agnes plan allows it."
        )
    return max(512, min(requested, available))


def _parse_duration(value: object) -> float | None:
    """Parse provider reset values such as '1.26s', '2m3s', '14m24s' or plain seconds."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    match = re.fullmatch(r"(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?", text)
    if not match or not any(match.groups()):
        return None
    return float(match.group(1) or 0) * 60 + float(match.group(2) or 0)


def _retry_delay(error: Exception, attempt: int) -> float:
    """Honour provider reset headers, otherwise use capped backoff with jitter."""
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is not None:
        for name in ("retry-after", "x-ratelimit-reset-tokens"):
            try:
                seconds = _parse_duration(headers.get(name))
            except (AttributeError, TypeError):
                seconds = None
            if seconds is not None:
                return min(max(seconds + 0.5, 1.0), 60.0)
    return _transient_delay(attempt)


def _transient_delay(attempt: int) -> float:
    return min(2**attempt + random.uniform(0, 0.75), 30.0)


def _usage_from_completion(completion: Any) -> TokenUsage:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


def _looks_incomplete_json(content: str) -> bool:
    """Detect an object that was cut off before its closing brace."""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.startswith("{") and not text.endswith("}") and _extract_json(content) is None


def _validate_with_repair(
    content: str,
    schema: type[BaseModel],
    schema_json: dict,
    client: Any,
    settings: Settings,
    sleep: Callable[[float], None],
    *,
    finish_reason: str,
    operation: str,
    notify: ProgressCallback | None = None,
) -> tuple[Any, TokenUsage]:
    """Parse + validate; make at most one targeted repair, then fail clearly."""
    if finish_reason == "length" or _looks_incomplete_json(content):
        logger.warning(
            "llm_output_truncated operation=%s schema=%s chars=%d finish_reason=%s",
            operation,
            schema.__name__,
            len(content),
            finish_reason,
        )
        raise StructuredOutputError(
            "The AI response was truncated or ended with incomplete JSON, so it cannot be validated. "
            f"No analysis was produced ({schema.__name__}, {len(content):,} characters received). "
            "Try again; if it repeats, raise MAX_OUTPUT_TOKENS/MAX_REQUEST_TOKENS "
            "or analyze a smaller document section."
        )

    payload, errors, candidate, targets = _parse_and_validate(content, schema)
    if payload is not None:
        return payload, TokenUsage()

    logger.warning("Structured output failed schema validation (%s); attempting one repair", schema.__name__)
    logger.warning("Validation error fields: %s", "; ".join(errors[:8]))
    if notify:
        notify("Structured output needs repair; retrying once with the validation errors...")

    # Valid JSON: ask only for the failed top-level keys and merge. Malformed
    # JSON: ask for a complete object. The RFP source is never resent.
    repair_messages = prompts.build_repair_prompt(
        content,
        errors,
        schema_json,
        target_keys=targets if candidate is not None and targets else None,
    )
    chat = _chat(
        client,
        repair_messages,
        settings,
        max_tokens=settings.max_output_tokens,
        sleep=sleep,
        operation=f"{operation}_repair",
        notify=notify,
    )
    if chat.finish_reason == "length" or _looks_incomplete_json(chat.content):
        logger.warning(
            "llm_output_truncated operation=%s schema=%s chars=%d finish_reason=%s",
            f"{operation}_repair",
            schema.__name__,
            len(chat.content),
            chat.finish_reason,
        )
        raise StructuredOutputError(
            "The repair response was also truncated, so no analysis was produced. "
            f"({schema.__name__}, {len(chat.content):,} characters received). "
            "Try again or analyze a smaller document section."
        )

    repaired, repair_errors, repaired_candidate, _ = _parse_and_validate(chat.content, schema)
    if candidate is not None and repaired_candidate is not None and targets:
        # A targeted repair may contain only the failed keys, which can validate
        # on its own because the other collections default to empty. Merge it
        # into the original response so valid findings are not discarded.
        merged = {**candidate, **{key: repaired_candidate[key] for key in targets if key in repaired_candidate}}
        repaired, repair_errors = _validate_candidate(merged, schema)
        if repaired is not None:
            logger.info("Targeted repair merged into %s", schema.__name__)
            return repaired, chat.usage
    elif repaired is not None:
        logger.info("Repair attempt succeeded for %s", schema.__name__)
        return repaired, chat.usage

    raise StructuredOutputError(
        "The AI response did not match the required schema after one repair attempt. "
        f"No analysis was produced ({schema.__name__}, finish_reason={chat.finish_reason}). "
        f"Validation summary: {repair_errors[0][:240] if repair_errors else 'unknown error'}"
    )


def _validate_candidate(candidate: dict[str, Any], schema: type[BaseModel]) -> tuple[Any | None, list[str]]:
    try:
        return schema.model_validate(candidate), []
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return None, errors or [str(exc)[:500]]


def _parse_and_validate(
    content: str, schema: type[BaseModel]
) -> tuple[Any | None, list[str], dict[str, Any] | None, list[str]]:
    candidate = _extract_json(content)
    if candidate is None:
        return None, ["Response was not a valid JSON object."], None, []
    if not isinstance(candidate, dict):
        return None, ["Response JSON was not an object."], None, []

    try:
        return schema.model_validate(candidate), [], candidate, []
    except ValidationError as exc:
        details = exc.errors()
        errors = [
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in details
        ]
        targets = sorted({str(err["loc"][0]) for err in details if err.get("loc")})
        return None, errors or [str(exc)[:500]], candidate, targets


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
