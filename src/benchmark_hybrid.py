"""Controlled Benchmark for Hybrid Extraction Strategy (10 and 50 records).

Runs empirical evaluation against real raw dataset without estimations:
- Measures deterministic bypasses vs LLM calls
- Measures fallbacks, 429 rate limits, tokens, latency, and runtime
- Computes exact llm_usage_rate = llm_calls / total_records

Usage:
    python src/benchmark_hybrid.py --limit 10
    python src/benchmark_hybrid.py --limit 50
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

from src.llm.extractor import LLMExtractor
from src.schemas import (
    JobEntity,
    NewsEntity,
    ProductEntity,
    ResearchPaperEntity,
    StartupEntity,
)
from src.structure import SCHEMA_MAP, process_vertical

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark")


def run_benchmark(limit_per_vertical: int, mode: str = "hybrid"):
    """Execute benchmark across all 5 verticals and report exact measurements."""
    raw_dir = PROJECT_ROOT / "data/raw"
    bench_dir = PROJECT_ROOT / f"data/benchmark_{limit_per_vertical}"
    bench_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = bench_dir / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    run_id = f"bench_{limit_per_vertical}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    print("\n" + "=" * 90)
    print(f"📊 RUNNING CONTROLLED BENCHMARK [{mode.upper()} MODE] (Target: {limit_per_vertical * 5} records total)")
    print(f"   Run ID: {run_id} | Per-vertical limit: {limit_per_vertical}")
    print("=" * 90)

    extractor = LLMExtractor(
        quarantine_dir=str(quarantine_dir),
        structured_dir=str(bench_dir),
    )

    t_start = time.time()
    vertical_stats = {}

    for vert in ["papers", "startups", "products", "news", "jobs"]:
        stat = process_vertical(
            vertical=vert,
            extractor=extractor,
            raw_dir=raw_dir,
            structured_dir=bench_dir,
            limit=limit_per_vertical,
            llm_mode=mode,
            run_id=run_id,
        )
        vertical_stats[vert] = stat

    runtime_s = round(time.time() - t_start, 2)

    # Aggregations
    tot_rec = sum(s.get("total_records", 0) for s in vertical_stats.values())
    tot_bypass = sum(s.get("deterministic_bypasses", 0) for s in vertical_stats.values())
    tot_req = sum(s.get("llm_required_records", 0) for s in vertical_stats.values())
    tot_rec_calls = sum(s.get("record_level_llm_calls", 0) for s in vertical_stats.values())
    tot_prov_attempts = sum(s.get("provider_attempts", 0) for s in vertical_stats.values())
    tot_cache = sum(s.get("llm_cache_hits", 0) for s in vertical_stats.values())
    tot_fallback = sum(s.get("fallback_escalations", 0) for s in vertical_stats.values())
    tot_429 = sum(s.get("rate_limited_429", 0) for s in vertical_stats.values())
    tot_val_fail = sum(s.get("validation_failures", 0) for s in vertical_stats.values())
    tot_repair = sum(s.get("repair_attempts", 0) for s in vertical_stats.values())
    tot_quarantine = sum(s.get("quarantined", 0) for s in vertical_stats.values())

    p_tokens = extractor.router.stats.get("prompt_tokens", 0) if extractor.router else 0
    c_tokens = extractor.router.stats.get("completion_tokens", 0) if extractor.router else 0

    llm_usage_rate = round((tot_rec_calls / max(1, tot_rec)) * 100, 1)
    bypass_rate = round((tot_bypass / max(1, tot_rec)) * 100, 1)

    avg_p_tokens = round(p_tokens / max(1, tot_rec_calls), 1) if tot_rec_calls > 0 else 0
    avg_c_tokens = round(c_tokens / max(1, tot_rec_calls), 1) if tot_rec_calls > 0 else 0

    # Aggregate trigger and quarantine reasons
    all_triggers = {}
    all_quarantine_reasons = {}
    for s in vertical_stats.values():
        for k, v in s.get("llm_trigger_reasons", {}).items():
            all_triggers[k] = all_triggers.get(k, 0) + v
        for k, v in s.get("quarantine_reasons", {}).items():
            all_quarantine_reasons[k] = all_quarantine_reasons.get(k, 0) + v

    print("\n" + "=" * 95)
    print("📈 MEASURED BENCHMARK AUDIT RESULTS")
    print("-" * 95)
    print(f"{'VERTICAL':<14} | {'RECORDS':<8} | {'BYPASS':<8} | {'LLM_REQ':<8} | {'PROV_ATT':<9} | {'FALLBACK':<9} | {'429s':<5} | {'QUARANTINE':<10}")
    print("-" * 95)
    for v, s in vertical_stats.items():
        print(f"{v.capitalize():<14} | {s.get('total_records', 0):<8} | "
              f"{s.get('deterministic_bypasses', 0):<8} | {s.get('llm_required_records', 0):<8} | "
              f"{s.get('provider_attempts', 0):<9} | {s.get('fallback_escalations', 0):<9} | "
              f"{s.get('rate_limited_429', 0):<5} | {s.get('quarantined', 0):<10}")
    print("-" * 95)
    print(f"{'TOTALS':<14} | {tot_rec:<8} | {tot_bypass:<8} | {tot_req:<8} | {tot_prov_attempts:<9} | "
          f"{tot_fallback:<9} | {tot_429:<5} | {tot_quarantine:<10}")
    print("=" * 95)

    report_payload = {
        "benchmark_run_id": run_id,
        "total_records": tot_rec,
        "deterministic_bypasses": tot_bypass,
        "deterministic_bypass_pct": bypass_rate,
        "llm_required_records": tot_req,
        "record_level_llm_calls": tot_rec_calls,
        "provider_attempts": tot_prov_attempts,
        "fallback_escalations": tot_fallback,
        "llm_usage_rate_pct": llm_usage_rate,
        "llm_cache_hits": tot_cache,
        "rate_limited_429": tot_429,
        "validation_failures": tot_val_fail,
        "repair_attempts": tot_repair,
        "quarantined_records": tot_quarantine,
        "llm_trigger_reasons": all_triggers,
        "quarantine_reasons": all_quarantine_reasons,
        "prompt_tokens": p_tokens,
        "completion_tokens": c_tokens,
        "total_tokens": p_tokens + c_tokens,
        "avg_prompt_tokens_per_llm_record": avg_p_tokens,
        "avg_completion_tokens_per_llm_record": avg_c_tokens,
        "runtime_seconds": runtime_s,
    }

    print("\nExact Measured Metrics JSON:")
    print(json.dumps(report_payload, indent=2))
    print("=" * 95 + "\n")
    return report_payload


def main():
    parser = argparse.ArgumentParser(description="Run Controlled Hybrid Extraction Benchmark")
    parser.add_argument("--limit", type=int, default=10, help="Per-vertical record limit (e.g. 2 for 10 total, 10 for 50 total)")
    parser.add_argument("--mode", choices=["hybrid", "force"], default="hybrid", help="Extraction mode")
    args = parser.parse_args()

    per_vert = max(1, args.limit // 5) if args.limit >= 5 else args.limit
    run_benchmark(limit_per_vertical=per_vert, mode=args.mode)


if __name__ == "__main__":
    main()
