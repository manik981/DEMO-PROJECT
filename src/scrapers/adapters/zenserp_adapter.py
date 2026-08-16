"""Zenserp Discovery & Search Adapter.

ROLE: Search / Discovery Utility ONLY.
Search results may only produce candidate URLs for downstream crawling.
Final records must retain legitimate source URLs from the actual target pages.
"""

import logging
import os
from typing import Any, Dict, List, Optional
import aiohttp

from src.scrapers.adapters.base import BaseSourceAdapter
from src.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)


class ZenserpDiscoveryAdapter(BaseSourceAdapter):
    """Discovery utility for finding candidate URLs via Zenserp Search API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        super().__init__(
            name="Zenserp",
            category="Discovery / Search",
            base_url="https://app.zenserp.com/api/v2/search",
            auth_type="api_key_query",
            http_client=http_client,
        )
        self.api_key = api_key if api_key is not None else os.getenv("ZENSERP_API_KEY")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def search_candidates(
        self, session: aiohttp.ClientSession, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Query Zenserp to discover candidate target URLs for downstream ingestion."""
        if not self.is_configured:
            logger.warning("Zenserp API key is not configured; skipping discovery.")
            return []

        params = {
            "apikey": self.api_key,
            "q": query,
            "num": min(limit, 20),
        }
        candidates = []
        try:
            data = await self.http_client.get_json(
                session=session,
                url=self.base_url,
                params=params,
                timeout=15.0,
            )
            if data and isinstance(data, dict):
                organic = data.get("organic", [])
                for item in organic:
                    url = item.get("url")
                    title = item.get("title", "")
                    description = item.get("description", "")
                    if url:
                        candidates.append({
                            "candidate_url": url,
                            "title": title,
                            "snippet": description,
                            "discovered_via": "zenserp",
                        })
        except Exception as e:
            logger.warning("Zenserp search error: %s", e)
        return candidates

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Base adapter implementation for discovery search."""
        return await self.search_candidates(session, query="latest artificial intelligence news breakthroughs", limit=limit)
