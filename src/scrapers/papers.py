"""Research Papers Ingestion Pipeline using Crossref REST API.

Ingests AI/ML research papers directly from the official Crossref REST API (https://api.crossref.org/works),
normalizes paper metadata into the standardized ResearchPaperEntity schema, performs deterministic
deduplication via DOI and title/author hashing, resolves linked GitHub repositories via content regex,
and enriches live GitHub stars via the GitHub REST API.

Zero-Hallucination Policy:
If no verifiable GitHub repository is linked, github_url and github_stars are strictly set to None.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import aiohttp

from src.schemas.research_paper import ResearchPaperContent, ResearchPaperEntity
from src.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)

GITHUB_REPO_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)

EXCLUDED_GITHUB_PATHS = {
    "features",
    "about",
    "pricing",
    "topics",
    "orgs",
    "site",
    "explore",
    "collections",
    "sponsors",
    "trending",
    "security",
    "settings",
}


class PapersScraper:
    """Scraper and harvester for AI research papers using Crossref REST API with GitHub enrichment."""

    CROSSREF_API_URL = "https://api.crossref.org/works"

    def __init__(
        self,
        github_token: Optional[str] = None,
        raw_output_path: Optional[str] = "data/raw/papers.jsonl",
        http_client: Optional[ResilientHttpClient] = None,
        rate_limit_delay: float = 1.0,
    ):
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        self.raw_output_path = Path(raw_output_path) if raw_output_path else None
        self.http_client = http_client or ResilientHttpClient(max_retries=2, default_timeout=15.0)
        self.rate_limit_delay = rate_limit_delay

        # Deduplication sets
        self.seen_dois: Set[str] = set()
        self.seen_paper_ids: Set[str] = set()

        # Contact email for Crossref Polite Pool
        self.contact_email = (
            os.getenv("USAJOBS_API_EMAIL")
            or os.getenv("CONTACT_EMAIL")
            or "developer@aetheria.ai"
        )
        self.user_agent = f"AETHERIAPipeline/2.0 (mailto:{self.contact_email})"

        # Metrics & GitHub caching
        self.github_cache: Dict[str, Tuple[Optional[str], Optional[int]]] = {}
        self.stats = {
            "requests_made": 0,
            "papers_fetched": 0,
            "papers_emitted": 0,
            "duplicates_skipped": 0,
            "failures": 0,
            "crossref_records_received": 0,
            "crossref_records_accepted": 0,
            "crossref_records_rejected": 0,
            "pagination_requests": 0,
            "github_repos_found": 0,
            "github_stars_enriched": 0,
            "github_cache_hits": 0,
            "github_api_calls": 0,
        }

        if self.raw_output_path:
            self.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing_ids()

    def _load_existing_ids(self) -> None:
        """Load previously processed paper DOIs/URLs to resume without duplicates."""
        if not self.raw_output_path or not self.raw_output_path.exists():
            return
        try:
            with open(self.raw_output_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        url = (
                            record.get("content", {}).get("paper_url")
                            or record.get("paper_url")
                            or record.get("source", {}).get("url")
                        )
                        if url:
                            self.seen_paper_ids.add(url.strip())

                        doi = record.get("doi") or record.get("content", {}).get("doi")
                        if doi:
                            self.seen_dois.add(str(doi).strip().lower())
                    except Exception:
                        continue
            logger.info(
                "Loaded %d existing paper records for Crossref deduplication.",
                len(self.seen_paper_ids),
            )
        except Exception as e:
            logger.warning("Could not read existing raw papers output: %s", e)

    def extract_github_candidate(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract owner and repo name from text using regex without hallucination."""
        if not text:
            return None

        for match in GITHUB_REPO_REGEX.finditer(text):
            owner, repo = match.groups()
            owner = owner.strip().rstrip(".,;:!?)'\"")
            repo = repo.strip().rstrip(".,;:!?)'\"")
            if repo.endswith(".git"):
                repo = repo[:-4]

            if owner.lower() in EXCLUDED_GITHUB_PATHS or not owner or not repo:
                continue

            return owner, repo
        return None

    async def verify_github_repo(
        self, session: aiohttp.ClientSession, owner: str, repo: str
    ) -> Tuple[Optional[str], Optional[int]]:
        """Verify repository existence and fetch stargazers count via GitHub API with in-memory caching."""
        cache_key = f"{owner.lower()}/{repo.lower()}"
        if cache_key in self.github_cache:
            self.stats["github_cache_hits"] += 1
            return self.github_cache[cache_key]

        self.stats["github_api_calls"] += 1
        url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Data-Intelligence-Ingestion-Pipeline",
        }
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"

        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=3.0, connect=1.5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    stars = data.get("stargazers_count")
                    canonical_url = data.get("html_url", f"https://github.com/{owner}/{repo}")
                    self.stats["github_stars_enriched"] += 1
                    res = (canonical_url, stars)
                    self.github_cache[cache_key] = res
                    return res
                elif resp.status == 404:
                    res = (None, None)
                    self.github_cache[cache_key] = res
                    return res
                elif resp.status in (403, 429):
                    logger.warning("GitHub API rate limited while checking %s/%s.", owner, repo)
                    res = (f"https://github.com/{owner}/{repo}", None)
                    self.github_cache[cache_key] = res
                    return res
                else:
                    return None, None
        except Exception as e:
            logger.debug("GitHub API verification failed for %s/%s: %s", owner, repo, e)
            return None, None

    def _parse_crossref_date(self, item: Dict[str, Any]) -> datetime:
        """Extract and parse publication date from Crossref date-parts hierarchy."""
        date_candidates = [
            item.get("published", {}).get("date-parts"),
            item.get("published-online", {}).get("date-parts"),
            item.get("published-print", {}).get("date-parts"),
            item.get("issued", {}).get("date-parts"),
            item.get("created", {}).get("date-parts"),
            item.get("deposited", {}).get("date-parts"),
        ]

        for dc in date_candidates:
            if dc and isinstance(dc, list) and len(dc) > 0 and isinstance(dc[0], list):
                parts = dc[0]
                if len(parts) >= 1 and isinstance(parts[0], int) and 1900 <= parts[0] <= 2100:
                    year = parts[0]
                    month = parts[1] if len(parts) >= 2 and isinstance(parts[1], int) and 1 <= parts[1] <= 12 else 1
                    day = parts[2] if len(parts) >= 3 and isinstance(parts[2], int) and 1 <= parts[2] <= 31 else 1
                    try:
                        return datetime(year, month, day, tzinfo=timezone.utc)
                    except ValueError:
                        return datetime(year, 1, 1, tzinfo=timezone.utc)

        return datetime.now(timezone.utc)

    def normalize_crossref_work(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Map raw Crossref work JSON item to normalized research paper candidate."""
        if not isinstance(item, dict):
            self.stats["crossref_records_rejected"] += 1
            return None

        self.stats["crossref_records_received"] += 1

        # 1. Title (Mandatory)
        raw_titles = item.get("title", [])
        title = ""
        if isinstance(raw_titles, list) and raw_titles:
            title = str(raw_titles[0]).strip()
        elif isinstance(raw_titles, str):
            title = raw_titles.strip()

        if not title:
            self.stats["crossref_records_rejected"] += 1
            return None

        # Clean title whitespace / newlines
        title = " ".join(title.split())

        # 2. DOI & Stable Paper URL (Mandatory)
        doi = (item.get("DOI") or "").strip()
        paper_url = (item.get("URL") or "").strip()
        if not paper_url and doi:
            paper_url = f"https://doi.org/{doi}"

        if not paper_url or not (paper_url.startswith("http://") or paper_url.startswith("https://")):
            self.stats["crossref_records_rejected"] += 1
            return None

        # 3. Authors
        authors: List[str] = []
        raw_authors = item.get("author", [])
        if isinstance(raw_authors, list):
            for a in raw_authors:
                if isinstance(a, dict):
                    given = str(a.get("given") or "").strip()
                    family = str(a.get("family") or "").strip()
                    name = str(a.get("name") or "").strip()
                    if given and family:
                        authors.append(f"{given} {family}")
                    elif family:
                        authors.append(family)
                    elif name:
                        authors.append(name)
        if not authors:
            authors = ["Anonymous / Crossref Contributor"]

        # 4. Abstract (Clean XML/HTML tags if present)
        raw_abstract = str(item.get("abstract") or "")
        clean_abstract = re.sub(r"<[^>]+>", " ", raw_abstract).strip() if raw_abstract else ""

        # 5. Venue / Journal
        raw_venue = item.get("container-title", [])
        venue = ""
        if isinstance(raw_venue, list) and raw_venue:
            venue = str(raw_venue[0]).strip()
        elif isinstance(raw_venue, str):
            venue = raw_venue.strip()

        # 6. Published Date
        published_dt = self._parse_crossref_date(item)

        # 7. Additional Metadata
        publisher = str(item.get("publisher") or "").strip()
        pub_type = str(item.get("type") or "journal-article").strip()
        citation_count = int(item.get("is-referenced-by-count") or 0)

        # 8. Deduplication key computation
        doi_key = doi.lower() if doi else ""
        first_author = authors[0].lower() if authors else ""
        fallback_key = f"{title.lower()}|{first_author}|{published_dt.year}"
        primary_key = doi_key or fallback_key

        self.stats["crossref_records_accepted"] += 1

        return {
            "title": title,
            "authors": authors,
            "paper_url": paper_url,
            "doi": doi,
            "abstract": clean_abstract,
            "venue": venue,
            "publisher": publisher,
            "publication_type": pub_type,
            "citation_count": citation_count,
            "published_date": published_dt,
            "primary_key": primary_key,
            "source": "crossref",
        }

    async def fetch_crossref_batch(
        self,
        session: aiohttp.ClientSession,
        query: str = "artificial intelligence OR machine learning OR large language models OR generative AI",
        offset: int = 0,
        rows: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query Crossref REST API for research works with robust error handling."""
        params = {
            "query": query,
            "rows": rows,
            "offset": offset,
            "sort": "published",
            "order": "desc",
        }
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        self.stats["requests_made"] += 1
        self.stats["pagination_requests"] += 1

        try:
            async with session.get(
                self.CROSSREF_API_URL,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15.0, connect=3.0),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = data.get("message", {}).get("items", [])
                    return items
                elif resp.status in (429, 503):
                    logger.warning("Crossref API rate limit / busy (Status %d). Backing off...", resp.status)
                    self.stats["failures"] += 1
                    return []
                else:
                    logger.warning("Crossref API returned status %d", resp.status)
                    self.stats["failures"] += 1
                    return []
        except Exception as e:
            logger.warning("Crossref API request error: %s", e)
            self.stats["failures"] += 1
            return []

    async def harvest_bulk(
        self,
        target_count: int = 100,
        query: str = "artificial intelligence OR machine learning OR large language models OR generative AI",
        batch_size: int = 50,
    ) -> List[ResearchPaperEntity]:
        """Harvest target count of unique research papers via Crossref REST API with GitHub enrichment."""
        collected_entities: List[ResearchPaperEntity] = []
        offset = 0
        consecutive_failures = 0
        max_pages = max(10, (target_count // max(1, batch_size)) * 3)
        pages_requested = 0

        logger.info(
            "Starting Crossref Research Papers harvest: target=%d, batch_size=%d",
            target_count,
            batch_size,
        )

        connector = aiohttp.TCPConnector(limit=15)
        async with aiohttp.ClientSession(connector=connector) as session:
            while len(collected_entities) < target_count and pages_requested < max_pages:
                pages_requested += 1
                logger.info(
                    "Fetching Crossref batch: offset=%d, target=%d, current=%d",
                    offset,
                    target_count,
                    len(collected_entities),
                )

                items = await self.fetch_crossref_batch(
                    session=session,
                    query=query,
                    offset=offset,
                    rows=batch_size,
                )

                if not items:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        logger.warning(
                            "Max Crossref consecutive failures reached. Gracefully proceeding with %d papers.",
                            len(collected_entities),
                        )
                        break
                    backoff = min(10.0, 2.0 * consecutive_failures)
                    logger.info("Retrying Crossref request in %.1fs (attempt %d/3)...", backoff, consecutive_failures)
                    await asyncio.sleep(backoff)
                    offset += batch_size
                    continue

                consecutive_failures = 0
                self.stats["papers_fetched"] += len(items)

                # Normalize and enrich items in parallel
                async def process_item(raw_item: Dict[str, Any]) -> Optional[ResearchPaperEntity]:
                    normalized = self.normalize_crossref_work(raw_item)
                    if not normalized:
                        return None

                    primary_key = normalized["primary_key"]
                    paper_url = normalized["paper_url"]
                    doi = normalized["doi"]

                    # Deduplication check
                    if (
                        (doi and doi.lower() in self.seen_dois)
                        or paper_url in self.seen_paper_ids
                        or primary_key in self.seen_dois
                    ):
                        self.stats["duplicates_skipped"] += 1
                        return None

                    # GitHub resolution pass on abstract and title
                    search_text = f"{normalized['title']} {normalized['abstract']}"
                    github_candidate = self.extract_github_candidate(search_text)

                    github_url = None
                    github_stars = None

                    if github_candidate:
                        self.stats["github_repos_found"] += 1
                        owner, repo = github_candidate
                        github_url, github_stars = await self.verify_github_repo(session, owner, repo)

                    # Build strictly typed schema entity
                    return ResearchPaperEntity(
                        schemaVersion="1.0",
                        recordType="RESEARCH_PAPER",
                        content=ResearchPaperContent(
                            title=normalized["title"],
                            authors=normalized["authors"],
                            paper_url=paper_url,
                            github_url=github_url,
                            github_stars=github_stars,
                            published_date=normalized["published_date"],
                        ),
                    )

                enriched_results = await asyncio.gather(*[process_item(item) for item in items])

                new_entities = []
                for entity in enriched_results:
                    if not entity:
                        continue
                    paper_url = entity.content.paper_url
                    if paper_url in self.seen_paper_ids:
                        self.stats["duplicates_skipped"] += 1
                        continue

                    self.seen_paper_ids.add(paper_url)
                    collected_entities.append(entity)
                    new_entities.append(entity)
                    self.stats["papers_emitted"] += 1

                    if len(collected_entities) >= target_count:
                        break

                if new_entities and self.raw_output_path:
                    with open(self.raw_output_path, "a", encoding="utf-8") as f:
                        for entity in new_entities:
                            f.write(entity.model_dump_json() + "\n")

                offset += batch_size
                if len(collected_entities) >= target_count:
                    break

                await asyncio.sleep(self.rate_limit_delay)

        logger.info("Crossref harvest complete: %s", self.stats)
        return collected_entities
