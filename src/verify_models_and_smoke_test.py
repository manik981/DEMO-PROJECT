"""Single Command Model Verification & 20-Record Hybrid Smoke Test.

Step 1: Verify model IDs (Gemini, Groq, DeepSeek) with 1 request each.
Step 2: Run 20 real records through the Hybrid pipeline and measure:
        - deterministic bypasses
        - LLM calls
        - 429 rate limits
        - fallbacks
        - prompt & completion tokens
        - runtime & observed LLM utilization rate

Usage:
    python src/verify_models_and_smoke_test.py
"""

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("smoke_test")

try:
    import litellm
    from litellm import completion
except ImportError:
    litellm = None
    completion = None

from src.db.supabase_client import get_supabase_client
from src.llm.extractor import LLMExtractor
from src.schemas import (
    JobEntity,
    NewsEntity,
    ProductEntity,
    ResearchPaperEntity,
    StartupEntity,
)
from src.structure import check_record_completeness


# =============================================================================
# STEP 1: VERIFY MODEL IDs (1 Probe Request Each)
# =============================================================================
__test__ = False  # Prevent pytest from auto-collecting this operational smoke script

from src.llm.probe import execute_single_probe


def verify_model(provider_name: str, model_id: str, api_key: str) -> dict:
    """Send 1 minimal request to test API key and model connectivity."""
    print(f"  🔍 Probing {provider_name} [{model_id}]...", end=" ", flush=True)
    if not api_key:
        print("❌ SKIPPED (API Key missing in .env)")
        return {"status": "missing_key", "latency_ms": 0, "tokens": 0, "model": model_id, "error": "No API key"}

    start = time.time()
    prov_key = (
        "gemini" if "gemini" in provider_name.lower()
        else "cerebras" if "cerebras" in provider_name.lower()
        else "openrouter" if "openrouter" in provider_name.lower()
        else "groq"
    )
    ok, msg = execute_single_probe(prov_key, model_id, api_key)
    latency = int((time.time() - start) * 1000)

    if ok:
        print(f"✅ WORKING ({latency}ms, result: '{msg}')")
        return {
            "status": "success",
            "latency_ms": latency,
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "model": model_id,
            "error": None,
        }
    else:
        print(f"❌ FAILED ({latency}ms) -> {msg}")
        return {
            "status": "error",
            "latency_ms": latency,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model": model_id,
            "error": msg,
        }


def step_1_verify_all_models():
    """Verify Groq, OpenRouter, Gemini, and Cerebras model IDs."""
    print("\n" + "=" * 90)
    print("STEP 1: VERIFYING LLM PROVIDER MODEL IDs (1 Probe Request Each)")
    print("-" * 90)

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    cerebras_key = (
        os.getenv("CEREBRAS_API_KEY")
        or os.getenv("CEREBAS_API_KEY", "")
    ).strip()

    groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    cerebras_model = (
        os.getenv("CEREBRAS_MODEL")
        or os.getenv("CEREBAS_MODEL", "zai-glm-4.7")
    )

    results = []

    # 1. Groq Probe
    gr_res = verify_model("Groq LLaMA", groq_model, groq_key)
    results.append({
        "provider": "Groq",
        "key_status": "configured" if groq_key else "missing",
        "model_id": groq_model,
        "available": "yes" if gr_res["status"] == "success" else "no",
        "result": "OK" if gr_res["status"] == "success" else (gr_res.get("error") or "ERROR")[:20],
    })

    # 2. OpenRouter Probe
    or_res = verify_model("OpenRouter", openrouter_model, openrouter_key)
    results.append({
        "provider": "OpenRouter",
        "key_status": "configured" if openrouter_key else "missing",
        "model_id": openrouter_model,
        "available": "yes" if or_res["status"] == "success" else "no",
        "result": "OK" if or_res["status"] == "success" else (or_res.get("error") or "ERROR")[:20],
    })

    # 3. Gemini Probe
    if gemini_key:
        g_res = verify_model("Google Gemini", gemini_model, gemini_key)
        results.append({
            "provider": "Gemini",
            "key_status": "configured" if gemini_key else "missing",
            "model_id": gemini_model,
            "available": "yes" if g_res["status"] == "success" else "check_quota",
            "result": "OK" if g_res["status"] == "success" else (g_res.get("error") or "ERROR")[:20],
        })

    # 4. Cerebras Probe
    if cerebras_key:
        c_res = verify_model("Cerebras", cerebras_model, cerebras_key)
        results.append({
            "provider": "Cerebras",
            "key_status": "configured" if cerebras_key else "missing",
            "model_id": cerebras_model,
            "available": "yes" if c_res["status"] == "success" else "no",
            "result": "OK" if c_res["status"] == "success" else (c_res.get("error") or "ERROR")[:20],
        })

    print("-" * 90)
    print(f"{'Provider':<12} | {'API Key':<12} | {'Model ID':<26} | {'Available':<10} | {'Test Result'}")
    print("-" * 90)
    for r in results:
        print(f"{r['provider']:<12} | {r['key_status']:<12} | {r['model_id']:<26} | {r['available']:<10} | {r['result']}")
    print("=" * 90 + "\n")
    return results


# =============================================================================
# STEP 2: 20-RECORD HYBRID SMOKE TEST
# =============================================================================
# 20 Diverse Real/Representative Records (4 per vertical)
TWENTY_TEST_RECORDS = [
    # --- STARTUPS (4 records) ---
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
    (
        "startups",
        StartupEntity,
        "STARTUP",
        {
            "source_name": "TechCrunch",
            "source_url": "https://techcrunch.com/2026/08/mistral-ai",
            "text": "Mistral AI is a Paris-based generative AI startup with 250 employees building open-weights foundation models.",
        },
    ),
    (
        "startups",
        StartupEntity,
        "STARTUP",
        {
            "source": {"name": "VentureBeat", "url": "https://venturebeat.com/ai/writer-ai"},
            "raw_snippet": "Writer AI delivers enterprise generative AI platforms with full data privacy guarantees.",
        },
    ),

    # --- PRODUCTS (4 records) ---
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
    (
        "products",
        ProductEntity,
        "PRODUCT",
        {
            "schemaVersion": "1.0",
            "recordType": "PRODUCT",
            "source": {"name": "ProductHunt", "url": "https://www.producthunt.com/posts/perplexity-pro"},
            "content": {
                "title": "Perplexity Pro",
                "startupName": "Perplexity AI",
                "pricingModel": "PAID",
                "description": "Conversational answer engine with multi-model switching.",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    (
        "products",
        ProductEntity,
        "PRODUCT",
        {
            "source": {"name": "HackerNews", "url": "https://news.ycombinator.com/item?id=388291"},
            "raw_text": "We launched vLLM Cloud! High-throughput GPU inference engine for open LLMs. Pricing: Free tier available, Pro is $20/mo (FREEMIUM). Startup: vLLM Project.",
        },
    ),
    (
        "products",
        ProductEntity,
        "PRODUCT",
        {
            "source": {"name": "Twitter / X", "url": "https://x.com/cursor_ai/status/889900"},
            "raw_text": "Cursor AI Code Editor by Anysphere. Built for rapid AI-assisted development. Free hobby plan, paid team plan (FREEMIUM).",
        },
    ),

    # --- RESEARCH PAPERS (4 records) ---
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
    (
        "papers",
        ResearchPaperEntity,
        "RESEARCH_PAPER",
        {
            "source": {"name": "arXiv CS.CL", "url": "https://arxiv.org/abs/2401.01234"},
            "content": {
                "title": "DeepSeek-V3 Technical Report",
                "paper_url": "https://arxiv.org/abs/2401.01234",
                "summary": "We present DeepSeek-V3, a 671B parameter Mixture-of-Experts language model. Code: https://github.com/deepseek-ai/DeepSeek-V3. Authors: DeepSeek AI Team.",
                "published_date": "2024-12-27T00:00:00Z",
            },
        },
    ),
    (
        "papers",
        ResearchPaperEntity,
        "RESEARCH_PAPER",
        {
            "source": {"name": "arXiv CS.LG", "url": "https://arxiv.org/abs/2402.56789"},
            "content": {
                "title": "Qwen2.5 Technical Report",
                "paper_url": "https://arxiv.org/abs/2402.56789",
                "summary": "Qwen2.5 language models achieve state of the art results. Code at https://github.com/QwenLM/Qwen2.5. Authors: Qwen Team, Alibaba Cloud.",
                "published_date": "2024-09-18T00:00:00Z",
            },
        },
    ),

    # --- NEWS (4 records) ---
    (
        "news",
        NewsEntity,
        "NEWS",
        {
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "source": {"name": "MIT Technology Review", "url": "https://technologyreview.com/2026/08/ai-reasoning"},
            "content": {
                "title": "How Test-Time Compute is Reshaping LLM Benchmarks",
                "published_date": datetime.now(timezone.utc).isoformat(),
                "summary": "An in-depth look at reinforcement learning and search during inference.",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    (
        "news",
        NewsEntity,
        "NEWS",
        {
            "schemaVersion": "1.0",
            "recordType": "NEWS",
            "source": {"name": "VentureBeat", "url": "https://venturebeat.com/2026/08/scale-ai-expansion"},
            "content": {
                "title": "Scale AI Expands Defense Data Contracts with $100M Initiative",
                "published_date": datetime.now(timezone.utc).isoformat(),
                "summary": "Scale AI announced a major federal expansion today for defense-grade data curation.",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    (
        "news",
        NewsEntity,
        "NEWS",
        {
            "source": {"name": "Techmeme", "url": "https://techmeme.com/2026/08/hyperscalers-datacenter"},
            "raw_text": "Global cloud hyperscalers announce collective $50B infrastructure expansion for next-gen AI clusters.",
            "published": "2026-08-15T09:00:00Z",
        },
    ),
    (
        "news",
        NewsEntity,
        "NEWS",
        {
            "source": {"name": "Reuters", "url": "https://reuters.com/technology/ai-energy-grid-2026"},
            "raw_text": "Nuclear and clean geothermal power partnerships surge as AI compute demands multiply.",
            "published": "2026-08-15T10:00:00Z",
        },
    ),

    # --- JOBS (4 records) ---
    (
        "jobs",
        JobEntity,
        "JOB",
        {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {"name": "OpenAI Careers", "url": "https://openai.com/careers/research-engineer-pretraining"},
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
    (
        "jobs",
        JobEntity,
        "JOB",
        {
            "schemaVersion": "1.0",
            "recordType": "JOB",
            "source": {"name": "Y Combinator Jobs", "url": "https://ycombinator.com/jobs/scale-infra"},
            "content": {
                "company": "Scale AI",
                "title": "Staff Infrastructure Engineer",
                "date": datetime.now(timezone.utc).isoformat(),
                "is_remote": False,
                "role_family": "Engineering",
            },
            "collectedAt": datetime.now(timezone.utc).isoformat(),
        },
    ),
    (
        "jobs",
        JobEntity,
        "JOB",
        {
            "source": {"name": "LinkedIn", "url": "https://linkedin.com/jobs/view/anthropic-evals-lead"},
            "raw_content": "Anthropic is looking for a Lead AI Safety Evaluations Engineer. Remote friendly in US/UK. Role focuses on red-teaming frontier models.",
        },
    ),
    (
        "jobs",
        JobEntity,
        "JOB",
        {
            "source": {"name": "HiringHackerNews", "url": "https://news.ycombinator.com/item?id=883719"},
            "raw_content": "Cohere (Remote US/Canada) is hiring a Senior Product Manager for Enterprise LLM Fine-tuning APIs.",
        },
    ),
]


from src.llm.deterministic import should_call_llm


async def step_2_run_twenty_records():
    """Run 20-record Hybrid smoke test and compute exact metrics."""
    print("=" * 95)
    print("STEP 2: RUNNING 20-RECORD HYBRID SMOKE TEST (Deterministic-First Architecture)")
    print("-" * 95)

    run_id = f"smoke_20_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    extractor = LLMExtractor(
        quarantine_dir="data/quarantine",
        structured_dir="data/structured",
    )

    t0 = time.time()
    total_records = len(TWENTY_TEST_RECORDS)
    deterministic_bypasses = 0
    llm_required_records = 0
    record_level_llm_calls = 0
    quarantined = 0
    prompt_tokens = 0
    completion_tokens = 0
    llm_trigger_reasons = {}
    quarantine_reasons = {}

    print(f"Executing {total_records} records through Central Deterministic Gate [Deterministic -> LLM Fallback]...\n")

    for i, (vert, schema_cls, rec_type, raw_rec) in enumerate(TWENTY_TEST_RECORDS, 1):
        source_url = raw_rec.get("source", {}).get("url") or raw_rec.get("content", {}).get("paper_url", "") or raw_rec.get("source_url", "")
        raw_text = json.dumps(raw_rec, indent=2)

        # 1. Central Deterministic Gate
        needs_llm, valid_entity, trigger_reason = should_call_llm(raw_rec, vert, schema_cls)

        if not needs_llm and valid_entity is not None:
            deterministic_bypasses += 1
            print(f"  #{i:02d} [{vert.upper():<8}] ✅ DETERMINISTIC BYPASS (0 tokens, 0ms)")
            continue

        # 2. Unavoidable LLM Extraction
        llm_required_records += 1
        record_level_llm_calls += 1
        llm_trigger_reasons[trigger_reason] = llm_trigger_reasons.get(trigger_reason, 0) + 1

        p_init = extractor.router.stats.get("prompt_tokens", 0) if extractor.router else 0
        c_init = extractor.router.stats.get("completion_tokens", 0) if extractor.router else 0

        entity = extractor.extract_entity(
            raw_text=raw_text,
            schema_cls=schema_cls,
            source_url=source_url,
            record_type=rec_type,
            allow_cache=False,
            run_id=run_id,
        )

        p_delta = (extractor.router.stats.get("prompt_tokens", 0) - p_init) if extractor.router else 0
        c_delta = (extractor.router.stats.get("completion_tokens", 0) - c_init) if extractor.router else 0
        prompt_tokens += p_delta
        completion_tokens += c_delta

        if entity:
            print(f"  #{i:02d} [{vert.upper():<8}] 🧠 LLM EXTRACTION SUCCESS ({p_delta + c_delta} tokens | Reason: {trigger_reason})")
        else:
            quarantined += 1
            quarantine_reasons[trigger_reason] = quarantine_reasons.get(trigger_reason, 0) + 1
            print(f"  #{i:02d} [{vert.upper():<8}] ⚠️ QUARANTINED (Reason: {trigger_reason})")

    runtime_s = round(time.time() - t0, 2)
    fallback_escalations = extractor.router.stats.get("fallback_calls", 0) if extractor.router else 0
    rate_limit_429 = extractor.router.stats.get("429_count", 0) if extractor.router else 0
    provider_attempts = record_level_llm_calls + fallback_escalations

    llm_usage_rate = round((record_level_llm_calls / total_records) * 100, 1)
    bypass_rate = round((deterministic_bypasses / total_records) * 100, 1)

    avg_p_tokens = round(prompt_tokens / max(1, record_level_llm_calls), 1) if record_level_llm_calls > 0 else 0
    avg_c_tokens = round(completion_tokens / max(1, record_level_llm_calls), 1) if record_level_llm_calls > 0 else 0

    print("\n" + "=" * 95)
    print("📊 20-RECORD HYBRID SMOKE TEST RESULTS (MEASURED)")
    print("-" * 95)
    print(f"  • Total Records Tested          : {total_records}")
    print(f"  • Deterministic Bypasses        : {deterministic_bypasses} ({bypass_rate}%)")
    print(f"  • LLM Required Records          : {llm_required_records}")
    print(f"  • Record-Level LLM Calls        : {record_level_llm_calls} ({llm_usage_rate}%)")
    print(f"  • Provider API Attempts         : {provider_attempts}")
    print(f"  • Fallback Escalations          : {fallback_escalations}")
    print(f"  • 429 Rate Limit Count          : {rate_limit_429}")
    print(f"  • Total Prompt Tokens           : {prompt_tokens}")
    print(f"  • Total Completion Tokens       : {completion_tokens}")
    print(f"  • Avg Prompt Tokens / LLM Call  : {avg_p_tokens}")
    print(f"  • Avg Completion Tokens / LLM   : {avg_c_tokens}")
    print(f"  • Quarantined Records           : {quarantined}")
    print(f"  • LLM Trigger Reasons           : {llm_trigger_reasons}")
    print(f"  • Quarantine Reasons            : {quarantine_reasons}")
    print(f"  • Total Runtime                 : {runtime_s}s")
    print("=" * 95)

    print("\nExact Measured Output Payload:")
    print(json.dumps({
        "total_records": total_records,
        "deterministic_bypasses": deterministic_bypasses,
        "deterministic_bypass_pct": bypass_rate,
        "llm_required_records": llm_required_records,
        "record_level_llm_calls": record_level_llm_calls,
        "provider_attempts": provider_attempts,
        "fallback_escalations": fallback_escalations,
        "rate_limited_429": rate_limit_429,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "avg_prompt_tokens_per_llm_record": avg_p_tokens,
        "avg_completion_tokens_per_llm_record": avg_c_tokens,
        "quarantined": quarantined,
        "llm_usage_rate_pct": llm_usage_rate,
        "runtime_seconds": runtime_s,
        "llm_trigger_reasons": llm_trigger_reasons,
    }, indent=2))
    print("=" * 95 + "\n")


def main():
    print("\n" + "#" * 95)
    print("🚀 AETHERIA // MODEL VERIFICATION & 20-RECORD HYBRID SMOKE TEST")
    print("#" * 95)
    step_1_verify_all_models()
    asyncio.run(step_2_run_twenty_records())


if __name__ == "__main__":
    main()
