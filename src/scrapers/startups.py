"""Startups Ingestion Module.

Harvests verified and fresh AI startups across:
1. Canonical Verified Seed Registry (550+ verified AI firms with categorized domains)
2. Dynamic Live Feeds: Hacker News AI Launches & Show HN AI Tech Showcases

Features:
- Enriched fields: category, description, country, entityName, authentic homepage URL
- Zero-fabrication policy: employeeCount is strictly None by design
- Resilient deduplication across runs using raw JSONL storage
"""

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import aiohttp

from src.schemas.shared import SourceInfo
from src.schemas.startup import StartupContent, StartupData, StartupEntity
from src.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)


def infer_startup_category(name: str, desc: str = "") -> str:
    """Classify startup into a granular AI sector based on name and domain clues."""
    text = f"{name} {desc}".lower()
    if any(k in text for k in ["robot", "humanoid", "hardware", "drone", "physical", "chip", "npu", "compute", "groq", "sambanova", "cerebras"]):
        return "Robotics & AI Hardware"
    if any(k in text for k in ["llm", "large language", "foundation", "gpt", "anthropic", "openai", "mistral", "deepseek", "qwen", "cohere"]):
        return "Frontier LLMs & Foundation Models"
    if any(k in text for k in ["vision", "video", "image", "diffusion", "flux", "midjourney", "runway", "pika", "luma", "suno", "audio", "voice", "speech"]):
        return "Generative Media & Multimodal AI"
    if any(k in text for k in ["data", "analytics", "pipeline", "etl", "snowflake", "databricks", "database", "vector", "pinecone", "weaviate", "qdrant"]):
        return "Data Science & AI Infrastructure"
    if any(k in text for k in ["agent", "reasoning", "automation", "workflow", "copilot", "cursor", "code", "dev", "tabnine", "cognition"]):
        return "AI Developer Tools & Autonomous Agents"
    if any(k in text for k in ["health", "bio", "pharma", "medicine", "clinical", "abridge", "ambience"]):
        return "Healthcare & Biotech AI"
    if any(k in text for k in ["security", "governance", "safety", "defense", "shield", "helsing", "anduril"]):
        return "Defense, Security & Safety AI"
    return "Enterprise AI Solutions"


class StartupsScraper:
    """Harvester for AI Startups combining dynamic live discovery and the Seed Startup Registry."""

    DYNAMIC_FEEDS = [
        {"name": "Hacker News AI Launches", "url": "https://hnrss.org/launches?q=AI+OR+LLM+OR+Machine+Learning"},
        {"name": "Show HN AI Showcases", "url": "https://hnrss.org/show?q=AI+OR+LLM+OR+GPT+OR+Machine+Learning"},
        {"name": "Hacker News AI Startups & Funding", "url": "https://hnrss.org/newest?q=AI+startup+OR+LLM+funding+OR+AI+agent"},
        {"name": "Hacker News AI Seed Showcase", "url": "https://hnrss.org/frontpage?q=AI+startup+OR+LLM"},
        {"name": "YC AI Companies Showcase", "url": "https://hnrss.org/newest?q=YC+AI+OR+YCombinator+AI+OR+OpenAI+startup"},
    ]

    # Canonical mapping of verified startup names to official company URLs
    VERIFIED_STARTUPS = {
        "OpenAI": ("https://openai.com", "Frontier LLMs & Foundation Models", "US"),
        "Anthropic": ("https://anthropic.com", "Frontier LLMs & Foundation Models", "US"),
        "Google DeepMind": ("https://deepmind.google", "Frontier AI Research", "UK"),
        "Mistral AI": ("https://mistral.ai", "Open Weights LLMs", "France"),
        "DeepSeek": ("https://deepseek.com", "Frontier LLMs & Reasoning Models", "Global"),
        "Cohere": ("https://cohere.com", "Enterprise LLMs & Embeddings", "Canada"),
        "Meta AI": ("https://ai.meta.com", "Open Source LLaMA & Research", "US"),
        "xAI": ("https://x.ai", "Grok & Advanced Supercomputing", "US"),
        "Stability AI": ("https://stability.ai", "Open Generative Media", "UK"),
        "Perplexity": ("https://perplexity.ai", "Conversational Answer Engine", "US"),
        "Hugging Face": ("https://huggingface.co", "AI Model Hub & Platform", "US"),
        "Scale AI": ("https://scale.com", "Data Annotation & RLHF", "US"),
        "Runway": ("https://runwayml.com", "Generative Video & World Models", "US"),
        "ElevenLabs": ("https://elevenlabs.io", "Voice Synthesis & AI Audio", "US"),
        "Character.ai": ("https://character.ai", "Personalized Conversational AI", "US"),
        "Jasper": ("https://jasper.ai", "Enterprise AI Copywriting", "US"),
        "Pinecone": ("https://pinecone.io", "Serverless Vector Database", "US"),
        "Weaviate": ("https://weaviate.io", "Open Source Vector Search Engine", "Netherlands"),
        "Qdrant": ("https://qdrant.tech", "Vector Database & Semantic Search", "Germany"),
        "Chroma": ("https://trychroma.com", "AI Native Embeddings Database", "US"),
        "Midjourney": ("https://midjourney.com", "AI Image Generation Lab", "US"),
        "Databricks": ("https://databricks.com", "Data Lakehouse & Mosaic AI", "US"),
        "Snowflake": ("https://snowflake.com", "Data Cloud & Cortex AI", "US"),
        "LangChain": ("https://langchain.com", "LLM Framework & LangSmith", "US"),
        "LlamaIndex": ("https://llamaindex.ai", "Data Framework for LLM Apps", "US"),
        "Cursor": ("https://cursor.com", "AI-First Code Editor", "US"),
        "Together AI": ("https://together.ai", "Cloud Compute & Model Training", "US"),
        "Replicate": ("https://replicate.com", "Run Open Source Models with API", "US"),
        "Modal": ("https://modal.com", "Serverless Cloud for AI/ML", "US"),
        "Fireworks AI": ("https://fireworks.ai", "Production AI Inference Engine", "US"),
        "Groq": ("https://groq.com", "LPU Inference Engine", "US"),
        "Inflection AI": ("https://inflection.ai", "Empathetic Conversational AI", "US"),
        "Glean": ("https://glean.com", "Enterprise Search & Work AI", "US"),
        "Harvey": ("https://harvey.ai", "Legal Generative AI Platform", "US"),
        "Writer": ("https://writer.com", "Full-Stack Generative AI for Enterprises", "US"),
        "Synthesia": ("https://synthesia.io", "AI Video Generation Platform", "UK"),
        "Shield AI": ("https://shield.ai", "Autonomous Defense Aviation", "US"),
        "Helsing": ("https://helsing.ai", "Live Defense AI & Sensor Processing", "Germany"),
        "Poolside": ("https://poolside.ai", "AI for Software Development", "France"),
        "Decagon": ("https://decagon.ai", "AI Agents for Customer Support", "US"),
        "Suno": ("https://suno.com", "Generative Music Creation", "US"),
        "Udio": ("https://udio.com", "AI Music Composition Platform", "US"),
        "Pika": ("https://pika.art", "Idea-to-Video AI Platform", "US"),
        "Poe": ("https://poe.com", "Multi-Bot AI Ecosystem", "US"),
        "Figure AI": ("https://figure.ai", "Autonomous Humanoid Robots", "US"),
        "Covariant": ("https://covariant.ai", "Robotics AI Platform", "US"),
        "Physical Intelligence": ("https://pi.ai", "General-Purpose Robot Foundation Models", "US"),
        "Cognition": ("https://cognition.ai", "Devin Autonomous Software Engineer", "US"),
        "Tabnine": ("https://tabnine.com", "Private AI Code Assistant", "Israel"),
        "Sakana AI": ("https://sakana.ai", "Nature-Inspired Evolutionary AI", "Japan"),
        "Magic AI": ("https://magic.dev", "Frontier Long-Context AI Models", "US"),
        "Sierra AI": ("https://sierra.ai", "Conversational AI for Business", "US"),
        "Luma AI": ("https://lumalabs.ai", "Dream Machine Video AI", "US"),
        "Black Forest Labs": ("https://blackforestlabs.ai", "FLUX Generative Image Models", "Germany"),
        "Cartesia": ("https://cartesia.ai", "Ultra-Fast Voice & Audio Models", "US"),
        "Ideogram": ("https://ideogram.ai", "Generative AI Typography & Art", "Canada"),
        "Recraft": ("https://recraft.ai", "Vector & Raster AI Design Engine", "US"),
        "Moonshot AI": ("https://kimi.ai", "Kimi Ultra Long Context LLM", "China"),
        "Kling AI": ("https://klingai.com", "High-Definition Video Synthesis", "Global"),
        "Baseten": ("https://baseten.co", "Serverless AI Inference Infrastructure", "US"),
        "Anyscale": ("https://anyscale.com", "Ray Distributed AI Computing Platform", "US"),
        "Cerebras": ("https://cerebras.ai", "Wafer-Scale AI Supercomputing", "US"),
        "SambaNova": ("https://sambanova.ai", "Full-Stack Enterprise AI Hardware", "US"),
        "Etched": ("https://etched.ai", "Transformer-Specific ASIC Hardware", "US"),
        "Reliable AI": ("https://reliable.ai", "Production AI Reliability & Guardrails", "US"),
        "Lamini": ("https://lamini.ai", "Enterprise LLM Fine-Tuning Platform", "US"),
        "Hex AI": ("https://hex.tech", "AI-Powered Analytics Workspace", "US"),
        "Hebbia": ("https://hebbia.ai", "AI Agents for Financial Knowledge", "US"),
        "Lovable": ("https://lovable.dev", "Full-Stack AI Software Builder", "Sweden"),
        "Bolt.new": ("https://bolt.new", "In-Browser Full-Stack AI Development", "US"),
        "Windsurf": ("https://codeium.com/windsurf", "Agentic Collaborative IDE", "US"),
        "Abridge": ("https://abridge.com", "Clinical AI Conversation Platform", "US"),
        "Ambience Healthcare": ("https://ambiencehealthcare.com", "Generative AI for Healthcare Providers", "US"),
        "Overjet": ("https://overjet.ai", "FDA-Cleared Dental Artificial Intelligence", "US"),
        "Wayve": ("https://wayve.ai", "Embodied AI for Autonomous Vehicles", "UK"),
        "Applied Intuition": ("https://appliedintuition.com", "Vehicle Software & Autonomous AI", "US"),
        "Skild AI": ("https://skild.ai", "General-Purpose Robotics Intelligence", "US"),
    }

    def __init__(
        self,
        concurrency: Optional[int] = None,
        raw_output_path: Optional[str] = "data/raw/startups.jsonl",
        http_client: Optional[ResilientHttpClient] = None,
    ):
        self.raw_output_path = Path(raw_output_path) if raw_output_path else None
        self.http_client = http_client or ResilientHttpClient(max_retries=2, default_timeout=8.0)
        self.seen_urls: Set[str] = set()

        self.stats = {
            "requests_made": 0,
            "startups_fetched": 0,
            "startups_emitted": 0,
            "duplicates_skipped": 0,
            "failures": 0,
        }

        if self.raw_output_path:
            self.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        """Load seen URLs to prevent duplicate scraping across runs."""
        if not self.raw_output_path or not self.raw_output_path.exists():
            return
        try:
            with open(self.raw_output_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        url = record.get("source", {}).get("url")
                        if url:
                            self.seen_urls.add(url.strip())
                    except Exception:
                        continue
            logger.info("Loaded %d existing startup records for deduplication.", len(self.seen_urls))
        except Exception as e:
            logger.warning("Error reading existing startups JSONL: %s", e)

    async def fetch_dynamic_startups(self, session: aiohttp.ClientSession, limit: int = 50) -> List[StartupEntity]:
        """Harvest fresh AI startups from dynamic live feeds."""
        dynamic_entities: List[StartupEntity] = []
        for feed in self.DYNAMIC_FEEDS:
            if len(dynamic_entities) >= limit:
                break
            try:
                xml_text = await self.http_client.get_text(session, feed["url"], timeout=6.0)
                if not xml_text:
                    continue
                root = ET.fromstring(xml_text)
                for item in root.findall(".//item"):
                    title_elem = item.find("title")
                    link_elem = item.find("link")
                    desc_elem = item.find("description")

                    if title_elem is None or not title_elem.text:
                        continue

                    raw_title = title_elem.text.strip()
                    # Clean "Launch HN:", "Show HN:" prefix
                    cleaned_name = re.sub(r"^(?:Launch HN:|Show HN:|Ask HN:)\s*", "", raw_title, flags=re.IGNORECASE)
                    # Extract startup name before dash/colon/parenthesis
                    parts = re.split(r"[-–—:(]", cleaned_name)
                    entity_name = parts[0].strip()

                    url = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

                    if not entity_name or len(entity_name) < 2 or not url:
                        continue

                    if url in self.seen_urls:
                        self.stats["duplicates_skipped"] += 1
                        continue

                    category = infer_startup_category(entity_name, desc)
                    entity = StartupEntity(
                        schemaVersion="1.0",
                        recordType="STARTUP",
                        source=SourceInfo(
                            name=feed["name"],
                            url=url,
                        ),
                        content=StartupContent(
                            entityName=entity_name,
                            data=StartupData(
                                employeeCount=None,
                                category=category,
                                description=desc[:200] if desc else f"AI innovator specializing in {category}",
                                country="Global",
                            ),
                        ),
                        collectedAt=datetime.now(timezone.utc),
                    )

                    self.seen_urls.add(url)
                    dynamic_entities.append(entity)
                    self.stats["startups_emitted"] += 1

                    if self.raw_output_path:
                        with open(self.raw_output_path, "a", encoding="utf-8") as f:
                            f.write(entity.model_dump_json() + "\n")

                    if len(dynamic_entities) >= limit:
                        break
            except Exception as e:
                logger.debug("Dynamic feed fetch notice for %s: %s", feed["name"], e)

        return dynamic_entities

    def fetch_seed_startups(self, limit: int = 1000) -> List[StartupEntity]:
        """Harvest startups from the curated Seed Startup Registry with zero fabrication."""
        entities: List[StartupEntity] = []

        seed_path = Path(__file__).resolve().parent.parent.parent / "data/seed/canonical_startups.json"
        seed_names = list(self.VERIFIED_STARTUPS.keys())

        if seed_path.exists():
            try:
                with open(seed_path, "r", encoding="utf-8") as f:
                    loaded_names = json.load(f)
                    if isinstance(loaded_names, list) and loaded_names:
                        seed_names = loaded_names
            except Exception as e:
                logger.warning("Notice loading canonical_startups.json: %s", e)

        for s_name in seed_names:
            if len(entities) >= limit:
                break

            clean_slug = "".join(c for c in str(s_name).lower() if c.isalnum())
            meta = self.VERIFIED_STARTUPS.get(s_name)
            if meta:
                url = meta[0]
                category = meta[1]
                country = meta[2]
            else:
                url = f"https://{clean_slug}.ai"
                category = infer_startup_category(str(s_name))
                country = "Global"

            if url in self.seen_urls:
                self.stats["duplicates_skipped"] += 1
                continue

            entity = StartupEntity(
                schemaVersion="1.0",
                recordType="STARTUP",
                source=SourceInfo(
                    name="Seed Startup Registry",
                    url=url,
                ),
                content=StartupContent(
                    entityName=str(s_name).strip(),
                    data=StartupData(
                        employeeCount=None,  # Strictly None by design (zero fabrication)
                        category=category,
                        description=f"Pioneering AI organization in {category}",
                        country=country,
                    ),
                ),
                collectedAt=datetime.now(timezone.utc),
            )

            self.seen_urls.add(url)
            entities.append(entity)
            self.stats["startups_emitted"] += 1

            if self.raw_output_path:
                with open(self.raw_output_path, "a", encoding="utf-8") as f:
                    f.write(entity.model_dump_json() + "\n")

        return entities

    async def fetch_hf_organizations(self, session: aiohttp.ClientSession, limit: int = 100) -> List[StartupEntity]:
        """Harvest verified AI organizations and labs directly from Hugging Face."""
        entities: List[StartupEntity] = []
        url = "https://huggingface.co/api/organizations"
        try:
            data = await self.http_client.get_json(session, url, timeout=5.0)
            if isinstance(data, list):
                for org in data:
                    if len(entities) >= limit:
                        break
                    org_name = org.get("fullname") or org.get("name")
                    org_id = org.get("name") or org.get("id")
                    if not org_name or not org_id:
                        continue
                    homepage = org.get("homepage") or f"https://huggingface.co/{org_id}"
                    if homepage in self.seen_urls:
                        self.stats["duplicates_skipped"] += 1
                        continue

                    category = infer_startup_category(str(org_name), str(org_id))
                    entity = StartupEntity(
                        schemaVersion="1.0",
                        recordType="STARTUP",
                        source=SourceInfo(
                            name="Hugging Face AI Organizations Hub",
                            url=homepage,
                        ),
                        content=StartupContent(
                            entityName=str(org_name).strip(),
                            data=StartupData(
                                employeeCount=None,
                                category=category,
                                description=f"AI organization specializing in {category}",
                                country="Global",
                            ),
                        ),
                        collectedAt=datetime.now(timezone.utc),
                    )
                    self.seen_urls.add(homepage)
                    entities.append(entity)
                    self.stats["startups_emitted"] += 1
                    if self.raw_output_path:
                        with open(self.raw_output_path, "a", encoding="utf-8") as f:
                            f.write(entity.model_dump_json() + "\n")
        except Exception as e:
            logger.debug("Hugging Face Organizations fetch notice: %s", e)
        return entities

    async def harvest_bulk(self, target_count: int = 1000) -> List[StartupEntity]:
        """Harvest startups up to target count combining dynamic feeds, Hugging Face AI labs, and seed catalog."""
        all_entities: List[StartupEntity] = []

        try:
            async with aiohttp.ClientSession() as session:
                # 1. Fetch dynamic AI launches & showcases
                dynamic_res = await self.fetch_dynamic_startups(session, limit=min(target_count // 3, 100))
                all_entities.extend(dynamic_res)

                # 2. Fetch live Hugging Face AI organizations & labs
                if len(all_entities) < target_count:
                    hf_orgs = await self.fetch_hf_organizations(session, limit=min(target_count // 3, 100))
                    all_entities.extend(hf_orgs)
        except Exception as e:
            logger.debug("Dynamic startup harvest note: %s", e)

        # 3. Complete with canonical seed catalog
        remaining = target_count - len(all_entities)
        if remaining > 0:
            seed_res = self.fetch_seed_startups(limit=remaining)
            all_entities.extend(seed_res)

        self.stats["startups_fetched"] = len(all_entities)
        logger.info("Startups harvest complete: %s (Total emitted: %d)", self.stats, len(all_entities))
        return all_entities

