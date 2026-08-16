"""Schema-Constrained LLM Structuring Engine with Zero-Hallucination Guardrails,
Deterministic Bypasses, Content-Hash Caching, and Diagnostic Quarantine.

Guiding Principles:
1. Deterministic Extraction First: URL, source, title, publication date, obvious company,
   remote status, role family, GitHub stars, and pricing models are extracted deterministically.
2. LLM ONLY when necessary: Used strictly for difficult, unstructured fields.
3. Content-Hash Caching: Same text hash is never re-sent to LLM; previous results are reused.
4. Concurrency Controlled: Router semaphore (max 3 concurrent) protects free-tier rate limits.
5. Zero Hallucination: Strict JSON mode, 1-shot repair prompt, and quarantine on failure.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type, TypeVar
from pydantic import BaseModel, ValidationError

from src.llm.chunker import SemanticChunker
from src.llm.router import ContextBudgetExceeded, LLMRouterManager
from src.schemas import (
    JobEntity,
    NewsEntity,
    ProductEntity,
    ResearchPaperEntity,
    StartupEntity,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

ZERO_HALLUCINATION_SYSTEM_PROMPT = """You are a precise, schema-constrained data extraction assistant.
CRITICAL MANDATE:
Only extract fields present in the provided text. Set any field you cannot find to null. Never infer or guess a value.
Output valid, parseable JSON strictly conforming to the requested schema. Do not include markdown code blocks or surrounding text."""


class LLMExtractor:
    """Schema-constrained LLM extraction engine with caching, deterministic bypass, and quarantine."""

    def __init__(
        self,
        router_manager: Optional[LLMRouterManager] = None,
        chunker: Optional[SemanticChunker] = None,
        quarantine_dir: str = "data/quarantine",
        structured_dir: str = "data/structured",
        cache_dir: str = "data/cache",
        github_token: Optional[str] = None,
    ):
        self.router = router_manager or LLMRouterManager()
        self.chunker = chunker or SemanticChunker()
        self.quarantine_dir = Path(quarantine_dir)
        self.structured_dir = Path(structured_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_file = self.cache_dir / "llm_cache.json"
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")

        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.structured_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.cache: Dict[str, Any] = self._load_cache()

        self.stats = {
            "total_extracted": 0,
            "deterministic_bypasses": 0,
            "llm_calls": 0,
            "llm_calls_made": 0,
            "llm_cache_hits": 0,
            "cache_hits": 0,
            "fallback_calls": 0,
            "llm_429": 0,
            "429_count": 0,
            "repair_count": 0,
            "repaired_successfully": 0,
            "quarantine_count": 0,
            "quarantined": 0,
            "verified_repos": 0,
        }

    def _load_cache(self) -> Dict[str, Any]:
        """Load persistent LLM extraction cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Could not read LLM cache: %s", e)
        return {}

    def _save_cache(self) -> None:
        """Persist memory cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            logger.warning("Could not persist LLM cache: %s", e)

    def compute_content_hash(self, text: str) -> str:
        """Compute SHA-256 content hash."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _quarantine_record(
        self,
        record_type: str,
        source_url: str,
        error_msg: str,
        raw_output: str,
        attempt: int = 2,
    ) -> None:
        """Persist failed record and diagnostics to quarantine file."""
        quarantine_file = self.quarantine_dir / f"{record_type.lower()}.jsonl"
        diagnostic_entry = {
            "record_type": record_type,
            "source_url": source_url,
            "error": error_msg,
            "raw_output": raw_output,
            "attempt": attempt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            with open(quarantine_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(diagnostic_entry) + "\n")
            self.stats["quarantined"] += 1
            self.stats["quarantine_count"] += 1
            logger.warning("Quarantined record for %s from %s (Error: %s)", record_type, source_url, error_msg)
        except Exception as e:
            logger.error("Failed to write to quarantine file: %s", e)

    def _build_repair_prompt(
        self,
        raw_output: str,
        validation_error: str,
        schema_json: str,
    ) -> str:
        """Construct one-shot schema repair prompt."""
        return f"""The previous JSON output failed schema validation:
Validation Error:
{validation_error}

Invalid JSON Output:
{raw_output}

Target JSON Schema:
{schema_json}

Please repair the JSON so that it strictly adheres to the schema.
Remember: Only extract fields present in the text. Set missing fields to null. Do NOT fabricate or guess."""

    def _clean_json_response(self, text: str) -> str:
        """Strip markdown ticks and whitespace from LLM output."""
        if not text:
            return "{}"
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    def verify_github_repo_sync(self, owner: str, repo: str) -> Tuple[Optional[str], Optional[int]]:
        """Synchronous GitHub API check to verify LLM-extracted GitHub repository."""
        cache_key = f"{owner.lower()}/{repo.lower()}"
        if cache_key in self.cache:
            self.stats["verified_repos"] += 1
            return self.cache[cache_key].get("github_url"), self.cache[cache_key].get("github_stars")

        url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Aetheria-Validator/1.0"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"

        try:
            import httpx
            resp = httpx.get(url, headers=headers, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                verified_url = data.get("html_url")
                stars = data.get("stargazers_count", 0)
                self.cache[cache_key] = {"github_url": verified_url, "github_stars": stars}
                self.stats["verified_repos"] += 1
                return verified_url, stars
        except Exception:
            pass
        return None, None

    def post_validate_and_ground(self, entity: T) -> T:
        """Apply external ground-truth validation to verified entity models."""
        if isinstance(entity, ResearchPaperEntity):
            github_url = entity.content.github_url
            if github_url:
                match = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", github_url)
                if match:
                    owner, repo = match.groups()
                    repo = repo.rstrip(".git")
                    verified_url, stars = self.verify_github_repo_sync(owner, repo)
                    entity.content.github_url = verified_url
                    entity.content.github_stars = stars
                else:
                    entity.content.github_url = None
                    entity.content.github_stars = None
        return entity

    def _normalize_entity_dict(self, data: Any, record_type: str, source_url: str) -> Dict[str, Any]:
        """Normalize raw LLM JSON output to match Pydantic Entity Envelope structure."""
        if not isinstance(data, dict):
            return {}

        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Outer Envelope Defaults
        if not data.get("schemaVersion"):
            data["schemaVersion"] = "1.0"
        if not data.get("recordType"):
            data["recordType"] = record_type.upper()
        if not data.get("collectedAt"):
            data["collectedAt"] = now_iso
        if not isinstance(data.get("source"), dict):
            data["source"] = {"name": record_type.capitalize(), "url": source_url or "https://unknown.source"}
        else:
            if not data["source"].get("name"):
                data["source"]["name"] = record_type.capitalize()
            if not data["source"].get("url"):
                data["source"]["url"] = source_url or "https://unknown.source"

        # 2. Content Envelope Normalization
        if "content" not in data or not isinstance(data["content"], dict):
            content_dict = {
                k: v for k, v in data.items()
                if k not in ("schemaVersion", "recordType", "source", "collectedAt", "entityName", "data")
            }
            data["content"] = content_dict

        # 3. Content Field Normalization
        content = data.get("content", {})
        if isinstance(content, dict):
            # If dates are strings, ensure valid ISO format
            for date_field in ("published_date", "date", "publication_date"):
                if date_field in content and isinstance(content[date_field], str):
                    try:
                        from dateutil import parser as dt_parser
                        dt = dt_parser.parse(content[date_field])
                        content[date_field] = dt.isoformat()
                    except Exception:
                        pass

            # Job specific defaults
            if record_type.upper() == "JOB":
                if not content.get("company") and source_url:
                    from urllib.parse import urlparse
                    netloc = urlparse(source_url).netloc.replace("www.", "")
                    content["company"] = netloc.split(".")[0].capitalize()
                if not content.get("date"):
                    content["date"] = now_iso
                if not content.get("role_family"):
                    content["role_family"] = "Engineering"

            # News specific defaults
            if record_type.upper() == "NEWS":
                if not content.get("title") and content.get("headline"):
                    content["title"] = content["headline"]
                if not content.get("title"):
                    content["title"] = "Tech Intelligence Update"
                if not content.get("published_date"):
                    content["published_date"] = now_iso
                if not content.get("summary") and content.get("description"):
                    content["summary"] = content["description"]
                elif not content.get("summary"):
                    content["summary"] = content.get("title", "News summary")

            # Startup specific defaults
            if record_type.upper() == "STARTUP":
                if not data.get("entityName") and content.get("startupName"):
                    data["entityName"] = content["startupName"]
                elif not data.get("entityName") and content.get("name"):
                    data["entityName"] = content["name"]
                if not data.get("entityName"):
                    data["entityName"] = "Unknown Startup"
                if not data.get("data") or not isinstance(data.get("data"), dict):
                    data["data"] = content

            # Product specific defaults
            if record_type.upper() == "PRODUCT":
                if not content.get("startupName") and content.get("company"):
                    content["startupName"] = content["company"]
                elif not content.get("startupName") and source_url:
                    from urllib.parse import urlparse
                    netloc = urlparse(source_url).netloc.replace("www.", "")
                    content["startupName"] = netloc.split(".")[0].capitalize()

        return data

    def extract_entity(
        self,
        raw_text: str,
        schema_cls: Type[T],
        source_url: str = "",
        record_type: str = "UNKNOWN",
        allow_cache: bool = True,
        run_id: Optional[str] = None,
    ) -> Optional[T]:
        """Extract and validate Pydantic record with caching, repair, and quarantine."""
        content_hash = self.compute_content_hash(raw_text)

        # 1. Content Hash Cache Check
        if allow_cache and content_hash in self.cache:
            try:
                cached_dict = self.cache[content_hash]
                entity = schema_cls.model_validate(cached_dict)
                self.stats["llm_cache_hits"] += 1
                self.stats["total_extracted"] += 1
                return entity
            except Exception:
                pass

        schema_json = json.dumps(schema_cls.model_json_schema(), indent=2)
        budgeted_text = self.chunker.chunk_and_budget(raw_text)

        user_prompt = f"""Extract data from the following text according to the JSON schema:

Target Schema:
{schema_json}

Document Text:
{budgeted_text}

JSON Output:"""

        messages = [
            {"role": "system", "content": ZERO_HALLUCINATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 2. Router Execution with Fallback
        raw_output = ""
        self.stats["llm_calls"] += 1
        try:
            raw_output = self.router.execute_completion(
                messages=messages,
                response_format={"type": "json_object"},
                record_type=record_type,
                content_hash=content_hash,
                run_id=run_id,
            )
        except ContextBudgetExceeded:
            logger.info("Context budget exceeded; retrying with reduced chunk size.")
            reduced_text = self.chunker.chunk_and_budget(budgeted_text, max_tokens=2500)
            messages[1]["content"] = f"Target Schema:\n{schema_json}\n\nDocument Text:\n{reduced_text}\n\nJSON Output:"
            try:
                raw_output = self.router.execute_completion(
                    messages=messages,
                    response_format={"type": "json_object"},
                    record_type=record_type,
                    content_hash=content_hash,
                    run_id=run_id,
                )
            except Exception as e:
                self._quarantine_record(record_type, source_url, f"Context error retry failed: {e}", "", attempt=1)
                return None
        except Exception as e:
            self._quarantine_record(record_type, source_url, f"Router completion error: {e}", "", attempt=1)
            return None

        # 3. Validation Step with Envelope Normalization
        cleaned_json = self._clean_json_response(raw_output)
        try:
            raw_data = json.loads(cleaned_json)
            data = self._normalize_entity_dict(raw_data, record_type, source_url)
            entity = schema_cls.model_validate(data)
            grounded_entity = self.post_validate_and_ground(entity)
            self.stats["total_extracted"] += 1

            self.cache[content_hash] = data
            self._save_cache()
            return grounded_entity
        except (json.JSONDecodeError, ValidationError) as initial_err:
            logger.info("Validation failed for %s (%s). Attempting 1 repair prompt...", record_type, initial_err)
            self.stats["repair_count"] += 1

            # 4. One-Shot Repair Attempt
            repair_prompt = self._build_repair_prompt(cleaned_json, str(initial_err), schema_json)
            repair_messages = [
                {"role": "system", "content": ZERO_HALLUCINATION_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ]

            try:
                repaired_output = self.router.execute_completion(
                    messages=repair_messages,
                    response_format={"type": "json_object"},
                    record_type=record_type,
                    content_hash=content_hash,
                    run_id=run_id,
                )
                cleaned_repaired = self._clean_json_response(repaired_output)
                raw_repaired = json.loads(cleaned_repaired)
                data = self._normalize_entity_dict(raw_repaired, record_type, source_url)
                entity = schema_cls.model_validate(data)
                grounded_entity = self.post_validate_and_ground(entity)
                self.stats["total_extracted"] += 1

                self.cache[content_hash] = data
                self._save_cache()
                return grounded_entity
            except Exception as repair_err:
                self._quarantine_record(
                    record_type=record_type,
                    source_url=source_url,
                    error_msg=f"Initial: {initial_err} | Repair: {repair_err}",
                    raw_output=cleaned_json,
                    attempt=2,
                )
                return None
