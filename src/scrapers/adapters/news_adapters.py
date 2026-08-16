"""Authoritative News Adapters for Key-Based and Public API Sources."""

import logging
import os
from typing import Any, Dict, List, Optional
import aiohttp

from src.scrapers.adapters.base import BaseSourceAdapter
from src.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)


class DataCubeNewsAdapter(BaseSourceAdapter):
    """Public adapter for DataCube AI news feed (No auth required)."""

    def __init__(self, http_client: Optional[ResilientHttpClient] = None):
        super().__init__(
            name="DataCube AI",
            category="News",
            base_url="https://datacube.ai/api/v1/news",
            auth_type="none",
            http_client=http_client,
        )

    @property
    def is_configured(self) -> bool:
        return True

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        candidates = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        try:
            data = await self.http_client.get_json(
                session=session,
                url=self.base_url,
                headers=headers,
                params={"limit": limit, "category": "ai"},
                timeout=4.0,
            )
            if data and isinstance(data, list):
                for item in data:
                    url = item.get("url") or item.get("link")
                    title = item.get("title") or item.get("headline", "")
                    raw_date = item.get("published_at") or item.get("date")
                    summary = item.get("summary") or item.get("description", "")

                    if not url or not title:
                        continue

                    candidates.append({
                        "source_name": self.name,
                        "source_url": url.strip(),
                        "title": title.strip(),
                        "published_date": raw_date,
                        "raw_content": summary.strip(),
                        "is_resolved": True,
                        "raw_metadata": item,
                    })
        except Exception as e:
            logger.warning("DataCube news fetch error: %s", e)
        return candidates


class NoozraNewsAdapter(BaseSourceAdapter):
    """Public adapter for Noozra Tech Articles with cursor pagination (No auth required)."""

    def __init__(self, http_client: Optional[ResilientHttpClient] = None):
        super().__init__(
            name="Noozra",
            category="News",
            base_url="https://noozra.com/api/articles",
            auth_type="none",
            http_client=http_client,
        )

    @property
    def is_configured(self) -> bool:
        return True

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        candidates = []
        try:
            data = await self.http_client.get_json(
                session=session,
                url=self.base_url,
                params={"category": "tech", "limit": min(limit, 100)},
                timeout=4.0,
            )
            articles = []
            if isinstance(data, list):
                articles = data
            elif isinstance(data, dict):
                articles = data.get("articles") or data.get("data") or []

            for item in articles:
                # Must have legitimate source URL - do NOT invent one
                source_url = item.get("url") or item.get("canonical_url") or item.get("link")
                title = item.get("title") or item.get("headline", "")
                raw_date = item.get("published_at") or item.get("date") or item.get("created_at")
                summary = item.get("summary") or item.get("description") or ""

                if not source_url:
                    continue

                # AI relevance filter to ensure high-fidelity AI & Data Science news only
                text_to_check = f"{title} {summary}".lower()
                ai_terms = [
                    "ai", "artificial intelligence", "llm", "large language model",
                    "machine learning", "deep learning", "neural", "openai", "anthropic",
                    "gemini", "gpt", "model", "robot", "robotics", "data science",
                    "data scientist", "big data", "analytics", "rag", "generative ai",
                    "genai", "diffusion", "transformer", "agent", "pytorch",
                    "databricks", "snowflake", "claude", "meta ai", "deepmind"
                ]
                if not any(term in text_to_check for term in ai_terms):
                    continue

                pub_name = item.get("source_name") or item.get("publisher") or self.name
                candidates.append({
                    "source_name": pub_name,
                    "source_url": source_url.strip(),
                    "title": title.strip(),
                    "published_date": raw_date,
                    "raw_content": summary.strip(),
                    "is_resolved": True,
                    "raw_metadata": item,
                })
        except Exception as e:
            logger.warning("Noozra fetch error: %s", e)
        return candidates


class NewsflashNewsAdapter(BaseSourceAdapter):
    """Authenticated adapter for Newsflash API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        super().__init__(
            name="Newsflash",
            category="News",
            base_url="https://newsflash.io/api/v1/news",
            auth_type="api_key_header",
            http_client=http_client,
        )
        self.api_key = api_key if api_key is not None else (os.getenv("NEWSFLASH_API_KEY") or os.getenv("NEWS_FLASH_API_KEY"))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.warning("Newsflash API key is not configured; skipping.")
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        topics = ["ai", "machine-learning", "data-science"]
        candidates = []
        seen_urls = set()

        for topic in topics:
            if len(candidates) >= limit:
                break
            try:
                data = await self.http_client.get_json(
                    session=session,
                    url=self.base_url,
                    headers=headers,
                    params={"topic": topic, "limit": min(limit, 25)},
                    timeout=4.0,
                )
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("news") or data.get("articles") or []

                for item in items:
                    url = item.get("url") or item.get("link")
                    title = item.get("title") or item.get("headline", "")
                    raw_date = item.get("published_at") or item.get("date")
                    summary = item.get("summary") or item.get("body", "")

                    if not url or str(url).strip() in seen_urls:
                        continue

                    seen_urls.add(str(url).strip())
                    candidates.append({
                        "source_name": item.get("publisher") or self.name,
                        "source_url": url.strip(),
                        "title": title.strip(),
                        "published_date": raw_date,
                        "raw_content": summary.strip(),
                        "is_resolved": True,
                        "raw_metadata": item,
                    })
            except Exception as e:
                logger.warning("Newsflash request error for topic '%s': %s", topic, e)
        return candidates


class GNewsAdapter(BaseSourceAdapter):
    """Authenticated adapter for official GNews API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        super().__init__(
            name="GNews",
            category="News",
            base_url="https://gnews.io/api/v4/search",
            auth_type="api_key_query",
            http_client=http_client,
        )
        self.api_key = api_key if api_key is not None else os.getenv("GNEWS_API_KEY")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.warning("GNews API key is not configured; skipping.")
            return []

        params = {
            "q": "artificial intelligence OR machine learning OR data science OR generative AI",
            "lang": "en",
            "max": min(limit, 50),
            "apikey": self.api_key,
        }
        candidates = []
        try:
            data = await self.http_client.get_json(
                session=session,
                url=self.base_url,
                params=params,
                timeout=5.0,
            )
            if data and isinstance(data, dict):
                articles = data.get("articles", [])
                for item in articles:
                    url = item.get("url")
                    title = item.get("title", "")
                    raw_date = item.get("publishedAt")
                    summary = item.get("description") or item.get("content", "")
                    src_obj = item.get("source", {})
                    src_name = src_obj.get("name") if isinstance(src_obj, dict) else self.name

                    if not url or not title:
                        continue

                    candidates.append({
                        "source_name": src_name or self.name,
                        "source_url": url.strip(),
                        "title": title.strip(),
                        "published_date": raw_date,
                        "raw_content": summary.strip(),
                        "is_resolved": True,
                        "raw_metadata": item,
                    })
        except Exception as e:
            logger.warning("GNews fetch error: %s", e)
        return candidates


class GuardianNewsAdapter(BaseSourceAdapter):
    """Authenticated adapter for The Guardian Open Platform Content API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        super().__init__(
            name="The Guardian",
            category="News",
            base_url="https://content.guardianapis.com/search",
            auth_type="api_key_query",
            http_client=http_client,
        )
        self.api_key = api_key if api_key is not None else os.getenv("GUARDIAN_API_KEY")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.warning("The Guardian API key is not configured; skipping.")
            return []

        params = {
            "q": "artificial intelligence OR machine learning OR data science OR generative AI",
            "section": "technology",
            "show-fields": "headline,byline,trailText,bodyText",
            "page-size": min(limit, 50),
            "api-key": self.api_key,
        }
        candidates = []
        try:
            data = await self.http_client.get_json(
                session=session,
                url=self.base_url,
                params=params,
                timeout=5.0,
            )
            if data and isinstance(data, dict):
                results = data.get("response", {}).get("results", [])
                for item in results:
                    url = item.get("webUrl")
                    title = item.get("webTitle") or item.get("fields", {}).get("headline", "")
                    raw_date = item.get("webPublicationDate")
                    fields = item.get("fields", {})
                    summary = fields.get("trailText") or fields.get("bodyText", "")[:500]

                    if not url or not title:
                        continue

                    candidates.append({
                        "source_name": "The Guardian",
                        "source_url": url.strip(),
                        "title": title.strip(),
                        "published_date": raw_date,
                        "raw_content": summary.strip(),
                        "is_resolved": True,
                        "raw_metadata": item,
                    })
        except Exception as e:
            logger.warning("Guardian Content API error: %s", e)
        return candidates
