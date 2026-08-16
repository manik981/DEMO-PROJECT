"""Jobs Ingestion Pipeline with Deterministic Role-Family Classification and Multi-Source Adapters.

Ingests AI jobs across authoritative job sources & API adapters:
1. RemoteOK (Public JSON API)
2. WeWorkRemotely (RSS Feed)
3. Y Combinator Work at a Startup Feed
4. Hugging Face AI Community Jobs Feed
5. AI Jobs Global Feed
6. AI Dev Jobs (Public API Adapter)
7. Freehire (Public API Adapter)
8. Artificial Intelligence Jobs (Public Feed Adapter)
9. USAJOBS (Authenticated Federal Jobs API Adapter)

Applies multi-tier date resolution, 24-hour freshness audit (now - 24h <= pub_date <= now),
and deterministic role-family classification (Engineering, Research, Product, Other).
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import xml.etree.ElementTree as ET
import aiohttp

from src.scrapers.arbeitnow import ArbeitnowJobsAdapter
from src.scrapers.adapters.jobs_adapters import (
    ActiveJobsDbAdapter,
    AIDevJobsAdapter,
    ArtificialIntelligenceJobsAdapter,
    FreehireJobsAdapter,
    IndeedJobsAdapter,
    USAJobsAdapter,
)
from src.schemas.job import JobContent, JobEntity
from src.utils.ai_job_filter import is_ai_job
from src.utils.date_resolver import DateResolver
from src.utils.role_classifier import classify_role_family

logger = logging.getLogger(__name__)


class JobsScraper:
    """High-fidelity fresh AI jobs harvester with multi-adapter ingestion."""

    RSS_SOURCES = [
        {"name": "RemoteOK (AI)", "url": "https://remoteok.com/api?tag=ai", "is_json": True},
        {"name": "RemoteOK (Data Science)", "url": "https://remoteok.com/api?tag=data-science", "is_json": True},
        {"name": "RemoteOK (Machine Learning)", "url": "https://remoteok.com/api?tag=machine-learning", "is_json": True},
        {"name": "RemoteOK (Data Engineering)", "url": "https://remoteok.com/api?tag=data-engineering", "is_json": True},
        {"name": "RemoteOK (Deep Learning)", "url": "https://remoteok.com/api?tag=deep-learning", "is_json": True},
        {"name": "RemoteOK (Python)", "url": "https://remoteok.com/api?tag=python", "is_json": True},
        {"name": "RemoteOK (NLP)", "url": "https://remoteok.com/api?tag=nlp", "is_json": True},
        {"name": "RemoteOK (LLM)", "url": "https://remoteok.com/api?tag=llm", "is_json": True},
        {"name": "WeWorkRemotely (Programming)", "url": "https://weworkremotely.com/categories/remote-programming-jobs.rss", "is_json": False},
        {"name": "WeWorkRemotely (DevOps & Data)", "url": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss", "is_json": False},
        {"name": "WeWorkRemotely (Back-End)", "url": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss", "is_json": False},
        {"name": "YC Work at a Startup", "url": "https://hnrss.org/jobs?q=AI+OR+ML+OR+Data+OR+LLM", "is_json": False},
        {"name": "Hacker News - Who is Hiring (AI & Data)", "url": "https://hnrss.org/whoishiring/jobs?q=AI+OR+LLM+OR+Machine+Learning+OR+Data+Science", "is_json": False},
        {"name": "Hacker News - Remote AI Jobs", "url": "https://hnrss.org/jobs?q=AI+OR+Data+Science+OR+PyTorch+OR+ML", "is_json": False},
        {"name": "Remotive (Data)", "url": "https://remotive.com/api/remote-jobs?category=data", "is_json": True},
        {"name": "Remotive (Software Dev / AI)", "url": "https://remotive.com/api/remote-jobs?category=software-dev", "is_json": True},
        {"name": "Remotive (AI Search)", "url": "https://remotive.com/api/remote-jobs?search=ai", "is_json": True},
        {"name": "Remotive (ML Search)", "url": "https://remotive.com/api/remote-jobs?search=machine%20learning", "is_json": True},
        {"name": "Remotive (Data Science Search)", "url": "https://remotive.com/api/remote-jobs?search=data%20science", "is_json": True},
        {"name": "Jobspresso Dev & AI", "url": "https://jobspresso.co/category/dev/feed/", "is_json": False},
    ]

    def __init__(
        self,
        freshness_hours: float = 24.0,
        raw_output_path: Optional[str] = "data/raw/jobs.jsonl",
        date_resolver: Optional[DateResolver] = None,
    ):
        self.freshness_hours = freshness_hours
        self.raw_output_path = Path(raw_output_path) if raw_output_path else None
        self.date_resolver = date_resolver or DateResolver()
        self.seen_jobs: Set[str] = set()

        # Initialize API Adapters (Including Arbeitnow, Indeed RapidAPI, and Active Jobs DB RapidAPI)
        self.adapters = [
            ArbeitnowJobsAdapter(),
            IndeedJobsAdapter(),
            ActiveJobsDbAdapter(),
            AIDevJobsAdapter(),
            FreehireJobsAdapter(),
            ArtificialIntelligenceJobsAdapter(),
            USAJobsAdapter(),
        ]

        self.stats = {"duplicates_skipped": 0}
        # Audit stats across all feeds and adapters
        all_source_names = [s["name"] for s in self.RSS_SOURCES] + [ad.name for ad in self.adapters]
        self.audit_stats: Dict[str, Dict[str, int]] = {
            name: {
                "candidates_parsed": 0,
                "fresh_records": 0,
                "stale_records": 0,
                "heuristic_dates": 0,
            }
            for name in all_source_names
        }

        if self.raw_output_path:
            self.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        """Load previously ingested job identifiers."""
        if not self.raw_output_path or not self.raw_output_path.exists():
            return
        try:
            with open(self.raw_output_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        content = record.get("content", {})
                        company = content.get("company", "")
                        title = content.get("title", "")
                        url = content.get("source_url", "")
                        if url:
                            self.seen_jobs.add(url.strip())
                        if company and title and url:
                            self.seen_jobs.add(f"{company}:{title}:{url}")
                            content_hash = hashlib.sha256(f"{company.lower().strip()}:{title.lower().strip()}::{url.strip()}".encode("utf-8")).hexdigest()
                            self.seen_jobs.add(content_hash)
                    except Exception:
                        continue
            logger.info("Loaded %d existing job records for deduplication.", len(self.seen_jobs))
        except Exception as e:
            logger.warning("Failed to load existing jobs JSONL: %s", e)

    def _clean_text(self, text: str) -> str:
        """Strip HTML and excess whitespace."""
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        return " ".join(clean.split()).strip()

    async def fetch_rss_or_json_feed(
        self, session: aiohttp.ClientSession, src: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Fetch candidates from RSS or direct JSON job feeds."""
        name = src["name"]
        url = src["url"]
        is_json = src.get("is_json", False)
        headers = {"User-Agent": "Mozilla/5.0"}
        candidates = []

        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=4.0, connect=2.0)) as resp:
                if resp.status != 200:
                    return []

                if is_json:
                    try:
                        data = await resp.json(content_type=None)
                        items = []
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict):
                            items = data.get("jobs", [])

                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            title = item.get("position") or item.get("title", "")
                            company = item.get("company_name") or item.get("company", "Remote AI Company")
                            link = item.get("url") or f"https://example.com/job/{item.get('id')}"
                            pub_date = item.get("date") or item.get("publication_date")

                            if not title:
                                continue

                            clean_title = self._clean_text(title)
                            clean_company = self._clean_text(company)

                            if not is_ai_job(title=clean_title, company=clean_company, source_name=name):
                                continue

                            candidates.append({
                                "source_name": name,
                                "title": clean_title,
                                "company": clean_company,
                                "source_url": link,
                                "published_date": pub_date,
                                "is_remote": True,
                            })
                    except Exception:
                        pass
                else:
                    # Parse RSS XML
                    xml_data = await resp.text()
                    try:
                        root = ET.fromstring(xml_data)
                        for item in root.findall(".//item"):
                            raw_title = item.findtext("title") or ""
                            desc = item.findtext("description") or ""
                            link = item.findtext("link") or ""
                            pub_date = item.findtext("pubDate") or ""

                            clean_desc = self._clean_text(desc)
                            clean_title = self._clean_text(raw_title)

                            # Handle Hacker News Who is Hiring comment threads
                            if "hnrss.org" in url or "Hacker News" in name or "whoishiring" in url:
                                # Extract Company & Role from description body (e.g. "Stripe | Senior ML Engineer | Remote")
                                first_chunk = clean_desc.split(".")[0] if "." in clean_desc else clean_desc
                                if "|" in first_chunk:
                                    parts = [p.strip() for p in first_chunk.split("|") if p.strip()]
                                    company = parts[0]
                                    title = parts[1] if len(parts) > 1 else "AI Software Engineer"
                                else:
                                    company = "YC / HN Startup"
                                    title = clean_title if "New comment" not in clean_title else "AI Software Engineer"
                            else:
                                title = clean_title
                                company = name
                                if ":" in title:
                                    parts = title.split(":", 1)
                                    company = parts[0].replace("is hiring", "").strip()
                                    title = parts[1].strip()
                                elif " at " in title:
                                    parts = title.split(" at ", 1)
                                    title = parts[0].strip()
                                    company = parts[1].strip()

                            if not title:
                                continue

                            clean_title_final = self._clean_text(title)
                            clean_company_final = self._clean_text(company)

                            # Strict AI validation
                            if not is_ai_job(title=clean_title_final, company=clean_company_final, description=clean_desc, source_name=name):
                                continue

                            is_remote = "remote" in clean_desc.lower() or "remote" in clean_title_final.lower() or True

                            candidates.append({
                                "source_name": name,
                                "title": clean_title_final,
                                "company": clean_company_final,
                                "source_url": link,
                                "published_date": pub_date,
                                "is_remote": is_remote,
                            })
                    except Exception:
                        pass

        except Exception as e:
            logger.warning("Error fetching feed %s: %s", name, e)

        return candidates

    async def harvest_fresh_jobs(self, target_count: int = 1000) -> List[JobEntity]:
        """Harvest fresh job listings across all RSS sources and API adapters concurrently."""
        all_jobs: List[JobEntity] = []
        connector = aiohttp.TCPConnector(limit=15)

        async with aiohttp.ClientSession(connector=connector) as session:
            feed_tasks = [self.fetch_rss_or_json_feed(session, src) for src in self.RSS_SOURCES]
            adapter_tasks = [ad.fetch_candidates(session, limit=target_count) for ad in self.adapters if ad.is_configured]

            all_tasks = feed_tasks + adapter_tasks
            results = await asyncio.gather(*all_tasks, return_exceptions=True)

            candidate_list: List[Dict[str, Any]] = []
            for res in results:
                if isinstance(res, list):
                    candidate_list.extend(res)

            for cand in candidate_list:
                src_name = cand.get("source_name", "AI Jobs Board")
                if src_name not in self.audit_stats:
                    self.audit_stats[src_name] = {
                        "candidates_parsed": 0, "fresh_records": 0,
                        "stale_records": 0, "heuristic_dates": 0,
                    }

                title = cand.get("title", "")
                company = cand.get("company", "Tech Company")
                url = cand.get("source_url", "")
                location = cand.get("location", "Remote")
                raw_date = cand.get("published_date")
                ext_id = cand.get("external_id")

                if not title or not url:
                    continue

                # Enforce strict AI / Machine Learning / Data Intelligence relevance
                if not is_ai_job(
                    title=title,
                    company=company,
                    tags=cand.get("raw_metadata", {}).get("tags") if isinstance(cand.get("raw_metadata"), dict) else None,
                    description=str(cand.get("raw_metadata", {}).get("description", "")) if isinstance(cand.get("raw_metadata"), dict) else "",
                    source_name=src_name,
                ):
                    continue

                self.audit_stats[src_name]["candidates_parsed"] += 1
                
                # Multi-tier deduplication: primary key (source + external_id) + fallback hash (company + title + location + url)
                simple_key = f"{company.lower().strip()}:{title.lower().strip()}:{url.strip()}"
                content_hash = hashlib.sha256(f"{company.lower().strip()}:{title.lower().strip()}:{location.lower().strip()}:{url.strip()}".encode("utf-8")).hexdigest()
                ext_key = f"{src_name}:{ext_id}" if ext_id else None

                if (ext_key and ext_key in self.seen_jobs) or (url in self.seen_jobs) or (simple_key in self.seen_jobs) or (content_hash in self.seen_jobs):
                    self.stats["duplicates_skipped"] += 1
                    continue

                pub_dt, _, is_heuristic, _ = self.date_resolver.resolve_date(
                    rss_date=str(raw_date) if raw_date else None,
                    url=url or None,
                )
                if is_heuristic:
                    self.audit_stats[src_name]["heuristic_dates"] += 1

                # Freshness filter: now - 24h <= pub_dt <= now
                if not self.date_resolver.is_within_freshness_window(pub_dt, hours=self.freshness_hours):
                    self.audit_stats[src_name]["stale_records"] += 1
                    continue

                self.audit_stats[src_name]["fresh_records"] += 1
                role_family = classify_role_family(title)

                entity = JobEntity(
                    schemaVersion="1.0",
                    recordType="JOB",
                    content=JobContent(
                        company=company,
                        title=title,
                        source_url=url,
                        source_name=src_name,
                        date=pub_dt,
                        is_remote=bool(cand.get("is_remote", True)),
                        role_family=role_family,
                    ),
                )

                if ext_key:
                    self.seen_jobs.add(ext_key)
                self.seen_jobs.add(url)
                self.seen_jobs.add(simple_key)
                self.seen_jobs.add(content_hash)
                all_jobs.append(entity)

                if len(all_jobs) >= target_count:
                    break

        if all_jobs and self.raw_output_path:
            with open(self.raw_output_path, "a", encoding="utf-8") as f:
                for entity in all_jobs:
                    f.write(entity.model_dump_json() + "\n")

        logger.info("Jobs harvest complete. Fresh records: %d", len(all_jobs))
        return all_jobs
