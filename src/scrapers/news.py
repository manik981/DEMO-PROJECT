"""News Ingestion Pipeline with 24-Hour Freshness Auditing and Multi-Source Adapters.

Ingests AI news from authoritative publishers & API feeds:
1. TechCrunch AI (RSS)
2. VentureBeat AI (RSS)
3. The Verge AI (Atom)
4. MIT Technology Review AI (RSS)
5. Ars Technica AI (RSS)
6. DataCube AI (Public API Adapter)
7. Noozra (Public API Adapter)
8. Newsflash (Authenticated API Adapter)
9. GNews (Authenticated API Adapter)
10. The Guardian Open Platform (Authenticated API Adapter)

Applies multi-tier date resolution, strict 24h freshness window auditing (now - 24h <= pub_date <= now),
and streams valid NewsEntity records to data/raw/news.jsonl.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import xml.etree.ElementTree as ET
import aiohttp

from src.scrapers.adapters.news_adapters import (
    DataCubeNewsAdapter,
    GNewsAdapter,
    GuardianNewsAdapter,
    NewsflashNewsAdapter,
    NoozraNewsAdapter,
)
from src.schemas.news import NewsContent, NewsEntity
from src.schemas.shared import SourceInfo
from src.utils.date_resolver import DateResolver

logger = logging.getLogger(__name__)

ATOM_NS = "{http://www.w3.org/2005/Atom}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"


def is_strictly_ai_news(title: str, summary: str, source_name: str) -> bool:
    """Verify that article is strictly AI/Data Science related."""
    pure_ai_sources = {
        "TechCrunch AI", "VentureBeat AI", "The Verge AI", "MIT Technology Review AI",
        "AI News Global", "KDnuggets Data Science & AI", "MarkTechPost AI & Research",
        "SyncedReview AI", "Towards Data Science", "Towards AI", "Unite.AI", "The Decoder AI",
        "Analytics Vidhya AI & Data", "Machine Learning Mastery", "InsideBIGDATA AI",
        "IEEE Spectrum AI", "TechXplore AI & Robotics", "Datafloq AI & Data", "AI Trends",
        "OpenAI News", "Google AI & DeepMind Blog", "DeepMind Research", "Microsoft AI Blog",
        "AWS Machine Learning Blog", "NVIDIA AI News", "Hugging Face Blog", "LangChain Blog",
        "LlamaIndex Blog", "BAIR Berkeley AI Research"
    }
    if source_name in pure_ai_sources:
        return True

    text = f"{title} {summary}".lower()
    ai_keywords = [
        "ai", "artificial intelligence", "llm", "large language model", "machine learning",
        "deep learning", "neural", "gpt", "gemini", "claude", "mistral", "deepseek", "llama",
        "transformer", "diffusion", "computer vision", "robotics", "nlp", "generative ai",
        "genai", "agent", "agents", "pytorch", "tensorflow", "vector db", "rag", "fine-tuning",
        "supercomputer", "accelerator", "gpu", "npu", "chip", "semiconductor", "data science"
    ]
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in ai_keywords)


class NewsScraper:
    """High-fidelity 24-hour freshness crawler for AI news sources."""

    RSS_FEEDS = [
        # Major Tech AI Desks
        {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
        {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/"},
        {"name": "VentureBeat Data Infrastructure", "url": "https://venturebeat.com/category/data-infrastructure/feed/"},
        {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
        {"name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/feed/"},
        {"name": "Ars Technica AI", "url": "https://feeds.arstechnica.com/arstechnica/index"},
        {"name": "SiliconANGLE AI & Big Data", "url": "https://siliconangle.com/feed/"},
        {"name": "The Register AI & ML", "url": "https://www.theregister.com/software/ai_ml/headlines.atom"},
        {"name": "ZDNet AI", "url": "https://www.zdnet.com/topic/artificial-intelligence/rss.xml"},
        {"name": "Wired AI News", "url": "https://www.wired.com/feed/tag/ai/latest/rss"},

        # Specialist AI & Data Science Publications
        {"name": "AI News Global", "url": "https://www.artificialintelligence-news.com/feed/"},
        {"name": "KDnuggets Data Science & AI", "url": "https://www.kdnuggets.com/feed"},
        {"name": "MarkTechPost AI & Research", "url": "https://www.marktechpost.com/feed/"},
        {"name": "SyncedReview AI", "url": "https://syncedreview.com/feed/"},
        {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed"},
        {"name": "Towards AI", "url": "https://towardsai.net/feed"},
        {"name": "Unite.AI", "url": "https://www.unite.ai/feed/"},
        {"name": "The Decoder AI", "url": "https://the-decoder.com/feed/"},
        {"name": "Analytics Vidhya AI & Data", "url": "https://www.analyticsvidhya.com/feed/"},
        {"name": "Machine Learning Mastery", "url": "https://machinelearningmastery.com/feed/"},
        {"name": "InsideBIGDATA AI", "url": "https://insidebigdata.com/feed/"},
        {"name": "InfoQ AI, ML & Data", "url": "https://feed.infoq.com/ai-ml-data-eng/news/"},
        {"name": "IEEE Spectrum AI", "url": "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss"},
        {"name": "TechXplore AI & Robotics", "url": "https://techxplore.com/rss-feed/machine-learning-ai-news/"},
        {"name": "Datafloq AI & Data", "url": "https://datafloq.com/feed/"},
        {"name": "AI Trends", "url": "https://www.aitrends.com/feed/"},

        # Frontier AI Labs & Engineering Blogs
        {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml"},
        {"name": "Google AI & DeepMind Blog", "url": "https://blog.google/technology/ai/rss/"},
        {"name": "DeepMind Research", "url": "https://deepmind.google/blog/rss.xml"},
        {"name": "Microsoft AI Blog", "url": "https://blogs.microsoft.com/ai/feed/"},
        {"name": "AWS Machine Learning Blog", "url": "https://aws.amazon.com/blogs/machine-learning/feed/"},
        {"name": "NVIDIA AI News", "url": "https://blogs.nvidia.com/blog/category/deep-learning/feed/"},
        {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml"},
        {"name": "LangChain Blog", "url": "https://blog.langchain.dev/rss/"},
        {"name": "LlamaIndex Blog", "url": "https://www.llamaindex.ai/blog/rss.xml"},
        {"name": "BAIR Berkeley AI Research", "url": "https://bair.berkeley.edu/blog/feed.xml"},

        # High-Frequency Realtime Streams (AI filtered)
        {"name": "Hacker News AI Headlines", "url": "https://hnrss.org/newest?q=AI+OR+LLM+OR+OpenAI+OR+Anthropic+OR+Mistral+OR+DeepSeek"},
        {"name": "Hacker News Top AI Stories", "url": "https://hnrss.org/frontpage?q=AI+OR+LLM+OR+Machine+Learning"},
        {"name": "Hacker News AI Showcases", "url": "https://hnrss.org/show?q=AI+OR+LLM+OR+GPT+OR+Model"},
    ]

    def __init__(
        self,
        freshness_hours: float = 24.0,
        raw_output_path: Optional[str] = "data/raw/news.jsonl",
        date_resolver: Optional[DateResolver] = None,
    ):
        self.freshness_hours = freshness_hours
        self.raw_output_path = Path(raw_output_path) if raw_output_path else None
        self.date_resolver = date_resolver or DateResolver()
        self.seen_urls: Set[str] = set()

        # Initialize API Adapters
        self.adapters = [
            DataCubeNewsAdapter(),
            NoozraNewsAdapter(),
            NewsflashNewsAdapter(),
            GNewsAdapter(),
            GuardianNewsAdapter(),
        ]

        self.stats = {"duplicates_skipped": 0}
        # Detailed freshness audit metrics across all feeds and adapters
        all_source_names = [f["name"] for f in self.RSS_FEEDS] + [ad.name for ad in self.adapters]
        self.audit_stats: Dict[str, Dict[str, int]] = {
            name: {
                "candidates_parsed": 0,
                "fresh_records": 0,
                "stale_records": 0,
                "invalid_dates": 0,
                "heuristic_dates": 0,
            }
            for name in all_source_names
        }

        if self.raw_output_path:
            self.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        """Load seen URLs to prevent duplicate processing."""
        if not self.raw_output_path or not self.raw_output_path.exists():
            return
        try:
            with open(self.raw_output_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        url = record.get("content", {}).get("url")
                        if url:
                            self.seen_urls.add(url)
                    except Exception:
                        continue
            logger.info("Loaded %d existing news records for deduplication.", len(self.seen_urls))
        except Exception as e:
            logger.warning("Failed to load existing news JSONL: %s", e)

    def _strip_html(self, text: str) -> str:
        """Strip HTML tags and normalize whitespace."""
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", " ", text)
        return " ".join(clean.split()).strip()

    def parse_feed_xml(self, xml_content: str, source_name: str) -> List[Dict[str, Any]]:
        """Parse RSS 2.0 or Atom XML content into raw candidate entries."""
        candidates = []
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.warning("Feed XML parse error for %s: %s", source_name, e)
            return []

        # 1. RSS 2.0
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or item.findtext(f"{DC_NS}date")
                description = (
                    item.findtext(f"{CONTENT_NS}encoded")
                    or item.findtext("description")
                    or ""
                )

                clean_desc = self._strip_html(description)[:500]
                candidates.append({
                    "source_name": source_name,
                    "title": self._strip_html(title),
                    "url": link.strip(),
                    "source_url": link.strip(),
                    "published_date": pub_date.strip() if pub_date else None,
                    "raw_content": clean_desc,
                    "summary": clean_desc,
                    "is_resolved": True,
                })
            return candidates

        # 2. Atom Feed
        for entry in root.findall(f"{ATOM_NS}entry"):
            title = entry.findtext(f"{ATOM_NS}title") or ""
            link = ""
            for link_elem in entry.findall(f"{ATOM_NS}link"):
                if link_elem.get("rel") in (None, "alternate"):
                    link = link_elem.get("href", "")
                    break

            pub_date = (
                entry.findtext(f"{ATOM_NS}published")
                or entry.findtext(f"{ATOM_NS}updated")
            )
            summary = (
                entry.findtext(f"{ATOM_NS}content")
                or entry.findtext(f"{ATOM_NS}summary")
                or ""
            )

            clean_sum = self._strip_html(summary)[:500]
            candidates.append({
                "source_name": source_name,
                "title": self._strip_html(title),
                "url": link.strip(),
                "source_url": link.strip(),
                "published_date": pub_date.strip() if pub_date else None,
                "raw_content": clean_sum,
                "summary": clean_sum,
                "is_resolved": True,
            })

        return candidates

    async def fetch_rss_feed(
        self, session: aiohttp.ClientSession, feed: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """Fetch raw candidates from RSS feed."""
        name = feed["name"]
        url = feed["url"]
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AIIntelligenceBot/1.0; +https://example.com/bot)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        }
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=4.0, connect=2.0)) as resp:
                if resp.status == 200:
                    xml_text = await resp.text()
                    return self.parse_feed_xml(xml_text, name)
        except Exception as e:
            logger.warning("Error harvesting feed %s: %s", name, e)
        return []

    async def harvest_fresh_news(self) -> List[NewsEntity]:
        """Harvest fresh articles across all RSS publishers and API adapters concurrently."""
        all_fresh: List[NewsEntity] = []
        connector = aiohttp.TCPConnector(limit=30)

        async with aiohttp.ClientSession(connector=connector) as session:
            # 1. Dispatch RSS feed tasks
            rss_tasks = [self.fetch_rss_feed(session, feed) for feed in self.RSS_FEEDS]
            # 2. Dispatch API adapter tasks
            adapter_tasks = [ad.fetch_candidates(session, limit=50) for ad in self.adapters if ad.is_configured]

            all_tasks = rss_tasks + adapter_tasks
            results = await asyncio.gather(*all_tasks, return_exceptions=True)

            candidate_list: List[Dict[str, Any]] = []
            for res in results:
                if isinstance(res, list):
                    candidate_list.extend(res)

            # 3. Apply Unified Freshness Gate, Deduplication, and Normalization
            for cand in candidate_list:
                src_name = cand.get("source_name", "AI News")
                if src_name not in self.audit_stats:
                    self.audit_stats[src_name] = {
                        "candidates_parsed": 0, "fresh_records": 0,
                        "stale_records": 0, "invalid_dates": 0, "heuristic_dates": 0,
                    }

                article_url = cand.get("source_url")
                if not article_url:
                    continue

                self.audit_stats[src_name]["candidates_parsed"] += 1

                if article_url in self.seen_urls:
                    self.stats["duplicates_skipped"] += 1
                    continue

                raw_date = cand.get("published_date")
                pub_dt, date_source, is_heuristic, freshness_verified = self.date_resolver.resolve_date(
                    rss_date=str(raw_date) if raw_date else None,
                    url=article_url,
                )

                if is_heuristic:
                    self.audit_stats[src_name]["heuristic_dates"] += 1

                # Strict Freshness Filter: now - 24h <= pub_dt <= now
                if not self.date_resolver.is_within_freshness_window(pub_dt, hours=self.freshness_hours):
                    self.audit_stats[src_name]["stale_records"] += 1
                    continue

                # Strict AI Relevance Gate: ensure candidate is strictly AI/ML/Data Science related
                cand_title = cand.get("title", "AI News Article")
                cand_summary = cand.get("raw_content", "")[:500]
                if not is_strictly_ai_news(cand_title, cand_summary, src_name):
                    continue

                self.audit_stats[src_name]["fresh_records"] += 1

                entity = NewsEntity(
                    schemaVersion="1.0",
                    recordType="NEWS",
                    source=SourceInfo(
                        name=src_name,
                        url=article_url,
                    ),
                    content=NewsContent(
                        title=cand.get("title", "AI News Article"),
                        url=article_url,
                        published_date=pub_dt,
                        summary=cand.get("raw_content", "")[:500],
                    ),
                    collectedAt=datetime.now(timezone.utc),
                )

                self.seen_urls.add(article_url)
                all_fresh.append(entity)

        if all_fresh and self.raw_output_path:
            with open(self.raw_output_path, "a", encoding="utf-8") as f:
                for entity in all_fresh:
                    f.write(entity.model_dump_json() + "\n")

        logger.info("News harvest complete. Fresh records: %d", len(all_fresh))
        return all_fresh
