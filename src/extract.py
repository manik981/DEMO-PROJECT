"""CLI Entrypoint for AI Data-Intelligence Extraction Pipelines.

Supports:
- Bulk Verticals (Phase I): Research Papers, Startups, Products (Target 1,000+ each)
- High-Fidelity Fresh Verticals (Phase II): 24h Fresh AI News & Jobs with Multi-Tier Date Auditing

Usage:
    python src/extract.py --vertical papers --limit 1000
    python src/extract.py --vertical startups --limit 1000
    python src/extract.py --vertical products --limit 1000
    python src/extract.py --vertical news --freshness-hours 24
    python src/extract.py --vertical jobs --freshness-hours 24
    python src/extract.py --all
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scrapers.jobs import JobsScraper
from src.scrapers.news import NewsScraper
from src.scrapers.papers import PapersScraper
from src.scrapers.products import ProductsScraper
from src.scrapers.startups import StartupsScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline_extractor")


async def run_papers_extraction(limit: int, output_dir: Path) -> dict:
    """Run research papers ingestion from Crossref REST API and GitHub."""
    logger.info("=== Starting Research Papers Ingestion (Target: %d) ===", limit)
    out_file = output_dir / "papers.jsonl"
    scraper = PapersScraper(raw_output_path=str(out_file))
    await scraper.harvest_bulk(target_count=limit)
    return scraper.stats


async def run_startups_extraction(limit: int, concurrency: int, output_dir: Path) -> dict:
    """Run startups ingestion from directories."""
    logger.info("=== Starting Startups Ingestion (Target: %d) ===", limit)
    out_file = output_dir / "startups.jsonl"
    scraper = StartupsScraper(concurrency=concurrency, raw_output_path=str(out_file))
    await scraper.harvest_bulk(target_count=limit)
    return scraper.stats


async def run_products_extraction(limit: int, concurrency: int, output_dir: Path) -> dict:
    """Run products ingestion from AI catalogs."""
    logger.info("=== Starting Products Ingestion (Target: %d) ===", limit)
    out_file = output_dir / "products.jsonl"
    scraper = ProductsScraper(concurrency=concurrency, raw_output_path=str(out_file))
    await scraper.harvest_bulk(target_count=limit)
    return scraper.stats


async def run_news_extraction(freshness_hours: float, output_dir: Path) -> dict:
    """Run news ingestion with 24-hour freshness audit."""
    logger.info("=== Starting News Ingestion (Freshness Window: %.1fh) ===", freshness_hours)
    out_file = output_dir / "news.jsonl"
    scraper = NewsScraper(freshness_hours=freshness_hours, raw_output_path=str(out_file))
    records = await scraper.harvest_fresh_news()
    return {"emitted": len(records), "duplicates_skipped": scraper.stats.get("duplicates_skipped", 0), "audit": scraper.audit_stats}


async def run_jobs_extraction(limit: int, freshness_hours: float, output_dir: Path) -> dict:
    """Run jobs ingestion with 24-hour freshness audit and role classification."""
    logger.info("=== Starting Jobs Ingestion (Target: %d, Freshness Window: %.1fh) ===", limit, freshness_hours)
    out_file = output_dir / "jobs.jsonl"
    scraper = JobsScraper(freshness_hours=freshness_hours, raw_output_path=str(out_file))
    records = await scraper.harvest_fresh_jobs(target_count=limit)
    return {"emitted": len(records), "duplicates_skipped": scraper.stats.get("duplicates_skipped", 0), "audit": scraper.audit_stats}


def print_summary_table(bulk_results: dict, freshness_results: dict, output_dir: Path) -> None:
    """Print clean summary metrics table to console."""
    if bulk_results:
        print("\n" + "=" * 80)
        print("BULK VERTICALS ACQUISITION METRICS (Phase I)")
        print("-" * 80)
        print(f"{'VERTICAL':<16} | {'EMITTED':<8} | {'DUPLICATES':<10} | {'REQUESTS':<9} | {'FAILURES':<8} | {'OUTPUT FILE'}")
        print("-" * 80)
        for vertical, stats in bulk_results.items():
            emitted = stats.get("papers_emitted") or stats.get("startups_emitted") or stats.get("products_emitted") or 0
            dups = stats.get("duplicates_skipped", 0)
            reqs = stats.get("requests_made", 0)
            fails = stats.get("failures", 0)
            filename = f"{vertical}.jsonl"
            print(f"{vertical.capitalize():<16} | {emitted:<8} | {dups:<10} | {reqs:<9} | {fails:<8} | {output_dir / filename}")
        print("=" * 80)

    if freshness_results:
        print("\n" + "=" * 80)
        print("FRESHNESS AUDIT METRICS — 24-HOUR WINDOW (Phase II)")
        print("-" * 80)
        print(f"{'SOURCE / PUBLISHER':<28} | {'PARSED':<7} | {'FRESH (<=24h)':<13} | {'STALE (>24h)':<12} | {'HEURISTIC'}")
        print("-" * 80)
        for vertical, data in freshness_results.items():
            print(f"\n--- {vertical.upper()} SOURCES ---")
            audit_dict = data.get("audit", {})
            for source_name, metrics in audit_dict.items():
                parsed = metrics.get("candidates_parsed", 0)
                fresh = metrics.get("fresh_records", 0)
                stale = metrics.get("stale_records", 0)
                heur = metrics.get("heuristic_dates", 0)
                print(f"{source_name:<28} | {parsed:<7} | {fresh:<13} | {stale:<12} | {heur}")
        print("=" * 80 + "\n")


async def main_async():
    load_dotenv()
    parser = argparse.ArgumentParser(description="AI Data-Intelligence Ingestion Pipeline")
    parser.add_argument(
        "--vertical",
        "-v",
        choices=["papers", "startups", "products", "news", "jobs", "all"],
        default="all",
        help="Vertical to run (default: all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 5 verticals",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=1000,
        help="Target number of records for bulk verticals (default: 1000)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=10,
        help="Concurrency for async workers (default: 10)",
    )
    parser.add_argument(
        "--freshness-hours",
        "-f",
        type=float,
        default=24.0,
        help="Maximum age in hours for fresh news and jobs (default: 24.0)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default="data/raw",
        help="Directory to save raw JSONL files (default: data/raw)",
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    vertical = "all" if args.all else args.vertical
    bulk_results = {}
    freshness_results = {}

    # Bulk Verticals
    if vertical in ("papers", "all"):
        bulk_results["papers"] = await run_papers_extraction(args.limit, output_dir)

    if vertical in ("startups", "all"):
        bulk_results["startups"] = await run_startups_extraction(args.limit, args.concurrency, output_dir)

    if vertical in ("products", "all"):
        bulk_results["products"] = await run_products_extraction(args.limit, args.concurrency, output_dir)

    # Fresh Verticals
    if vertical in ("news", "all"):
        freshness_results["news"] = await run_news_extraction(args.freshness_hours, output_dir)

    if vertical in ("jobs", "all"):
        freshness_results["jobs"] = await run_jobs_extraction(args.limit, args.freshness_hours, output_dir)

    print_summary_table(bulk_results, freshness_results, output_dir)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
