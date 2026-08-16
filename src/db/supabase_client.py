"""Supabase PostgreSQL Async Repository & Client.

Provides structured persistence, scoped deduplication, and audit logging into Supabase PostgreSQL tables:
1. startups
2. products
3. research_papers
4. jobs
5. news
6. entity_mapping_log
7. ingestion_runs
8. source_records_audit
9. llm_logs
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiohttp
from dotenv import load_dotenv

# Ensure environment is loaded
load_dotenv()

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Async repository layer connecting to Supabase PostgreSQL database."""

    def __init__(
        self,
        supabase_url: Optional[str] = None,
        supabase_secret_key: Optional[str] = None,
    ):
        raw_url = (
            supabase_url
            or os.getenv("SUPABASE_URL", "")
            or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
        ).strip("'\" \t\r\n")

        raw_key = (
            supabase_secret_key
            or os.getenv("SUPABASE_SECRET_KEY", "")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
            or os.getenv("SUPABASE_KEY", "")
            or os.getenv("SUPABASE_ANON_KEY", "")
        ).strip("'\" \t\r\n")

        self.supabase_url = raw_url.rstrip("/")
        self.supabase_key = raw_key
        self.rest_endpoint = f"{self.supabase_url}/rest/v1" if self.supabase_url else ""

    @property
    def is_configured(self) -> bool:
        """Verify presence of valid Supabase URL and Secret Key."""
        return bool(
            self.supabase_url
            and self.supabase_key
            and "your-project-ref" not in self.supabase_url
            and "your-supabase" not in self.supabase_url
            and self.supabase_key != "your_service_role_secret_key_here"
        )

    def _get_headers(self, prefer_resolution: str = "merge-duplicates") -> Dict[str, str]:
        """Build authorized headers for Supabase PostgREST API."""
        return {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": f"resolution={prefer_resolution},return=representation",
        }

    def compute_content_hash(self, content_str: str) -> str:
        """Compute SHA-256 hash for content-based deduplication."""
        return hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    async def upsert_records(
        self,
        table_name: str,
        records: List[Dict[str, Any]],
        conflict_columns: Optional[str] = None,
    ) -> int:
        """Batch upsert records into target Supabase table with duplicate ignoring."""
        if not self.is_configured:
            print(f"⚠️ [Supabase] Client not configured. SUPABASE_URL or SUPABASE_SECRET_KEY missing in .env.")
            return 0
        if not records:
            return 0

        url = f"{self.rest_endpoint}/{table_name}"
        params = {}
        if conflict_columns:
            params["on_conflict"] = conflict_columns

        headers = self._get_headers(prefer_resolution="merge-duplicates")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=records, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        inserted = len(data) if isinstance(data, list) else 0
                        logger.info("Successfully persisted %d records to Supabase table '%s'.", inserted, table_name)
                        return inserted
                    elif resp.status == 409:
                        logger.info("0 new records persisted to '%s' (all duplicates ignored).", table_name)
                        return 0
                    else:
                        text = await resp.text()
                        error_msg = f"❌ [Supabase] Table '{table_name}' returned status {resp.status}: {text[:300]}"
                        print(error_msg)
                        if resp.status == 400:
                            raise ValueError(error_msg)
                        return 0
        except Exception as e:
            print(f"❌ [Supabase] Failed to persist to table '{table_name}': {e}")
            if isinstance(e, ValueError):
                raise
            return 0

    async def get_table_count(self, table_name: str) -> int:
        """Get exact count of rows in a Supabase table."""
        if not self.is_configured:
            return 0

        url = f"{self.rest_endpoint}/{table_name}?select=*"
        headers = self._get_headers()
        headers["Prefer"] = "count=exact"
        headers["Range-Unit"] = "items"
        headers["Range"] = "0-0"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    cr = resp.headers.get("Content-Range", "")
                    if "/" in cr:
                        total = cr.split("/")[1]
                        if total != "*":
                            return int(total)
                    if resp.status == 200:
                        data = await resp.json()
                        return len(data) if isinstance(data, list) else 0
                    else:
                        text = await resp.text()
                        logger.debug("get_table_count failed for %s (status %d): %s", table_name, resp.status, text[:200])
        except Exception as e:
            logger.debug("Failed to get count for table %s: %s", table_name, e)
        return 0

    async def fetch_table_records(self, table_name: str, limit: int = 5000) -> List[Dict[str, Any]]:
        """Fetch all records from a target Supabase table."""
        if not self.is_configured:
            return []

        url = f"{self.rest_endpoint}/{table_name}?select=*&limit={limit}"
        headers = self._get_headers()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data if isinstance(data, list) else []
                    else:
                        logger.debug("fetch_table_records failed for %s (status %d)", table_name, resp.status)
        except Exception as e:
            logger.debug("Failed to fetch records from table %s: %s", table_name, e)
        return []

    async def delete_all_records(self, table_name: str) -> None:
        """Delete all records from a Supabase table."""
        if not self.is_configured:
            return

        url = f"{self.rest_endpoint}/{table_name}?id=not.is.null"
        headers = self._get_headers()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status not in (200, 204):
                        logger.error("Failed to clear table '%s': %s", table_name, await resp.text())
        except Exception as e:
            logger.error("Failed to clear table '%s': %s", table_name, e)

    async def delete_user_records(self, table_name: str, user_id: str) -> None:
        """Delete records matching user_id from a Supabase table."""
        if not self.is_configured:
            return

        url = f"{self.rest_endpoint}/{table_name}?user_id=eq.{user_id}"
        headers = self._get_headers()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status not in (200, 204):
                        logger.error("Failed to clear user records for table '%s': %s", table_name, await resp.text())
                    else:
                        logger.info("Successfully deleted user '%s' records from table '%s'.", user_id, table_name)
        except Exception as e:
            logger.error("Failed to clear user records for table '%s': %s", table_name, e)

    async def fetch_table_records(
        self, table_name: str, limit: int = 5000
    ) -> List[Dict[str, Any]]:
        """Fetch records from table for Google Sheets export or auditing."""
        if not self.is_configured:
            return []

        url = f"{self.rest_endpoint}/{table_name}?select=*&limit={limit}"
        headers = self._get_headers()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data if isinstance(data, list) else []
        except Exception as e:
            logger.error("Failed to fetch records from table '%s': %s", table_name, e)
        return []

    async def log_ingestion_run(
        self,
        run_id: str,
        phase: str,
        source_name: str,
        started_at: datetime,
        completed_at: Optional[datetime] = None,
        status: str = "completed",
        candidate_count: int = 0,
        accepted_count: int = 0,
        stale_count: int = 0,
        duplicate_count: int = 0,
        error_count: int = 0,
    ) -> None:
        """Persist pipeline audit run record."""
        run_record = {
            "run_id": run_id,
            "phase": phase,
            "source_name": source_name,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat() if completed_at else datetime.now(timezone.utc).isoformat(),
            "status": status,
            "candidate_count": candidate_count,
            "accepted_count": accepted_count,
            "stale_count": stale_count,
            "duplicate_count": duplicate_count,
            "error_count": error_count,
        }
        await self.upsert_records("ingestion_runs", [run_record])

    async def log_llm_call(
        self,
        model_name: str,
        tier: str = "primary",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        status: str = "success",
        run_id: Optional[str] = None,
        fallback_from: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        content_hash: Optional[str] = None,
        record_type: Optional[str] = None,
    ) -> None:
        """Persist LLM router execution metrics to Supabase."""
        llm_record = {
            "run_id": run_id,
            "model_name": model_name,
            "tier": tier,
            "fallback_from": fallback_from,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "status": status,
            "error_type": error_type,
            "error_message": error_message,
            "content_hash": content_hash,
            "record_type": record_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.upsert_records("llm_logs", [llm_record])


def get_supabase_client() -> SupabaseClient:
    """Helper factory for SupabaseClient."""
    return SupabaseClient()
