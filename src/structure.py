"""CLI Structuring Pipeline for Phase III LLM Extraction & Token-Efficient Hybrid Routing.

Hybrid Strategy:
1. Deterministic Bypass: If raw record passes strict completeness (valid types, required fields,
   source URL, no unsupported inference), bypasses LLM to save tokens and latency.
2. Incomplete / Unstructured Records: Routed through LiteLLM Router -> Pydantic Validation -> 1 Repair Prompt -> Quarantine.
3. Telemetry & Logs: Every actual LLM invocation persists to Supabase llm_logs with run_id, token usage, latency, status, fallback_from.
4. LLM_MODE: 'hybrid' (default) or 'force' (forces LLM evaluation).
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type, TypeVar
from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.extractor import LLMExtractor
from src.schemas import (
    JobEntity,
    NewsEntity,
    ProductEntity,
    ResearchPaperEntity,
    StartupEntity,
)

T = TypeVar("T")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("structure_pipeline")

SCHEMA_MAP = {
    "papers": (ResearchPaperEntity, "RESEARCH_PAPER", "research_papers"),
    "startups": (StartupEntity, "STARTUP", "startups"),
    "products": (ProductEntity, "PRODUCT", "products"),
    "news": (NewsEntity, "NEWS", "news"),
    "jobs": (JobEntity, "JOB", "jobs"),
}


from src.llm.deterministic import should_call_llm


def should_use_llm(raw_record: dict, vertical: str, schema_cls: Type[T]) -> Tuple[bool, Optional[T]]:
    """Backward-compatible wrapper for central LLM Gate should_call_llm."""
    needs_llm, entity, _ = should_call_llm(raw_record, vertical, schema_cls)
    return needs_llm, entity


def check_record_completeness(raw_record: dict, vertical: str, schema_cls: Type[T]) -> Tuple[bool, Optional[T]]:
    """Backward-compatible alias."""
    needs_llm, entity, _ = should_call_llm(raw_record, vertical, schema_cls)
    return not needs_llm, entity


def process_vertical(
    vertical: str,
    extractor: LLMExtractor,
    raw_dir: Path,
    structured_dir: Path,
    limit: int = 1000,
    llm_mode: Optional[str] = None,
    run_id: Optional[str] = None,
) -> dict:
    """Process a single vertical with Hybrid deterministic-first routing strategy."""
    schema_cls, record_type, db_table = SCHEMA_MAP[vertical]
    raw_file = raw_dir / f"{vertical}.jsonl"
    out_file = structured_dir / f"{vertical}.jsonl"

    mode = (llm_mode or os.getenv("LLM_MODE", "hybrid")).lower().strip()
    effective_run_id = run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    stats = {
        "total_records": 0,
        "deterministic_bypasses": 0,
        "llm_required_records": 0,
        "record_level_llm_calls": 0,
        "provider_attempts": 0,
        "fallback_escalations": 0,
        "llm_cache_hits": 0,
        "rate_limited_429": 0,
        "validation_failures": 0,
        "repair_attempts": 0,
        "quarantined": 0,
        "llm_trigger_reasons": {},
        "quarantine_reasons": {},
    }

    if not raw_file.exists():
        logger.warning("Raw input file not found: %s", raw_file)
        return stats

    # Load existing structured records to ensure historical data is never wiped
    seen_urls = set()
    existing_count = 0
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f_ex:
                for l in f_ex:
                    if l.strip():
                        try:
                            rec = json.loads(l)
                            url = rec.get("source", {}).get("url") or rec.get("content", {}).get("paper_url", "")
                            if url:
                                seen_urls.add(url)
                            existing_count += 1
                        except Exception:
                            pass
        except Exception:
            pass

    logger.info("Structuring '%s' [Mode: %s] (Existing Records: %d, New Limit: %d)", vertical, mode.upper(), existing_count, limit)

    written_records = 0
    with open(raw_file, "r", encoding="utf-8") as f_in, open(out_file, "a", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue
            if written_records >= limit:
                break

            try:
                raw_record = json.loads(line)
            except Exception:
                continue

            source_url = raw_record.get("source", {}).get("url") or raw_record.get("content", {}).get("paper_url", "")
            
            # Skip if this URL was already structured in historical runs
            if source_url and source_url in seen_urls:
                continue
            if source_url:
                seen_urls.add(source_url)

            stats["total_records"] += 1
            raw_text = json.dumps(raw_record, indent=2)

            entity = None

            # 1. Central Deterministic Gate
            needs_llm, valid_entity, trigger_reason = should_call_llm(raw_record, vertical, schema_cls)

            # In sample mode or when LLM_SAMPLE is set, route first 2 records of news/jobs to LLM to exercise LiteLLM fallback chain
            is_sample_target = (mode in ("sample", "hybrid_eval") or os.getenv("LLM_SAMPLE_EVAL", "false").lower() == "true") and (written_records < 2 and vertical in ("news", "jobs"))

            if mode == "hybrid" and not needs_llm and valid_entity is not None and not is_sample_target:
                entity = extractor.post_validate_and_ground(valid_entity)
                stats["deterministic_bypasses"] += 1
                extractor.stats["deterministic_bypasses"] += 1

            # 2. Incomplete records OR FORCE/SAMPLE mode -> LiteLLM Router Execution
            if entity is None:
                stats["llm_required_records"] += 1
                stats["record_level_llm_calls"] += 1
                stats["llm_trigger_reasons"][trigger_reason] = stats["llm_trigger_reasons"].get(trigger_reason, 0) + 1

                initial_calls = extractor.stats.get("llm_calls", 0)
                initial_cache = extractor.stats.get("llm_cache_hits", 0)
                initial_repairs = extractor.stats.get("repair_count", 0)
                initial_quarantine = extractor.stats.get("quarantine_count", 0)

                entity = extractor.extract_entity(
                    raw_text=raw_text,
                    schema_cls=schema_cls,
                    source_url=source_url,
                    record_type=record_type,
                    run_id=effective_run_id,
                )

                if extractor.stats.get("llm_cache_hits", 0) > initial_cache:
                    stats["llm_cache_hits"] += (extractor.stats.get("llm_cache_hits", 0) - initial_cache)
                if extractor.stats.get("repair_count", 0) > initial_repairs:
                    stats["repair_attempts"] += (extractor.stats.get("repair_count", 0) - initial_repairs)
                    stats["validation_failures"] += (extractor.stats.get("repair_count", 0) - initial_repairs)
                if extractor.stats.get("quarantine_count", 0) > initial_quarantine:
                    stats["quarantined"] += (extractor.stats.get("quarantine_count", 0) - initial_quarantine)
                    stats["quarantine_reasons"]["extractor_quarantine"] = stats["quarantine_reasons"].get("extractor_quarantine", 0) + 1

            if entity:
                f_out.write(entity.model_dump_json() + "\n")
                written_records += 1
            else:
                stats["quarantined"] += 1

    stats["final_valid"] = written_records
    stats["llm_structured"] = max(0, written_records - stats["deterministic_bypasses"])

    # Pull router-level stats
    if extractor.router:
        stats["fallback_escalations"] = extractor.router.stats.get("fallback_calls", 0)
        stats["rate_limited_429"] = extractor.router.stats.get("429_count", 0)
        stats["provider_attempts"] = (
            stats["record_level_llm_calls"] + stats["fallback_escalations"] + stats["repair_attempts"]
        )

    return stats


def print_structuring_report(all_stats: Dict[str, dict], mode: str) -> None:
    """Print structured audit report table conforming to evaluation metrics."""
    tot_rec = sum(s.get("total_records", 0) for s in all_stats.values())
    tot_bypass = sum(s.get("deterministic_bypasses", 0) for s in all_stats.values())
    tot_req = sum(s.get("llm_required_records", 0) for s in all_stats.values())
    tot_rec_calls = sum(s.get("record_level_llm_calls", 0) for s in all_stats.values())
    tot_prov_attempts = sum(s.get("provider_attempts", 0) for s in all_stats.values())
    tot_cache = sum(s.get("llm_cache_hits", 0) for s in all_stats.values())
    tot_fallback = sum(s.get("fallback_escalations", 0) for s in all_stats.values())
    tot_429 = sum(s.get("rate_limited_429", 0) for s in all_stats.values())
    tot_val_fail = sum(s.get("validation_failures", 0) for s in all_stats.values())
    tot_repair = sum(s.get("repair_attempts", 0) for s in all_stats.values())
    tot_quarantine = sum(s.get("quarantined", 0) for s in all_stats.values())

    llm_usage_rate = round((tot_rec_calls / max(1, tot_rec)) * 100, 1)
    bypass_rate = round((tot_bypass / max(1, tot_rec)) * 100, 1)

    print("\n" + "=" * 95)
    print(f"📊 PHASE III STRUCTURING METRICS REPORT [MODE: {mode.upper()}]")
    print("-" * 95)
    print(f"{'VERTICAL':<14} | {'TOTAL':<6} | {'BYPASS':<7} | {'LLM_REQ':<8} | {'PROV_ATT':<9} | {'FALLBACK':<9} | {'429':<5} | {'QUARANTINE':<10}")
    print("-" * 95)
    for v, s in all_stats.items():
        print(f"{v.capitalize():<14} | {s.get('total_records', 0):<6} | "
              f"{s.get('deterministic_bypasses', 0):<7} | {s.get('llm_required_records', 0):<8} | "
              f"{s.get('provider_attempts', 0):<9} | {s.get('fallback_escalations', 0):<9} | "
              f"{s.get('rate_limited_429', 0):<5} | {s.get('quarantined', 0):<10}")
    print("-" * 95)
    print(f"{'TOTALS':<14} | {tot_rec:<6} | {tot_bypass:<7} | {tot_req:<8} | {tot_prov_attempts:<9} | "
          f"{tot_fallback:<9} | {tot_429:<5} | {tot_quarantine:<10}")
    print("=" * 95)
    print(json.dumps({
        "total_records": tot_rec,
        "deterministic_bypasses": tot_bypass,
        "deterministic_bypass_pct": bypass_rate,
        "llm_required_records": tot_req,
        "record_level_llm_calls": tot_rec_calls,
        "provider_attempts": tot_prov_attempts,
        "fallback_escalations": tot_fallback,
        "llm_cache_hits": tot_cache,
        "rate_limited_429": tot_429,
        "validation_failures": tot_val_fail,
        "repair_attempts": tot_repair,
        "quarantined": tot_quarantine,
        "llm_usage_rate_pct": llm_usage_rate,
    }, indent=2))
    print("=" * 95 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Phase III Hybrid LLM Structuring Engine")
    parser.add_argument(
        "--vertical",
        choices=["papers", "startups", "products", "news", "jobs"],
        help="Vertical dataset to structure",
    )
    parser.add_argument("--all", action="store_true", help="Process all verticals")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum records to process per vertical")
    parser.add_argument("--mode", choices=["hybrid", "force"], default=os.getenv("LLM_MODE", "hybrid"),
                        help="Structuring mode: 'hybrid' (deterministic bypass) or 'force' (evaluate via LLM)")
    parser.add_argument("--raw-dir", default="data/raw", help="Raw input directory")
    parser.add_argument("--structured-dir", default="data/structured", help="Structured output directory")
    parser.add_argument("--quarantine-dir", default="data/quarantine", help="Quarantine output directory")

    args = parser.parse_args()
    load_dotenv()

    extractor = LLMExtractor(
        quarantine_dir=args.quarantine_dir,
        structured_dir=args.structured_dir,
    )

    raw_dir = Path(args.raw_dir)
    structured_dir = Path(args.structured_dir)

    verticals = list(SCHEMA_MAP.keys()) if args.all else [args.vertical] if args.vertical else []
    if not verticals:
        parser.print_help()
        sys.exit(1)

    all_stats = {}
    for vert in verticals:
        stats = process_vertical(vert, extractor, raw_dir, structured_dir, args.limit, llm_mode=args.mode)
        all_stats[vert] = stats

    print_structuring_report(all_stats, mode=args.mode)


if __name__ == "__main__":
    main()
