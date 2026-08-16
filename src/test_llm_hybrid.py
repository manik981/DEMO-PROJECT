"""Controlled Test Command for Hybrid LLM Structuring & Telemetry Verification.

Processes 10-20 representative records across verticals in both 'hybrid' and 'force' modes to demonstrate:
1. Gemini extraction success
2. Fallback escalation (Groq / DeepSeek)
3. Token usage & latency tracking
4. Schema validation & 1-shot repair
5. llm_logs persistence to Supabase PostgreSQL table
6. Full 7-metric structuring telemetry report

Usage:
    python src/test_llm_hybrid.py --mode force --limit 15
    python src/test_llm_hybrid.py --mode hybrid --limit 15
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

from src.db.supabase_client import get_supabase_client
from src.llm.extractor import LLMExtractor
from src.schemas import (
    JobEntity,
    NewsEntity,
    ProductEntity,
    ResearchPaperEntity,
    StartupEntity,
)
from src.structure import check_record_completeness, print_structuring_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_llm_hybrid")

# 15 Representative sample records across all 5 verticals + edge cases
REPRESENTATIVE_SAMPLES = [
    # 1. Clean Startup (Deterministic candidate)
    (
        "startups",
        StartupEntity,
        "STARTUP",
        {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {"name": "Y Combinator", "url": "https://www.ycombinator.com/companies/stripe"},
            "content": {"entityName": "Stripe", "data": {"employeeCount": 8000}},
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    # 2. Raw Startup Description (Unstructured LLM candidate)
    (
        "startups",
        StartupEntity,
        "STARTUP",
        {
            "source_name": "TechCrunch",
            "source_url": "https://techcrunch.com/2026/08/14/mistral-ai-expansion",
            "text": "Mistral AI, the Paris-based frontier LLM startup with over 250 engineers, announced their new flagship model series today.",
        },
    ),
    # 3. Clean Product (Deterministic candidate)
    (
        "products",
        ProductEntity,
        "PRODUCT",
        {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "source": {"name": "ProductHunt", "url": "https://www.producthunt.com/posts/claude-3-5-sonnet"},
            "content": {
                "title": "Claude 3.5 Sonnet",
                "startupName": "Anthropic",
                "pricingModel": "FREEMIUM",
                "description": "Next-generation intelligent frontier AI model.",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    # 4. Unstructured Product blurb (LLM candidate)
    (
        "products",
        ProductEntity,
        "PRODUCT",
        {
            "source": {"name": "Twitter / X", "url": "https://x.com/cursor_ai/status/123456789"},
            "raw_text": "Cursor is an AI-powered code editor built for pair programming. Free for hobbyists, $20/mo Pro plan.",
        },
    ),
    # 5. Clean arXiv Paper (Deterministic candidate)
    (
        "papers",
        ResearchPaperEntity,
        "RESEARCH_PAPER",
        {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "content": {
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
                "paper_url": "https://arxiv.org/abs/1706.03762",
                "github_url": "https://github.com/tensorflow/tensor2tensor",
                "github_stars": 15000,
                "published_date": "2017-06-12T00:00:00Z",
            },
        },
    ),
    # 6. Unstructured arXiv abstract with github repo (LLM candidate)
    (
        "papers",
        ResearchPaperEntity,
        "RESEARCH_PAPER",
        {
            "source": {"name": "arXiv CS.AI", "url": "https://arxiv.org/abs/2401.00001"},
            "content": {
                "title": "DeepSeek-V3 Technical Report",
                "paper_url": "https://arxiv.org/abs/2401.00001",
                "summary": "We introduce DeepSeek-V3, a strong Mixture-of-Experts language model. Code and weights at https://github.com/deepseek-ai/DeepSeek-V3. Authors: DeepSeek-AI team.",
                "published_date": "2024-12-27T00:00:00Z",
            },
        },
    ),
    # 7. Clean Job (Deterministic candidate)
    (
        "jobs",
        JobEntity,
        "JOB",
        {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {"name": "OpenAI Careers", "url": "https://openai.com/careers/research-engineer"},
            "content": {
                "company": "OpenAI",
                "title": "Member of Technical Staff - Pretraining",
                "date": datetime.now(timezone.utc).isoformat(),
                "is_remote": True,
                "role_family": "Research",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    # 8. Unstructured Job Posting (LLM candidate)
    (
        "jobs",
        JobEntity,
        "JOB",
        {
            "source": {"name": "LinkedIn", "url": "https://linkedin.com/jobs/view/99887766"},
            "content": {
                "snippet": "Hiring a Senior Full Stack Engineer at Cohere. Remote friendly role, building our enterprise platform.",
                "posted": "2026-08-14",
            },
        },
    ),
    # 9. Clean News article (Deterministic candidate)
    (
        "news",
        NewsEntity,
        "NEWS",
        {
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "source": {"name": "MIT Technology Review", "url": "https://technologyreview.com/2026/08/15/ai-reasoning"},
            "content": {
                "title": "How Test-Time Compute is Reshaping LLM Benchmarks",
                "published_date": datetime.now(timezone.utc).isoformat(),
                "summary": "An in-depth look at reinforcement learning and search during inference.",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    # 10. Unstructured News RSS Snippet (LLM candidate)
    (
        "news",
        NewsEntity,
        "NEWS",
        {
            "source": {"name": "VentureBeat", "url": "https://venturebeat.com/ai/scale-ai-defense-contract"},
            "content": {
                "raw_text": "Scale AI secures $100M government data labeling initiative for defense robotics applications.",
                "published": "2026-08-15T08:30:00Z",
            },
        },
    ),
    # 11. Edge case: Malformed pricing field (Requires LLM one-shot repair)
    (
        "products",
        ProductEntity,
        "PRODUCT",
        {
            "source": {"name": "HackerNews", "url": "https://news.ycombinator.com/item?id=334455"},
            "raw_content": "We launched vLLM Cloud! Pricing: pay-as-you-go GPU instances starting at $0.50/hour (PAID).",
        },
    ),
    # 12. Startup seed record (Deterministic)
    (
        "startups",
        StartupEntity,
        "STARTUP",
        {
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {"name": "Y Combinator", "url": "https://www.ycombinator.com/companies/anyscale"},
            "content": {"entityName": "Anyscale", "data": {"employeeCount": 180}},
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    # 13. High-star Research Paper (Deterministic)
    (
        "papers",
        ResearchPaperEntity,
        "RESEARCH_PAPER",
        {
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "content": {
                "title": "LLaMA: Open and Efficient Foundation Language Models",
                "authors": ["Hugo Touvron", "Thibaut Lavril", "Gautier Izacard"],
                "paper_url": "https://arxiv.org/abs/2302.13971",
                "github_url": "https://github.com/facebookresearch/llama",
                "github_stars": 58000,
                "published_date": "2023-02-27T00:00:00Z",
            },
        },
    ),
    # 14. ML Engineering Job (Deterministic)
    (
        "jobs",
        JobEntity,
        "JOB",
        {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {"name": "Y Combinator Jobs", "url": "https://ycombinator.com/jobs/scale-ml-eng"},
            "content": {
                "company": "Scale AI",
                "title": "Staff ML Infrastructure Engineer",
                "date": datetime.now(timezone.utc).isoformat(),
                "is_remote": False,
                "role_family": "Engineering",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    # 15. Global AI Announcement (LLM candidate)
    (
        "news",
        NewsEntity,
        "NEWS",
        {
            "source": {"name": "Reuters", "url": "https://reuters.com/technology/ai-compute-datacenter-expansion"},
            "raw_text": "Global hyperscalers announce $50B infrastructure expansion for next-generation AI model clusters.",
        },
    ),
]


async def run_controlled_test(mode: str = "force", limit: int = 15):
    """Execute controlled representative test and verify telemetry in Supabase."""
    run_id = f"test_run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    print("\n" + "=" * 90)
    print(f"🧪 CONTROLLED HYBRID LLM EVALUATION TEST [MODE: {mode.upper()}]")
    print(f"   Run ID: {run_id} | Sample Limit: {limit}")
    print("=" * 90)

    extractor = LLMExtractor(
        quarantine_dir="data/quarantine",
        structured_dir="data/structured",
    )

    stats = {
        "read": 0,
        "structured": 0,
        "deterministic_bypasses": 0,
        "llm_calls": 0,
        "llm_cache_hits": 0,
        "fallback_calls": 0,
        "429_count": 0,
        "repair_count": 0,
        "quarantine_count": 0,
    }

    vertical_stats = {
        "papers": {"read": 0, "structured": 0, "deterministic_bypasses": 0, "llm_calls": 0, "llm_cache_hits": 0, "repair_count": 0, "quarantine_count": 0},
        "startups": {"read": 0, "structured": 0, "deterministic_bypasses": 0, "llm_calls": 0, "llm_cache_hits": 0, "repair_count": 0, "quarantine_count": 0},
        "products": {"read": 0, "structured": 0, "deterministic_bypasses": 0, "llm_calls": 0, "llm_cache_hits": 0, "repair_count": 0, "quarantine_count": 0},
        "news": {"read": 0, "structured": 0, "deterministic_bypasses": 0, "llm_calls": 0, "llm_cache_hits": 0, "repair_count": 0, "quarantine_count": 0},
        "jobs": {"read": 0, "structured": 0, "deterministic_bypasses": 0, "llm_calls": 0, "llm_cache_hits": 0, "repair_count": 0, "quarantine_count": 0},
    }

    test_samples = REPRESENTATIVE_SAMPLES[:limit]

    print(f"\n[1/3] ⚙️ Processing {len(test_samples)} representative records through Hybrid Pipeline...")
    for idx, (vert, schema_cls, rec_type, raw_record) in enumerate(test_samples, 1):
        v_stat = vertical_stats[vert]
        v_stat["read"] += 1
        stats["read"] += 1

        source_url = raw_record.get("source", {}).get("url") or raw_record.get("content", {}).get("paper_url", "") or raw_record.get("source_url", "")
        raw_text = json.dumps(raw_record, indent=2)

        entity = None
        bypass_reason = "FORCED_LLM" if mode == "force" else "INCOMPLETE_RAW"

        # 1. Deterministic Bypass in HYBRID mode
        if mode == "hybrid":
            is_complete, valid_entity = check_record_completeness(raw_record, vert, schema_cls)
            if is_complete and valid_entity:
                entity = extractor.post_validate_and_ground(valid_entity)
                stats["deterministic_bypasses"] += 1
                v_stat["deterministic_bypasses"] += 1
                bypass_reason = "DETERMINISTIC_PASS"

        # 2. LLM Structuring Pass
        if entity is None:
            init_calls = extractor.stats.get("llm_calls", 0)
            init_cache = extractor.stats.get("llm_cache_hits", 0)
            init_repair = extractor.stats.get("repair_count", 0)
            init_quar = extractor.stats.get("quarantine_count", 0)

            entity = extractor.extract_entity(
                raw_text=raw_text,
                schema_cls=schema_cls,
                source_url=source_url,
                record_type=rec_type,
                allow_cache=False,  # Force fresh evaluation
                run_id=run_id,
            )

            if extractor.stats.get("llm_calls", 0) > init_calls:
                v_stat["llm_calls"] += 1
                stats["llm_calls"] += 1
            if extractor.stats.get("llm_cache_hits", 0) > init_cache:
                v_stat["llm_cache_hits"] += 1
                stats["llm_cache_hits"] += 1
            if extractor.stats.get("repair_count", 0) > init_repair:
                v_stat["repair_count"] += 1
                stats["repair_count"] += 1
            if extractor.stats.get("quarantine_count", 0) > init_quar:
                v_stat["quarantine_count"] += 1
                stats["quarantine_count"] += 1

        if entity:
            v_stat["structured"] += 1
            stats["structured"] += 1
            print(f"  #{idx:02d} [{vert.upper():<8}] ✅ SUCCESS -> {bypass_reason}")
        else:
            v_stat["quarantine_count"] += 1
            stats["quarantine_count"] += 1
            print(f"  #{idx:02d} [{vert.upper():<8}] ⚠️ QUARANTINED")

    # Pull router-level stats
    if extractor.router:
        stats["fallback_calls"] = extractor.router.stats.get("fallback_calls", 0)
        stats["429_count"] = extractor.router.stats.get("429_count", 0)

    # 2. Print metrics table
    print_structuring_report(vertical_stats, mode=mode)

    # 3. Supabase llm_logs Verification
    print("[2/3] 📡 Verifying llm_logs Audit Rows in Supabase...")
    db_client = get_supabase_client()
    if db_client.is_configured:
        import httpx
        try:
            # Query recent logs for this run_id
            headers = db_client._get_headers()
            url = f"{db_client.rest_endpoint}/llm_logs?run_id=eq.{run_id}&order=created_at.desc"
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=headers, timeout=5.0)
                if res.status_code == 200:
                    rows = res.json()
                    print(f"  ✅ Fetched {len(rows)} verified llm_logs entries from Supabase:")
                    print("-" * 90)
                    print(f"{'MODEL':<24} | {'TIER':<18} | {'STATUS':<16} | {'TOKENS (P/C)':<14} | {'LATENCY'}")
                    print("-" * 90)
                    for r in rows[:10]:
                        tokens = f"{r.get('prompt_tokens', 0)} / {r.get('completion_tokens', 0)}"
                        lat = f"{r.get('latency_ms', 0)}ms"
                        print(f"{r.get('model_name', 'unknown')[:24]:<24} | {r.get('tier', 'primary')[:18]:<18} | "
                              f"{r.get('status', 'success')[:16]:<16} | {tokens:<14} | {lat}")
                    print("-" * 90)
                else:
                    print(f"  ⚠️ Supabase query status: {res.status_code}")
        except Exception as e:
            print(f"  ⚠️ Supabase llm_logs fetch warning: {e}")
    else:
        print("  ⚠️ Supabase client not configured.")

    print("\n[3/3] 🏆 Controlled Hybrid Test Finished Successfully!\n")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Controlled Hybrid LLM Evaluation")
    parser.add_argument("--mode", choices=["hybrid", "force"], default="force",
                        help="'hybrid' tests deterministic bypass; 'force' evaluates full LiteLLM router pipeline")
    parser.add_argument("--limit", type=int, default=15, help="Number of test records to process (10-20)")
    args = parser.parse_args()

    asyncio.run(run_controlled_test(mode=args.mode, limit=args.limit))


if __name__ == "__main__":
    main()
