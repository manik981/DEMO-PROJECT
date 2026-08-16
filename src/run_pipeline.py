"""Unified End-to-End Execution Pipeline for AETHERIA.

Orchestrates all 6 architectural phases in sequence:
Phase I & II: Scraping / Harvesting (Papers, Startups, Products, 24h News, 24h Jobs)
Phase III: LLM / Deterministic Structuring
Phase IV: Deterministic Entity Resolution & Canonical Mapping
Phase V: Supabase PostgreSQL Persistence
Phase VI: Google Sheets 6-Tab Synchronized Export

Usage:
    python src/run_pipeline.py
    python src/run_pipeline.py --limit 50
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extract import (
    run_papers_extraction,
    run_startups_extraction,
    run_products_extraction,
    run_news_extraction,
    run_jobs_extraction,
)
from src.structure import process_vertical, SCHEMA_MAP
from src.llm.extractor import LLMExtractor
from src.resolve import resolve_startups, resolve_products
from src.resolver.entity_resolver import EntityResolver
from src.sync_supabase import sync_all_tables
from src.export.sheets import GoogleSheetsExporter
from src.telemetry.tracker import PipelineTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_pipeline")


async def run_full_pipeline(limit: int = 100, freshness_hours: float = 24.0, concurrency: int = 10, llm_mode: str = "hybrid", run_id: str | None = None, user_id: str | None = None):
    load_dotenv()
    tracker = PipelineTracker(run_id=run_id, user_id=user_id)
    tracker.start_pipeline(requested_limit=limit, freshness_window_hours=freshness_hours)

    print("\n" + "=" * 80)
    print("🚀 AETHERIA // FULL 6-PHASE AUTONOMOUS PIPELINE EXECUTION")
    print("=" * 80)
    print(f"Run ID: {tracker.run_id}")
    print(f"Timestamp: {tracker.started_at_iso}")
    print(f"Bulk Ingestion Target: {limit} records/vertical")
    print(f"Freshness Window: {freshness_hours}h")
    if not user_id:
        user_id = "anonymous_demo"

    # Setup core directories partitioned by user_id
    raw_dir = PROJECT_ROOT / "data/raw" / user_id
    structured_dir = PROJECT_ROOT / "data/structured" / user_id
    resolved_dir = PROJECT_ROOT / "data/resolved" / user_id
    output_dir = PROJECT_ROOT / "data/output" / user_id

    for d in [raw_dir, structured_dir, resolved_dir, output_dir]:
        d.mkdir(parents=True, exist_ok=True)

    entities_canonicalized = 0
    supabase_written = 0
    sheets_exported = 0

    try:
        # -------------------------------------------------------------------------
        # PHASE I: HARVESTING & SCRAPING (Concurrent Multi-Source Ingestion)
        # -------------------------------------------------------------------------
        print("\n[PHASE 1/6] 🌐 SCRAPING & HARVESTING (Parallel Multi-Vertical Ingestion)")
        print("-" * 80)
        tracker.start_phase(1, "Scraping & Harvesting")
        harvest_stats = {}
        harvest_dups = {}

        async def scrape_papers():
            try:
                stat = await run_papers_extraction(limit=limit, output_dir=raw_dir)
                harvest_stats["papers"] = stat.get("papers_emitted", 0)
                harvest_dups["papers"] = stat.get("duplicates_skipped", 0)
                print(f"  ✅ Research Papers (Crossref) : {harvest_stats['papers']} emitted")
            except Exception as e:
                logger.error("Papers scraping error: %s", e)
                harvest_stats["papers"] = 0
                harvest_dups["papers"] = 0

        async def scrape_startups():
            try:
                stat = await run_startups_extraction(limit=limit, concurrency=concurrency, output_dir=raw_dir)
                harvest_stats["startups"] = stat.get("startups_emitted", 0)
                harvest_dups["startups"] = stat.get("duplicates_skipped", 0)
                print(f"  ✅ Startups             : {harvest_stats['startups']} emitted")
            except Exception as e:
                logger.error("Startups scraping error: %s", e)
                harvest_stats["startups"] = 0
                harvest_dups["startups"] = 0

        async def scrape_products():
            try:
                stat = await run_products_extraction(limit=limit, concurrency=concurrency, output_dir=raw_dir)
                harvest_stats["products"] = stat.get("products_emitted", 0)
                harvest_dups["products"] = stat.get("duplicates_skipped", 0)
                print(f"  ✅ AI Products          : {harvest_stats['products']} emitted")
            except Exception as e:
                logger.error("Products scraping error: %s", e)
                harvest_stats["products"] = 0
                harvest_dups["products"] = 0

        async def scrape_news():
            try:
                stat = await run_news_extraction(freshness_hours=freshness_hours, output_dir=raw_dir)
                harvest_stats["news"] = stat.get("emitted", 0)
                harvest_dups["news"] = stat.get("duplicates_skipped", 0)
                print(f"  ✅ 24h AI News          : {harvest_stats['news']} fresh articles emitted")
            except Exception as e:
                logger.error("News scraping error: %s", e)
                harvest_stats["news"] = 0
                harvest_dups["news"] = 0

        async def scrape_jobs():
            try:
                stat = await run_jobs_extraction(limit=limit, freshness_hours=freshness_hours, output_dir=raw_dir)
                harvest_stats["jobs"] = stat.get("emitted", 0)
                harvest_dups["jobs"] = stat.get("duplicates_skipped", 0)
                print(f"  ✅ 24h AI Jobs          : {harvest_stats['jobs']} fresh roles emitted")
            except Exception as e:
                logger.error("Jobs scraping error: %s", e)
                harvest_stats["jobs"] = 0
                harvest_dups["jobs"] = 0

        # Launch all 5 vertical scrapers concurrently!
        await asyncio.gather(
            scrape_papers(),
            scrape_startups(),
            scrape_products(),
            scrape_news(),
            scrape_jobs(),
        )

        total_emitted = sum(harvest_stats.values())
        tracker.finish_phase(
            phase_number=1,
            phase_name="Scraping & Harvesting",
            records_in=limit * 5,
            records_out=total_emitted,
            metadata={"harvest_stats": harvest_stats, "harvest_dups": harvest_dups},
        )

        # -------------------------------------------------------------------------
        # PHASE II & III: STRUCTURING & LLM VALIDATION (Hybrid Execution)
        # -------------------------------------------------------------------------
        print(f"\n[PHASE 3/6] 🧠 STRUCTURING & SCHEMA VALIDATION [LLM_MODE: {llm_mode.upper()}]")
        print("-" * 80)
        tracker.start_phase(2, "Structuring & Schema Validation")
        extractor = LLMExtractor()
        struct_stats = {}

        async def struct_vertical(v: str):
            try:
                stat = await asyncio.to_thread(process_vertical, v, extractor, raw_dir, structured_dir, limit=limit, llm_mode=llm_mode)
                struct_stats[v] = stat
                tot = stat.get("total_records", 0)
                det = stat.get("deterministic_bypasses", 0)
                llm_s = stat.get("llm_structured", 0)
                val = stat.get("final_valid", 0)
                print(f"  ✅ {v.capitalize():<12} : Requested: {limit} | Harvested: {harvest_stats.get(v, tot)} | Deterministic: {det} | LLM Structured: {llm_s} | Final Valid: {val}")

                tracker.record_vertical(
                    vertical=v,
                    records_requested=limit,
                    records_scraped=harvest_stats.get(v, tot),
                    records_emitted=tot,
                    records_structured=val,
                    duplicates_skipped=harvest_dups.get(v, 0),
                    deterministic_bypasses=det,
                    llm_calls=stat.get("llm_calls", 0),
                    llm_cache_hits=stat.get("llm_cache_hits", 0),
                    fallback_calls=stat.get("fallback_calls", 0),
                    quarantined=stat.get("quarantined", 0),
                    final_valid=val,
                    prompt_tokens=stat.get("prompt_tokens", 0),
                    completion_tokens=stat.get("completion_tokens", 0),
                    total_tokens=stat.get("total_tokens", 0),
                )
            except Exception as e:
                logger.error("Structuring error for %s: %s", v, e)

        # Structure all 5 verticals in parallel!
        await asyncio.gather(*[struct_vertical(v) for v in ["papers", "startups", "products", "news", "jobs"]])

        # Metrics Summary
        tot_processed = sum(s.get("total_records", 0) for s in struct_stats.values())
        tot_bypass = sum(s.get("deterministic_bypasses", 0) for s in struct_stats.values())
        tot_llm_structured = sum(s.get("llm_structured", 0) for s in struct_stats.values())
        tot_final_valid = sum(s.get("final_valid", 0) for s in struct_stats.values())
        tot_llm = sum(s.get("llm_calls", 0) for s in struct_stats.values())
        tot_cache = sum(s.get("llm_cache_hits", 0) for s in struct_stats.values())
        tot_fallback = sum(s.get("fallback_calls", 0) for s in struct_stats.values())
        tot_quarantine = sum(s.get("quarantined", 0) for s in struct_stats.values())

        print("\n  📊 Phase III Structuring Metrics:")
        print(f"     • Total Processed        : {tot_processed}")
        print(f"     • Deterministic Bypasses : {tot_bypass}")
        print(f"     • LLM Structured Valid   : {tot_llm_structured}")
        print(f"     • Final Valid Output     : {tot_final_valid}")
        print(f"     • Actual LLM Calls Made  : {tot_llm}")
        print(f"     • Fallback Calls         : {tot_fallback}")
        print(f"     • Quarantined            : {tot_quarantine}")

        tracker.finish_phase(
            phase_number=2,
            phase_name="Structuring & Schema Validation",
            records_in=tot_processed,
            records_out=tot_final_valid,
            records_failed=tot_quarantine,
        )

        # -------------------------------------------------------------------------
        # PHASE IV: DETERMINISTIC ENTITY RESOLUTION (Parallel Execution)
        # -------------------------------------------------------------------------
        print("\n[PHASE 4/6] 🔍 DETERMINISTIC ENTITY RESOLUTION")
        print("-" * 80)
        tracker.start_phase(3, "Deterministic Entity Resolution")
        resolver = EntityResolver(
            seed_path=str(PROJECT_ROOT / "data/seed/canonical_startups.json"),
            output_csv_path=str(output_dir / "entity_mapping_log.csv"),
            review_csv_path=str(output_dir / "manual_review_entities.csv"),
        )
        s_task = asyncio.to_thread(resolve_startups, resolver, structured_dir, resolved_dir)
        p_task = asyncio.to_thread(resolve_products, resolver, structured_dir, resolved_dir)
        s_stats, p_stats = await asyncio.gather(s_task, p_task)

        entities_canonicalized = s_stats.get("canonicalized", 0) + p_stats.get("canonicalized", 0)
        print(f"  ✅ Startups Canonicalized: {s_stats.get('canonicalized', 0)} / {s_stats.get('processed', 0)}")
        print(f"  ✅ Products Canonicalized: {p_stats.get('canonicalized', 0)} / {p_stats.get('processed', 0)}")
        print(f"  ✅ Entity Mapping Log written to: data/output/entity_mapping_log.csv")

        tracker.finish_phase(
            phase_number=3,
            phase_name="Deterministic Entity Resolution",
            records_in=s_stats.get("processed", 0) + p_stats.get("processed", 0),
            records_out=entities_canonicalized,
        )

        # -------------------------------------------------------------------------
        # PHASE V: PERSISTENCE & SUPABASE LIVE POSTGRESQL SYNC
        # -------------------------------------------------------------------------
        print("\n[PHASE 5/6] 🗄️ SUPABASE POSTGRESQL PERSISTENCE & SYNC")
        print("-" * 80)
        tracker.start_phase(4, "Supabase Persistence")
        try:
            sync_res = await sync_all_tables(user_id=user_id)
            supabase_written = sync_res.get("total_unique_records", 0) if isinstance(sync_res, dict) else tot_final_valid
            tracker.finish_phase(
                phase_number=4,
                phase_name="Supabase Persistence",
                records_in=tot_final_valid,
                records_out=supabase_written,
                metadata=sync_res if isinstance(sync_res, dict) else {},
            )
        except Exception as e:
            logger.error("Supabase sync error: %s", e)
            tracker.finish_phase(
                phase_number=4,
                phase_name="Supabase Persistence",
                records_in=tot_final_valid,
                records_out=0,
                error_message=str(e),
                status="failed",
            )

        # Finalize and persist telemetry immediately for core pipeline completion
        await tracker.persist_telemetry(
            status="completed",
            entities_canonicalized=entities_canonicalized,
            supabase_rows_written=supabase_written,
            google_sheets_rows_exported=0,
        )

        print("=" * 80)
        print(f"🎉 CORE PIPELINE EXECUTION FINISHED SUCCESSFULLY! [Run ID: {tracker.run_id}]")
        print("=" * 80 + "\n")

        # -------------------------------------------------------------------------
        # PHASE VI: GOOGLE SHEETS 6-TAB EXPORT & OBSERVABILITY
        # -------------------------------------------------------------------------
        def run_async_sheets_export():
            try:
                print("\n[PHASE 6/6] 📊 GOOGLE SHEETS EXPORT (6-Tab Cloud Sync)")
                print("-" * 80)
                exporter = GoogleSheetsExporter(user_id=user_id)
                res = exporter.export_all_tabs()
                tot_exported = sum(max(0, c - 1) for c in res.values())
                print(f"✅ [Background Worker] Google Sheets sync complete: {tot_exported} rows pushed across 6 tabs.")
            except Exception as ex:
                logger.warning("Background Google Sheets export non-blocking error: %s", ex)

        sheets_thread = threading.Thread(target=run_async_sheets_export, daemon=False)
        sheets_thread.start()
        sheets_thread.join(timeout=15.0)

    except Exception as e:
        logger.error("Pipeline fatal execution error: %s", e)
        await tracker.persist_telemetry(
            status="failed",
            error_summary=str(e),
            entities_canonicalized=entities_canonicalized,
            supabase_rows_written=supabase_written,
            google_sheets_rows_exported=sheets_exported,
        )
        raise


def main():
    parser = argparse.ArgumentParser(description="AETHERIA Full Pipeline Runner")
    parser.add_argument("--limit", type=int, default=100, help="Record limit per bulk vertical")
    parser.add_argument("--user-id", type=str, default=None, help="Authenticated Supabase User UUID")
    parser.add_argument("--freshness-hours", type=float, default=24.0, help="Freshness threshold in hours")
    parser.add_argument("--concurrency", type=int, default=10, help="Worker concurrency")
    parser.add_argument("--llm-mode", choices=["hybrid", "force"], default=os.getenv("LLM_MODE", "hybrid"),
                        help="LLM Structuring mode: 'hybrid' (deterministic bypass) or 'force' (evaluate via LLM)")
    args = parser.parse_args()

    asyncio.run(run_full_pipeline(
        limit=args.limit,
        user_id=args.user_id,
        freshness_hours=args.freshness_hours,
        concurrency=args.concurrency,
        llm_mode=args.llm_mode,
    ))


if __name__ == "__main__":
    main()
