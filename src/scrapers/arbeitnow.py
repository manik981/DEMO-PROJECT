"""Arbeitnow Job Board API Adapter.

Fetches fresh job openings from Arbeitnow's public Job Board API (https://www.arbeitnow.com/api/job-board-api),
extracts and normalizes records to match the unified JobContent / JobEntity schema,
and isolates errors so pipeline execution continues uninterrupted.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import aiohttp

from src.scrapers.adapters.base import BaseSourceAdapter
from src.utils.ai_job_filter import is_ai_job
from src.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)

ARBEITNOW_API_ENDPOINT = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowJobsAdapter(BaseSourceAdapter):
    """Public adapter for Arbeitnow Job Board API (No authentication required)."""

    def __init__(self, http_client: Optional[ResilientHttpClient] = None):
        super().__init__(
            name="Arbeitnow",
            category="Jobs",
            base_url=ARBEITNOW_API_ENDPOINT,
            auth_type="none",
            http_client=http_client,
        )

    @property
    def is_configured(self) -> bool:
        """Public endpoint requires no API keys."""
        return True

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch candidates from Arbeitnow API and normalize to candidate schema."""
        candidates = []
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }
            data = await self.http_client.get_json(
                session=session,
                url=self.base_url,
                headers=headers,
                timeout=5.0,
            )

            if not data or not isinstance(data, dict):
                logger.warning("Arbeitnow API returned non-dict response.")
                return []

            items = data.get("data", [])
            for item in items[:limit]:
                if not isinstance(item, dict):
                    continue

                title = item.get("title", "")
                company = item.get("company_name", "Tech Employer")
                url = item.get("url", "")
                location = item.get("location", "Remote")
                is_remote = bool(item.get("remote", True))
                slug = item.get("slug", "")

                # Date normalization: handle Unix timestamp or ISO string
                raw_created = item.get("created_at")
                pub_date = None
                if isinstance(raw_created, (int, float)):
                    try:
                        pub_date = datetime.fromtimestamp(raw_created, timezone.utc).isoformat()
                    except Exception:
                        pub_date = str(raw_created)
                elif isinstance(raw_created, str):
                    pub_date = raw_created

                tags = item.get("tags", [])
                description = item.get("description", "")

                if not url or not title:
                    continue

                # Ensure candidate is AI/ML/Data intelligence related
                if not is_ai_job(title=title, company=company, tags=tags, description=description, source_name=self.name):
                    continue

                candidates.append({
                    "source_name": self.name,
                    "source_url": url.strip(),
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": location.strip(),
                    "published_date": pub_date,
                    "is_remote": is_remote,
                    "is_resolved": True,
                    "external_id": slug.strip() if slug else None,
                    "raw_metadata": item,
                })

            logger.info("Arbeitnow scraper fetched %d candidate jobs.", len(candidates))

        except Exception as e:
            # Failure isolation: Log warning and return empty candidate list so pipeline continues
            logger.warning("⚠️ Arbeitnow API fetch failed (isolated): %s", e)

        return candidates
