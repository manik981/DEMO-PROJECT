"""CLI Pipeline for Phase IV Deterministic Entity Resolution.

Reads structured (or raw) Startup and Product records, applies deterministic
canonicalization to entityName and startupName fields, and persists:
- Finalized resolved records in data/resolved/{startups,products}.jsonl
- Entity Mapping Audit Log in data/output/entity_mapping_log.csv
- Manual Review Log in data/output/manual_review_entities.csv

Usage:
    python src/resolve.py
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.resolver.entity_resolver import EntityResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("entity_resolution_pipeline")


def resolve_startups(
    resolver: EntityResolver,
    input_dir: Path,
    resolved_dir: Path,
) -> dict:
    """Resolve startup entity names to canonical names."""
    # Check structured first, fallback to user's raw directory
    in_file = input_dir / "startups.jsonl"
    if not in_file.exists():
        raw_fallback = input_dir.parent.parent / "raw" / input_dir.name / "startups.jsonl"
        if raw_fallback.exists():
            in_file = raw_fallback
        else:
            in_file = Path("data/raw/startups.jsonl")

    out_file = resolved_dir / "startups.jsonl"
    stats = {"processed": 0, "canonicalized": 0}

    if not in_file.exists():
        logger.warning("Startups input file not found: %s", in_file)
        return stats

    # Load existing resolved records to preserve historical data
    seen_urls = set()
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f_ex:
                for l in f_ex:
                    if l.strip():
                        try:
                            rec = json.loads(l)
                            url = rec.get("source", {}).get("url", "")
                            if url:
                                seen_urls.add(url)
                        except Exception:
                            pass
        except Exception:
            pass

    with open(in_file, "r", encoding="utf-8") as f_in, open(out_file, "a", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue

            raw_name = record.get("content", {}).get("entityName", "")
            source_url = record.get("source", {}).get("url", "")

            if source_url and source_url in seen_urls:
                continue
            if source_url:
                seen_urls.add(source_url)

            if raw_name:
                res = resolver.resolve(raw_name, source_url=source_url, entity_type="STARTUP")
                # Apply canonical name to record
                record["content"]["entityName"] = res.canonical_name
                stats["canonicalized"] += 1

            f_out.write(json.dumps(record) + "\n")
            stats["processed"] += 1

    return stats


def resolve_products(
    resolver: EntityResolver,
    input_dir: Path,
    resolved_dir: Path,
) -> dict:
    """Resolve product startup names to canonical names."""
    in_file = input_dir / "products.jsonl"
    if not in_file.exists():
        raw_fallback = input_dir.parent.parent / "raw" / input_dir.name / "products.jsonl"
        if raw_fallback.exists():
            in_file = raw_fallback
        else:
            in_file = Path("data/raw/products.jsonl")

    out_file = resolved_dir / "products.jsonl"
    stats = {"processed": 0, "canonicalized": 0}

    if not in_file.exists():
        logger.warning("Products input file not found: %s", in_file)
        return stats

    seen_urls = set()
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f_ex:
                for l in f_ex:
                    if l.strip():
                        try:
                            rec = json.loads(l)
                            url = rec.get("source", {}).get("url", "")
                            if url:
                                seen_urls.add(url)
                        except Exception:
                            pass
        except Exception:
            pass

    with open(in_file, "r", encoding="utf-8") as f_in, open(out_file, "a", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue

            raw_startup = record.get("content", {}).get("startupName", "")
            source_url = record.get("source", {}).get("url", "")

            if source_url and source_url in seen_urls:
                continue
            if source_url:
                seen_urls.add(source_url)

            if raw_startup:
                res = resolver.resolve(raw_startup, source_url=source_url, entity_type="PRODUCT")
                record["content"]["startupName"] = res.canonical_name
                stats["canonicalized"] += 1

            f_out.write(json.dumps(record) + "\n")
            stats["processed"] += 1

    return stats


def print_resolution_summary(resolver: EntityResolver, startup_stats: dict, product_stats: dict) -> None:
    """Print resolution metrics and method distribution."""
    methods_count: dict = {}
    for res in resolver.logged_resolutions.values():
        methods_count[res.method] = methods_count.get(res.method, 0) + 1

    print("\n" + "=" * 80)
    print("PHASE IV — DETERMINISTIC ENTITY RESOLUTION SUMMARY")
    print("-" * 80)
    print(f"Startups Processed:       {startup_stats['processed']}")
    print(f"Products Processed:       {product_stats['processed']}")
    print(f"Total Unique Entities:    {len(resolver.logged_resolutions)}")
    print("-" * 80)
    print("MATCHING METHOD BREAKDOWN:")
    for method, count in sorted(methods_count.items()):
        print(f"  • {method:<22}: {count}")
    print("-" * 80)
    print(f"Output Mapping Log:       data/output/entity_mapping_log.csv")
    print(f"Manual Review Log:        data/output/manual_review_entities.csv")
    print("=" * 80 + "\n")


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Phase IV Deterministic Entity Resolution")
    parser.add_argument(
        "--input-dir",
        type=str,
        default="data/structured",
        help="Input structured records directory (default: data/structured)",
    )
    parser.add_argument(
        "--resolved-dir",
        type=str,
        default="data/resolved",
        help="Output resolved records directory (default: data/resolved)",
    )
    parser.add_argument(
        "--seed-path",
        type=str,
        default="data/seed/canonical_startups.json",
        help="Seed canonical JSON catalog (default: data/seed/canonical_startups.json)",
    )

    args = parser.parse_args()
    input_dir = Path(args.input_dir)
    resolved_dir = Path(args.resolved_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)
    Path("data/output").mkdir(parents=True, exist_ok=True)

    resolver = EntityResolver(seed_path=args.seed_path)

    startup_stats = resolve_startups(resolver, input_dir, resolved_dir)
    product_stats = resolve_products(resolver, input_dir, resolved_dir)

    print_resolution_summary(resolver, startup_stats, product_stats)


if __name__ == "__main__":
    main()
