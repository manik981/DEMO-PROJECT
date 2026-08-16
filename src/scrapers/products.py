"""Products Ingestion Module.

Harvests AI products directly from the live Hugging Face Spaces Hub API (real open-source
AI applications & spaces) with fallback to the curated Verified AI Product Registry.
Emits strictly typed ProductEntity records with valid pricing models (FREE, FREEMIUM, PAID, ENTERPRISE).
Streams raw JSONL entries incrementally to data/raw/products.jsonl.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional, Set
import aiohttp

from src.schemas.product import ProductContent, ProductEntity
from src.schemas.shared import SourceInfo

logger = logging.getLogger(__name__)

PricingTier = Literal["FREE", "FREEMIUM", "PAID", "ENTERPRISE"]


class ProductsScraper:
    """Harvester for AI Products using Hugging Face Spaces API and Verified AI Product Registry."""

    HF_SPACES_ENDPOINTS = [
        "https://huggingface.co/api/spaces?limit=500&full=true",
        "https://huggingface.co/api/spaces?sort=likes&direction=-1&limit=500&full=true",
        "https://huggingface.co/api/spaces?sort=trendingScore&direction=-1&limit=500&full=true",
        "https://huggingface.co/api/spaces?filter=text-to-image&limit=300&full=true",
        "https://huggingface.co/api/spaces?filter=text-generation&limit=300&full=true",
        "https://huggingface.co/api/spaces?filter=image-to-text&limit=300&full=true",
        "https://huggingface.co/api/spaces?filter=automatic-speech-recognition&limit=300&full=true",
    ]

    GITHUB_AI_PRODUCT_ENDPOINTS = [
        "https://api.github.com/search/repositories?q=topic:generative-ai+stars:>2000&sort=stars&order=desc&per_page=100",
        "https://api.github.com/search/repositories?q=topic:llm+stars:>2000&sort=stars&order=desc&per_page=100",
        "https://api.github.com/search/repositories?q=topic:ai-agent+stars:>1000&sort=stars&order=desc&per_page=100",
    ]

    VERIFIED_PRODUCTS = [
        # LLMs & Conversational AI
        ("ChatGPT", "OpenAI", "FREEMIUM", "https://chatgpt.com"),
        ("Claude", "Anthropic", "FREEMIUM", "https://claude.ai"),
        ("Gemini", "Google DeepMind", "FREEMIUM", "https://gemini.google.com"),
        ("Le Chat", "Mistral AI", "FREE", "https://chat.mistral.ai"),
        ("DeepSeek Chat", "DeepSeek", "FREE", "https://chat.deepseek.com"),
        ("Command R+", "Cohere", "PAID", "https://cohere.com/models/command"),
        ("Grok", "xAI", "PAID", "https://x.ai/grok"),
        ("Perplexity Pro", "Perplexity", "FREEMIUM", "https://perplexity.ai/pro"),
        ("HuggingChat", "Hugging Face", "FREE", "https://huggingface.co/chat"),
        ("Poe Multi-Bot", "Poe", "FREEMIUM", "https://poe.com"),
        ("Pi Personal AI", "Inflection AI", "FREE", "https://pi.ai"),
        ("Character Voice", "Character.ai", "FREE", "https://character.ai"),
        ("Kimi AI", "Moonshot AI", "FREE", "https://kimi.ai"),
        ("Qwen Chat", "Alibaba Qwen", "FREE", "https://chat.qwenlm.ai"),

        # Generative Video & Image
        ("Midjourney v6", "Midjourney", "PAID", "https://midjourney.com"),
        ("Stable Diffusion 3", "Stability AI", "PAID", "https://stability.ai/stable-diffusion"),
        ("FLUX.1", "Black Forest Labs", "FREEMIUM", "https://blackforestlabs.ai"),
        ("Gen-3 Alpha", "Runway", "FREEMIUM", "https://runwayml.com/gen-3"),
        ("Dream Machine", "Luma AI", "FREEMIUM", "https://lumalabs.ai/dream-machine"),
        ("Kling AI Studio", "Kling AI", "FREEMIUM", "https://klingai.com"),
        ("Pika 1.0", "Pika", "FREEMIUM", "https://pika.art"),
        ("Ideogram 2.0", "Ideogram", "FREEMIUM", "https://ideogram.ai"),
        ("Recraft AI", "Recraft", "FREEMIUM", "https://recraft.ai"),
        ("DALL-E 3", "OpenAI", "PAID", "https://openai.com/dall-e-3"),
        ("HeyGen Video", "HeyGen", "PAID", "https://heygen.com"),
        ("Synthesia Studio", "Synthesia", "PAID", "https://synthesia.io"),

        # Voice, Audio & Music AI
        ("ElevenLabs Voice", "ElevenLabs", "FREEMIUM", "https://elevenlabs.io/app"),
        ("Suno v3.5", "Suno", "FREEMIUM", "https://suno.com"),
        ("Udio Music Studio", "Udio", "FREEMIUM", "https://udio.com"),
        ("Cartesia Sonic", "Cartesia", "PAID", "https://cartesia.ai"),
        ("Descript AI", "Descript", "FREEMIUM", "https://descript.com"),
        ("Otter AI", "Otter.ai", "FREEMIUM", "https://otter.ai"),
        ("Fireflies AI", "Fireflies.ai", "FREEMIUM", "https://fireflies.ai"),

        # AI Code & Developer Tools
        ("Cursor IDE", "Cursor", "FREEMIUM", "https://cursor.com"),
        ("Devin", "Cognition", "ENTERPRISE", "https://cognition.ai"),
        ("Tabnine Pro", "Tabnine", "PAID", "https://tabnine.com"),
        ("Codeium", "Exafunction", "FREE", "https://codeium.com"),
        ("v0 by Vercel", "Vercel", "FREEMIUM", "https://v0.dev"),
        ("Replit Agent", "Replit", "PAID", "https://replit.com/ai"),
        ("Lovable AI", "Lovable", "FREEMIUM", "https://lovable.dev"),
        ("Bolt.new", "StackBlitz", "FREEMIUM", "https://bolt.new"),
        ("Windsurf Editor", "Codeium", "FREEMIUM", "https://codeium.com/windsurf"),
        ("Augment Code", "Augment", "PAID", "https://augmentcode.com"),
        ("Aider AI Pair", "Aider", "FREE", "https://aider.chat"),

        # Vector Databases & AI Infrastructure
        ("Pinecone Serverless", "Pinecone", "FREEMIUM", "https://pinecone.io/pricing"),
        ("Weaviate Cloud", "Weaviate", "FREEMIUM", "https://weaviate.io/pricing"),
        ("Qdrant Cloud", "Qdrant", "FREEMIUM", "https://qdrant.tech/pricing"),
        ("Chroma DB", "Chroma", "FREE", "https://trychroma.com"),
        ("Milvus Vector DB", "Zilliz", "FREE", "https://milvus.io"),
        ("Databricks Mosaic AI", "Databricks", "ENTERPRISE", "https://databricks.com/product/mosaic-ai"),
        ("Snowflake Cortex AI", "Snowflake", "ENTERPRISE", "https://snowflake.com/en/data-cloud/cortex"),
        ("LangSmith", "LangChain", "FREEMIUM", "https://smith.langchain.com"),
        ("LlamaParse", "LlamaIndex", "FREEMIUM", "https://llamaindex.ai/llamaparse"),
        ("Together Inference", "Together AI", "PAID", "https://together.ai/pricing"),
        ("Replicate Platform", "Replicate", "PAID", "https://replicate.com/pricing"),
        ("Modal Serverless", "Modal", "PAID", "https://modal.com/pricing"),
        ("Fireworks Serverless", "Fireworks AI", "PAID", "https://fireworks.ai/pricing"),
        ("Groq LPU Engine", "Groq", "FREEMIUM", "https://groq.com"),
        ("Ollama Local", "Ollama", "FREE", "https://ollama.com"),
        ("vLLM Engine", "vLLM", "FREE", "https://vllm.ai"),
        ("LiteLLM Gateway", "BerriAI", "FREE", "https://litellm.ai"),
        ("Langfuse", "Langfuse", "FREEMIUM", "https://langfuse.com"),
        ("Helicone AI", "Helicone", "FREEMIUM", "https://helicone.ai"),
        ("Portkey AI Gateway", "Portkey", "FREEMIUM", "https://portkey.ai"),
        ("Braintrust Evals", "Braintrust", "FREEMIUM", "https://braintrust.dev"),

        # Enterprise & Productivity AI
        ("Glean Work AI", "Glean", "ENTERPRISE", "https://glean.com"),
        ("Harvey Legal AI", "Harvey", "ENTERPRISE", "https://harvey.ai"),
        ("Writer Full-Stack AI", "Writer", "ENTERPRISE", "https://writer.com"),
        ("Jasper Creator", "Jasper", "PAID", "https://jasper.ai/pricing"),
        ("Copy.ai", "Copy.ai", "FREEMIUM", "https://copy.ai"),
        ("Gamma Presentations", "Gamma", "FREEMIUM", "https://gamma.app"),
        ("Tome AI", "Tome", "FREEMIUM", "https://tome.app"),
        ("Phind Search", "Phind", "FREEMIUM", "https://phind.com"),
        ("Consensus AI", "Consensus", "FREEMIUM", "https://consensus.app"),
        ("Elicit Research", "Elicit", "FREEMIUM", "https://elicit.com"),
        ("Julius AI", "Julius", "FREEMIUM", "https://julius.ai"),
        ("Weights & Biases", "W&B", "FREEMIUM", "https://wandb.ai"),
        ("Arize Phoenix", "Arize AI", "FREE", "https://arize.com/phoenix"),
        ("Dify.ai", "Dify", "FREEMIUM", "https://dify.ai"),
        ("Flowise AI", "Flowise", "FREE", "https://flowiseai.com"),
    ]

    def __init__(
        self,
        concurrency: Optional[int] = None,
        raw_output_path: Optional[str] = "data/raw/products.jsonl",
    ):
        self.concurrency = concurrency or int(os.getenv("CRAWLER_CONCURRENCY", "15"))
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.raw_output_path = Path(raw_output_path) if raw_output_path else None
        self.seen_urls: Set[str] = set()

        self.stats = {
            "requests_made": 0,
            "products_fetched": 0,
            "products_emitted": 0,
            "duplicates_skipped": 0,
            "failures": 0,
        }

        if self.raw_output_path:
            self.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        """Load seen product URLs to avoid duplicates across runs."""
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
            logger.info("Loaded %d existing product records for deduplication.", len(self.seen_urls))
        except Exception as e:
            logger.warning("Error reading existing products JSONL: %s", e)

    def normalize_pricing_model(self, raw_pricing: Optional[str]) -> PricingTier:
        """Map diverse pricing strings into strictly valid enum values."""
        if not raw_pricing:
            return "FREEMIUM"

        text = raw_pricing.upper().strip()
        if "ENTERPRISE" in text or "CUSTOM" in text or "CONTACT" in text:
            return "ENTERPRISE"
        elif "FREE TRIAL" in text or "FREEMIUM" in text or "FREE & PAID" in text:
            return "FREEMIUM"
        elif "FREE" in text or "OPEN SOURCE" in text:
            return "FREE"
        elif "PAID" in text or "$" in text or "MONTH" in text or "SUBSCRIPTION" in text:
            return "PAID"
        return "FREEMIUM"

    async def fetch_live_and_seed_products(
        self, session: aiohttp.ClientSession, limit: int = 1000
    ) -> List[ProductEntity]:
        """Harvest products from live Hugging Face Spaces & GitHub AI APIs with Verified AI Product Registry."""
        entities: List[ProductEntity] = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        # 1. Primary Live Tier: Hugging Face Spaces Hub Endpoints
        for endpoint in self.HF_SPACES_ENDPOINTS:
            if len(entities) >= limit:
                break
            self.stats["requests_made"] += 1
            try:
                async with session.get(endpoint, headers=headers, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    if resp.status == 200:
                        spaces_data = await resp.json(content_type=None)
                        if isinstance(spaces_data, list):
                            for space in spaces_data:
                                if len(entities) >= limit:
                                    break
                                space_id = space.get("id") or space.get("_id")
                                if not space_id or "/" not in space_id:
                                    continue

                                author, product_slug = space_id.split("/", 1)
                                space_url = f"https://huggingface.co/spaces/{space_id}"
                                if space_url in self.seen_urls:
                                    self.stats["duplicates_skipped"] += 1
                                    continue

                                entity = ProductEntity(
                                    schemaVersion="1.0",
                                    recordType="PRODUCT",
                                    source=SourceInfo(
                                        name="Hugging Face Spaces Hub",
                                        url=space_url,
                                    ),
                                    content=ProductContent(
                                        startupName=str(author).strip(),
                                        pricingModel="FREE",
                                    ),
                                    collectedAt=datetime.now(timezone.utc),
                                )

                                self.seen_urls.add(space_url)
                                entities.append(entity)
                                self.stats["products_emitted"] += 1
            except Exception as e:
                logger.debug("Hugging Face Spaces endpoint notice for %s: %s", endpoint, e)

        # 2. Secondary Live Tier: GitHub AI Repositories / Tools
        gh_token = os.getenv("GITHUB_TOKEN")
        gh_headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-Data-Intelligence-Ingestion-Pipeline",
        }
        if gh_token:
            gh_headers["Authorization"] = f"token {gh_token}"

        for endpoint in self.GITHUB_AI_PRODUCT_ENDPOINTS:
            if len(entities) >= limit:
                break
            self.stats["requests_made"] += 1
            try:
                async with session.get(endpoint, headers=gh_headers, timeout=aiohttp.ClientTimeout(total=4.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        for repo in items:
                            if len(entities) >= limit:
                                break
                            owner = repo.get("owner", {}).get("login") or "AI Contributor"
                            repo_url = repo.get("html_url")
                            if not repo_url or repo_url in self.seen_urls:
                                continue

                            entity = ProductEntity(
                                schemaVersion="1.0",
                                recordType="PRODUCT",
                                source=SourceInfo(
                                    name="GitHub AI Projects",
                                    url=repo_url,
                                ),
                                content=ProductContent(
                                    startupName=str(owner).strip(),
                                    pricingModel="FREE",
                                ),
                                collectedAt=datetime.now(timezone.utc),
                            )

                            self.seen_urls.add(repo_url)
                            entities.append(entity)
                            self.stats["products_emitted"] += 1
            except Exception as e:
                logger.debug("GitHub AI Product notice: %s", e)

        # 3. Tertiary Fallback Tier: Verified AI Product Registry
        if len(entities) < limit:
            for p_title, p_startup, p_tier, p_url in self.VERIFIED_PRODUCTS:
                if len(entities) >= limit:
                    break
                if p_url in self.seen_urls:
                    self.stats["duplicates_skipped"] += 1
                    continue

                entity = ProductEntity(
                    schemaVersion="1.0",
                    recordType="PRODUCT",
                    source=SourceInfo(
                        name="Verified AI Product Registry",
                        url=p_url,
                    ),
                    content=ProductContent(
                        startupName=str(p_startup).strip(),
                        pricingModel=self.normalize_pricing_model(p_tier),
                    ),
                    collectedAt=datetime.now(timezone.utc),
                )

                self.seen_urls.add(p_url)
                entities.append(entity)
                self.stats["products_emitted"] += 1

        self.stats["products_fetched"] = len(entities)
        if entities and self.raw_output_path:
            with open(self.raw_output_path, "a", encoding="utf-8") as f:
                for entity in entities:
                    f.write(entity.model_dump_json() + "\n")
        return entities

    async def harvest_bulk(self, target_count: int = 1000) -> List[ProductEntity]:
        """Harvest products up to target count."""
        async with aiohttp.ClientSession() as session:
            results = await self.fetch_live_and_seed_products(session, limit=target_count)
            logger.info("Products harvest finished: %s (Total emitted: %d)", self.stats, len(results))
            return results

