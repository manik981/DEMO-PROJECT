"""Authoritative Jobs Adapters for Key-Based and Public API Sources."""

import logging
import os
from typing import Any, Dict, List, Optional
import aiohttp

from src.scrapers.adapters.base import BaseSourceAdapter
from src.utils.ai_job_filter import is_ai_job
from src.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)


class AIDevJobsAdapter(BaseSourceAdapter):
    """Public adapter for AI Dev Jobs API (No auth required)."""

    def __init__(self, http_client: Optional[ResilientHttpClient] = None):
        super().__init__(
            name="AI Dev Jobs",
            category="Jobs",
            base_url="https://aidevboard.com/api/v1/jobs",
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
        queries = ["ai", "data science", "machine learning", "data engineer", "deep learning"]
        seen_urls = set()

        for q in queries:
            if len(candidates) >= limit:
                break
            try:
                data = await self.http_client.get_json(
                    session=session,
                    url=self.base_url,
                    params={"limit": min(limit, 50), "q": q},
                    timeout=4.0,
                )
                jobs = []
                if isinstance(data, list):
                    jobs = data
                elif isinstance(data, dict):
                    jobs = data.get("jobs") or data.get("data") or []

                for item in jobs:
                    url = item.get("url") or item.get("apply_url") or item.get("link")
                    title = item.get("title") or item.get("position", "")
                    company = item.get("company") or item.get("company_name", "AI Company")
                    raw_date = item.get("created_at") or item.get("published_at") or item.get("date")
                    is_remote = bool(item.get("is_remote") or item.get("remote") or True)

                    if not url or not title or str(url).strip() in seen_urls:
                        continue

                    if not is_ai_job(title=title, company=company, source_name=self.name):
                        continue

                    seen_urls.add(str(url).strip())
                    candidates.append({
                        "source_name": self.name,
                        "source_url": str(url).strip(),
                        "title": str(title).strip(),
                        "company": str(company).strip(),
                        "published_date": raw_date,
                        "is_remote": is_remote,
                        "is_resolved": True,
                        "raw_metadata": item,
                    })
            except Exception as e:
                logger.warning("AI Dev Jobs fetch error for query '%s': %s", q, e)
        return candidates


class FreehireJobsAdapter(BaseSourceAdapter):
    """Public adapter for Freehire Jobs Search API (No auth required)."""

    def __init__(self, http_client: Optional[ResilientHttpClient] = None):
        super().__init__(
            name="Freehire",
            category="Jobs",
            base_url="https://freehire.me/api/v1/jobs",
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
                params={"limit": min(limit, 50), "offset": 0},
                timeout=4.0,
            )
            if data and isinstance(data, dict):
                jobs = data.get("data", [])
                for item in jobs:
                    url = item.get("url") or item.get("link")
                    title = item.get("title") or item.get("role", "")
                    company = item.get("company") or item.get("employer", "Tech Employer")
                    raw_date = item.get("created_at") or item.get("date")
                    is_remote = bool(item.get("remote", True))

                    if not url or not title:
                        continue

                    # Strictly filter out non-AI jobs
                    if not is_ai_job(title=title, company=company, source_name=self.name):
                        continue

                    candidates.append({
                        "source_name": self.name,
                        "source_url": str(url).strip(),
                        "title": str(title).strip(),
                        "company": str(company).strip(),
                        "published_date": raw_date,
                        "is_remote": is_remote,
                        "is_resolved": True,
                        "raw_metadata": item,
                    })
        except Exception as e:
            logger.warning("Freehire fetch error: %s", e)
        return candidates


class ArtificialIntelligenceJobsAdapter(BaseSourceAdapter):
    """Public adapter for Artificial Intelligence Jobs feed."""

    def __init__(self, http_client: Optional[ResilientHttpClient] = None):
        super().__init__(
            name="Artificial Intelligence Jobs",
            category="Jobs",
            base_url="https://artificialintelligencejobs.net/feed/",
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
            xml_text = await self.http_client.get_text(
                session=session,
                url=self.base_url,
                timeout=4.0,
            )
            if xml_text:
                root = ET.fromstring(xml_text)
                for item in root.findall(".//item"):
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""

                    if not link or not title:
                        continue

                    company = "AI Employer"
                    if " at " in title:
                        parts = title.split(" at ", 1)
                        title = parts[0].strip()
                        company = parts[1].strip()
                    elif " - " in title:
                        parts = title.split(" - ", 1)
                        company = parts[0].strip()
                        title = parts[1].strip()

                    if not is_ai_job(title=title, company=company, source_name=self.name):
                        continue

                    candidates.append({
                        "source_name": self.name,
                        "source_url": str(link).strip(),
                        "title": str(title).strip(),
                        "company": str(company).strip(),
                        "published_date": pub_date,
                        "is_remote": True,
                        "is_resolved": True,
                        "raw_metadata": {"title": title, "link": link, "pubDate": pub_date},
                    })
        except Exception as e:
            logger.warning("Artificial Intelligence Jobs fetch error: %s", e)
        return candidates


class USAJobsAdapter(BaseSourceAdapter):
    """Authenticated adapter for USAJOBS Search API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_email: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        super().__init__(
            name="USAJOBS",
            category="Jobs",
            base_url="https://data.usajobs.gov/api/search",
            auth_type="api_key_headers",
            http_client=http_client,
        )
        self.api_key = api_key if api_key is not None else os.getenv("USAJOBS_API_KEY")
        self.api_email = api_email if api_email is not None else os.getenv("USAJOBS_API_EMAIL", "developer@example.com")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.warning("USAJOBS API key is not configured; skipping.")
            return []

        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": self.api_email,
            "Authorization-Key": self.api_key,
            "Accept": "application/json",
        }
        queries = ["Artificial Intelligence", "Data Science", "Machine Learning", "Data Scientist", "Data Engineer"]
        candidates = []
        seen_urls = set()

        for q in queries:
            if len(candidates) >= limit:
                break
            params = {
                "Keyword": q,
                "ResultsPerPage": min(limit, 25),
            }
            try:
                data = await self.http_client.get_json(
                    session=session,
                    url=self.base_url,
                    headers=headers,
                    params=params,
                    timeout=5.0,
                )
                if data and isinstance(data, dict):
                    items = data.get("SearchResult", {}).get("SearchResultItems", [])
                    for item in items:
                        desc = item.get("MatchedObjectDescriptor", {})
                        title = desc.get("PositionTitle", "")
                        company = desc.get("OrganizationName", "US Federal Agency")
                        url = desc.get("PositionURI", "")
                        raw_date = desc.get("PublicationStartDate", "")

                        user_area = desc.get("UserArea", {}).get("Details", {})
                        telework = user_area.get("TeleworkEligible", False)
                        is_remote = bool(telework or "remote" in str(title).lower())

                        if not url or not title or str(url).strip() in seen_urls:
                            continue

                        if not is_ai_job(title=title, company=company, source_name=self.name):
                            continue

                        seen_urls.add(str(url).strip())
                        candidates.append({
                            "source_name": self.name,
                            "source_url": str(url).strip(),
                            "title": str(title).strip(),
                            "company": str(company).strip(),
                            "published_date": raw_date,
                            "is_remote": is_remote,
                            "is_resolved": True,
                            "raw_metadata": desc,
                        })
            except Exception as e:
                logger.warning("USAJOBS fetch error for keyword '%s': %s", q, e)
        return candidates


class IndeedJobsAdapter(BaseSourceAdapter):
    """Authenticated adapter for Indeed API via RapidAPI (indeed12.p.rapidapi.com)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        super().__init__(
            name="Indeed (RapidAPI)",
            category="Jobs",
            base_url="https://indeed12.p.rapidapi.com",
            auth_type="api_key_headers",
            http_client=http_client,
        )
        self.api_key = api_key if api_key is not None else (
            os.getenv("RAPIDAPI_KEY") or os.getenv("INDEED_RAPIDAPI_KEY")
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.info("Indeed RapidAPI key is not configured; skipping.")
            return []

        headers = {
            "x-rapidapi-host": "indeed12.p.rapidapi.com",
            "x-rapidapi-key": self.api_key,
            "Content-Type": "application/json",
        }

        candidates = []
        endpoints_to_try = [
            f"{self.base_url}/jobs/search?query=artificial%20intelligence&location=us&page=1",
            f"{self.base_url}/jobs/search?query=machine%20learning%20engineer&location=us&page=1",
            f"{self.base_url}/jobs/search?query=data%20scientist&location=us&page=1",
            f"{self.base_url}/jobs/search?query=data%20engineer&location=us&page=1",
            f"{self.base_url}/jobs/search?query=ai%20engineer&location=us&page=1",
            f"{self.base_url}/jobs/search?query=llm%20engineer&location=us&page=1",
            f"{self.base_url}/jobs/search?query=deep%20learning%20engineer&location=us&page=1",
            f"{self.base_url}/jobs/search?query=computer%20vision%20engineer&location=us&page=1",
        ]

        seen_urls = set()
        for url in endpoints_to_try:
            if len(candidates) >= limit:
                break
            try:
                data = await self.http_client.get_json(
                    session=session,
                    url=url,
                    headers=headers,
                    timeout=7.5,
                )
                if not data:
                    continue

                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("hits") or data.get("jobs") or data.get("data") or data.get("results") or []

                for item in items[:limit]:
                    if not isinstance(item, dict):
                        continue

                    title = item.get("job_title") or item.get("title") or item.get("position", "")
                    company = item.get("company_name") or item.get("company") or "Tech Company"
                    job_url = item.get("link") or item.get("url") or item.get("job_url") or item.get("apply_url")
                    location = item.get("location") or item.get("formatted_location") or "Remote / US"
                    raw_date = item.get("date") or item.get("pub_date") or item.get("created_at") or item.get("formatted_relative_time")
                    is_remote = bool(item.get("is_remote") or item.get("remote") or "remote" in str(location).lower() or "remote" in str(title).lower())
                    job_id = item.get("id") or item.get("job_key") or item.get("job_id")

                    if not job_url:
                        if job_id:
                            job_url = f"https://www.indeed.com/viewjob?jk={job_id}"
                        else:
                            continue

                    if not title or str(job_url).strip() in seen_urls:
                        continue

                    # Strict AI relevance filter
                    if not is_ai_job(title=title, company=company, description=str(item.get("description", "")), source_name=self.name):
                        continue

                    seen_urls.add(str(job_url).strip())
                    candidates.append({
                        "source_name": self.name,
                        "source_url": str(job_url).strip(),
                        "title": str(title).strip(),
                        "company": str(company).strip(),
                        "location": str(location).strip(),
                        "published_date": raw_date,
                        "is_remote": is_remote,
                        "is_resolved": True,
                        "external_id": job_id,
                        "raw_metadata": item,
                    })

            except Exception as e:
                logger.warning("Indeed RapidAPI fetch error for endpoint %s: %s", url, e)

        logger.info("Indeed RapidAPI fetched %d candidate jobs.", len(candidates))
        return candidates


class ActiveJobsDbAdapter(BaseSourceAdapter):
    """Authenticated adapter for Active Jobs DB via RapidAPI (active-jobs-db.p.rapidapi.com)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_client: Optional[ResilientHttpClient] = None,
    ):
        super().__init__(
            name="Active Jobs DB (RapidAPI)",
            category="Jobs",
            base_url="https://active-jobs-db.p.rapidapi.com",
            auth_type="api_key_headers",
            http_client=http_client,
        )
        self.api_key = api_key if api_key is not None else (
            os.getenv("RAPIDAPI_KEY") or os.getenv("ACTIVE_JOBS_RAPIDAPI_KEY")
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    async def fetch_candidates(
        self, session: aiohttp.ClientSession, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.info("Active Jobs DB RapidAPI key is not configured; skipping.")
            return []

        headers = {
            "x-rapidapi-host": "active-jobs-db.p.rapidapi.com",
            "x-rapidapi-key": self.api_key,
            "Content-Type": "application/json",
        }

        candidates = []
        queries = [
            "AI Engineer", "Machine Learning", "Data Engineer", "Data Scientist",
            "Deep Learning", "MLOps", "LLM", "Data Analyst", "Applied Scientist"
        ]

        for query in queries:
            endpoint = (
                f"{self.base_url}/active-ats?"
                f"time_frame=24h&limit={min(limit, 25)}&offset=0&description_format=text&title=%22{query.replace(' ', '%20')}%22"
            )
            try:
                data = await self.http_client.get_json(
                    session=session,
                    url=endpoint,
                    headers=headers,
                    timeout=5.0,
                )
                if not data:
                    continue

                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("data") or data.get("results") or data.get("jobs") or []

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    title = item.get("title") or item.get("job_title") or item.get("position", "")
                    company = item.get("company") or item.get("company_name") or item.get("organization", "AI Tech Firm")
                    job_url = item.get("url") or item.get("apply_url") or item.get("link") or item.get("job_url")
                    location = item.get("location") or item.get("locations_raw") or item.get("country", "Remote")
                    raw_date = item.get("date_posted") or item.get("posted_at") or item.get("created_at") or item.get("date")
                    is_remote = bool(
                        item.get("is_remote") or item.get("remote")
                        or "remote" in str(location).lower()
                        or "remote" in str(title).lower()
                    )
                    job_id = item.get("id") or item.get("external_id")

                    if not job_url:
                        continue

                    if not title:
                        continue

                    # Strict AI relevance filter
                    if not is_ai_job(
                        title=title,
                        company=company,
                        description=str(item.get("description", "")),
                        source_name=self.name,
                    ):
                        continue

                    candidates.append({
                        "source_name": self.name,
                        "source_url": str(job_url).strip(),
                        "title": str(title).strip(),
                        "company": str(company).strip(),
                        "location": str(location).strip(),
                        "published_date": raw_date,
                        "is_remote": is_remote,
                        "is_resolved": True,
                        "external_id": job_id,
                        "raw_metadata": item,
                    })

                if candidates:
                    break
            except Exception as e:
                logger.warning("Active Jobs DB fetch error for query %s: %s", query, e)

        logger.info("Active Jobs DB fetched %d candidate jobs.", len(candidates))
        return candidates
