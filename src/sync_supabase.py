"""Synchronize local dataset files directly to Supabase PostgreSQL tables.

Usage:
    python src/sync_supabase.py
"""

import asyncio
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.supabase_client import get_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_supabase")


def load_jsonl_for_user(file_paths: list, user_id: str) -> list:
    """Load records from the first existing file among priority list for a specific user."""
    for p in file_paths:
        path = PROJECT_ROOT / p.replace("{user_id}", user_id)
        if path.exists():
            records = []
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line))
                if records:
                    return records
            except Exception:
                pass
    return []


import uuid

def sanitize_uuid(user_id: str) -> str:
    """Ensure user_id is a valid Postgres UUID, falling back to nil UUID if invalid/demo."""
    if not user_id:
        return "00000000-0000-0000-0000-000000000000"
    try:
        return str(uuid.UUID(user_id))
    except (ValueError, AttributeError, TypeError):
        return "00000000-0000-0000-0000-000000000000"


async def sync_all_tables(user_id: str = "anonymous_demo"):
    load_dotenv()
    client = get_supabase_client()
    db_user_id = sanitize_uuid(user_id)

    print("\n" + "=" * 75)
    print(f"🚀 SUPABASE POSTGRESQL DIRECT SYNC UTILITY (User: {user_id} -> DB UUID: {db_user_id})")
    print("-" * 75)
    print(f"Supabase Endpoint: {client.supabase_url or 'NOT CONFIGURED'}")
    print(f"Client Configured: {client.is_configured}")
    print("-" * 75)

    if not client.is_configured:
        print("❌ [Supabase] Missing valid SUPABASE_URL or SUPABASE_SECRET_KEY in .env!")
        return

    # 1. Startups
    startup_raw = load_jsonl_for_user([
        "data/resolved/{user_id}/startups.jsonl",
        "data/structured/{user_id}/startups.jsonl",
        "data/raw/{user_id}/startups.jsonl"
    ], user_id)
    startup_records = []
    seen_startups = set()
    for s in startup_raw:
        url = s.get("source", {}).get("url", "")
        if url in seen_startups:
            continue
        if url:
            seen_startups.add(url)
        startup_records.append({
            "user_id": db_user_id,
            "schema_version": s.get("schemaVersion", "1.0"),
            "record_type": s.get("recordType", "STARTUP"),
            "source_name": s.get("source", {}).get("name", "Seed Startup Registry"),
            "source_url": url,
            "entity_name": s.get("content", {}).get("entityName", "Startup"),
            "employee_count": s.get("content", {}).get("data", {}).get("employeeCount"),
            "collected_at": s.get("collectedAt") or datetime.now(timezone.utc).isoformat(),
        })

    if startup_records:
        n = await client.upsert_records("startups", startup_records, conflict_columns="source_url")
        icon = "✅" if n > 0 else "ℹ️"
        print(f"{icon} Startups Synced: {len(startup_records)} unique records -> {n} rows written to table 'startups'")
    else:
        print("⚠️ No startup records found for this user.")

    # 2. Products
    product_raw = load_jsonl_for_user([
        "data/resolved/{user_id}/products.jsonl",
        "data/structured/{user_id}/products.jsonl",
        "data/raw/{user_id}/products.jsonl"
    ], user_id)
    product_records = []
    seen_products = set()
    for p in product_raw:
        url = p.get("source", {}).get("url", "")
        if url in seen_products:
            continue
        if url:
            seen_products.add(url)
        product_records.append({
            "user_id": db_user_id,
            "schema_version": p.get("schemaVersion", "1.0"),
            "record_type": p.get("recordType", "PRODUCT"),
            "source_name": p.get("source", {}).get("name", "Hugging Face Spaces Hub"),
            "source_url": url,
            "startup_name": p.get("content", {}).get("startupName", "Company"),
            "pricing_model": p.get("content", {}).get("pricingModel", "FREE"),
            "collected_at": p.get("collectedAt") or datetime.now(timezone.utc).isoformat(),
        })

    if product_records:
        n = await client.upsert_records("products", product_records, conflict_columns="source_url")
        icon = "✅" if n > 0 else "ℹ️"
        print(f"{icon} Products Synced: {len(product_records)} unique records -> {n} rows written to table 'products'")
    else:
        print("⚠️ No product records found for this user.")

    # 3. Research Papers
    paper_raw = load_jsonl_for_user([
        "data/structured/{user_id}/papers.jsonl",
        "data/raw/{user_id}/papers.jsonl"
    ], user_id)
    paper_records = []
    seen_papers = set()
    for pap in paper_raw:
        p_url = pap.get("content", {}).get("paper_url", "")
        if p_url in seen_papers:
            continue
        if p_url:
            seen_papers.add(p_url)
        paper_records.append({
            "user_id": db_user_id,
            "schema_version": pap.get("schemaVersion", "1.0"),
            "record_type": pap.get("recordType", "RESEARCH_PAPER"),
            "title": pap.get("content", {}).get("title", ""),
            "authors": pap.get("content", {}).get("authors", []),
            "paper_url": p_url,
            "github_url": pap.get("content", {}).get("github_url"),
            "github_stars": pap.get("content", {}).get("github_stars"),
            "published_date": pap.get("content", {}).get("published_date") or datetime.now(timezone.utc).isoformat(),
            "collected_at": pap.get("collectedAt") or datetime.now(timezone.utc).isoformat(),
        })

    if paper_records:
        n = await client.upsert_records("research_papers", paper_records, conflict_columns="paper_url")
        icon = "✅" if n > 0 else "ℹ️"
        print(f"{icon} Research Papers Synced: {len(paper_records)} unique records -> {n} rows written to table 'research_papers'")
    else:
        print("⚠️ No paper records found for this user.")

    # 4. Jobs
    job_raw = load_jsonl_for_user([
        "data/structured/{user_id}/jobs.jsonl",
        "data/raw/{user_id}/jobs.jsonl"
    ], user_id)
    job_records = []
    seen_jobs = set()
    for idx, j in enumerate(job_raw):
        content = j.get("content", {})
        company = (content.get("company") or "").strip()
        role = content.get("role_family", "Engineering")
        title = (content.get("title") or f"{company} {role} Specialist" if company else f"AI Position #{idx+1}").strip()
        url = (
            content.get("source_url")
            or j.get("source", {}).get("url")
            or f"https://jobs.ai/post/{idx+1}_{abs(hash(company + title))}"
        ).strip()
        date_val = content.get("date") or j.get("collectedAt") or datetime.now(timezone.utc).isoformat()
        
        job_key = f"{company}_{title}_{url}_{date_val}"
        if not company or job_key in seen_jobs:
            continue
        seen_jobs.add(job_key)

        job_records.append({
            "user_id": db_user_id,
            "schema_version": j.get("schemaVersion", "1.0"),
            "record_type": j.get("recordType", "JOB"),
            "company": company,
            "title": title,
            "source_name": content.get("source_name") or j.get("source", {}).get("name", "Jobs Feed"),
            "source_url": url,
            "date": date_val,
            "is_remote": content.get("is_remote", True),
            "role_family": role,
            "collected_at": j.get("collectedAt") or datetime.now(timezone.utc).isoformat(),
        })

    if job_records:
        n = await client.upsert_records("jobs", job_records, conflict_columns="company,title,source_url,date")
        icon = "✅" if n > 0 else "ℹ️"
        print(f"{icon} Jobs Synced: {len(job_records)} unique records -> {n} rows written to table 'jobs'")
    else:
        print("⚠️ No job records found for this user.")

    # 5. News
    news_raw = load_jsonl_for_user([
        "data/structured/{user_id}/news.jsonl",
        "data/raw/{user_id}/news.jsonl"
    ], user_id)
    news_records = []
    seen_news = set()
    for nw in news_raw:
        url = nw.get("source", {}).get("url", "")
        if url in seen_news:
            continue
        if url:
            seen_news.add(url)
        news_records.append({
            "user_id": db_user_id,
            "schema_version": nw.get("schemaVersion", "1.0"),
            "record_type": nw.get("recordType", "NEWS"),
            "source_name": nw.get("source", {}).get("name", "Publisher"),
            "source_url": url,
            "title": nw.get("content", {}).get("title", ""),
            "published_date": nw.get("content", {}).get("published_date") or datetime.now(timezone.utc).isoformat(),
            "content": nw.get("content", {}).get("summary") or nw.get("content", {}).get("raw_content", ""),
            "collected_at": nw.get("collectedAt") or datetime.now(timezone.utc).isoformat(),
        })

    if news_records:
        n = await client.upsert_records("news", news_records, conflict_columns="source_url")
        icon = "✅" if n > 0 else "ℹ️"
        print(f"{icon} News Synced: {len(news_records)} unique records -> {n} rows written to table 'news'")
    else:
        print("⚠️ No news records found for this user.")

    # 6. Entity Mapping Log
    mapping_path = PROJECT_ROOT / "data/output" / user_id / "entity_mapping_log.csv"
    mapping_records = []
    seen_mappings = set()
    if mapping_path.exists():
        with open(mapping_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_name = (row.get("raw_name") or "").strip()
                entity_type = (row.get("entity_type") or "STARTUP").strip()
                if not raw_name:
                    continue

                m_key = f"{raw_name}_{entity_type}"
                if m_key in seen_mappings:
                    continue
                seen_mappings.add(m_key)

                try:
                    score = float(row.get("match_score", 0.0))
                except Exception:
                    score = 0.0

                method_val = (row.get("method") or "").strip()
                if not method_val or method_val.lower() in ("none", "null"):
                    method_val = "new_entity" if score == 0.0 else "seed_match"

                mapping_records.append({
                    "user_id": db_user_id,
                    "raw_name": raw_name,
                    "canonical_name": (row.get("canonical_name") or raw_name).strip(),
                    "match_score": score,
                    "method": method_val,
                    "entity_type": entity_type,
                    "source_url": (row.get("source_url") or "").strip(),
                })

    if mapping_records:
        n = await client.upsert_records("entity_mapping_log", mapping_records, conflict_columns="raw_name,entity_type")
        icon = "✅" if n > 0 else "ℹ️"
        print(f"{icon} Entity Mappings Synced: {len(mapping_records)} unique records -> {n} rows written to table 'entity_mapping_log'")
    else:
        print("⚠️ No entity mapping records found for this user.")

    sync_results = {
        "startups": len(startup_records),
        "products": len(product_records),
        "research_papers": len(paper_records),
        "jobs": len(job_records),
        "news": len(news_records),
        "entity_mapping_log": len(mapping_records),
        "total_unique_records": len(startup_records) + len(product_records) + len(paper_records) + len(job_records) + len(news_records),
    }

    return sync_results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=str, default="anonymous_demo")
    args = parser.parse_args()
    asyncio.run(sync_all_tables(args.user_id))
