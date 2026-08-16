"""Data cleanup utility."""
import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.supabase_client import get_supabase_client
from src.export.sheets import GoogleSheetsExporter

TAB_MAP = {
    "startups": "Startups",
    "products": "Products",
    "papers": "Research Papers",
    "jobs": "Jobs",
    "news": "News",
    "mappings": "Entity Mapping Log",
    "quarantine": None
}

TABLE_MAP = {
    "startups": "startups",
    "products": "products",
    "papers": "research_papers",
    "jobs": "jobs",
    "news": "news",
    "mappings": "entity_mapping_log",
    "quarantine": None
}

def sanitize_uuid(val: Optional[str]) -> str:
    if not val:
        return "00000000-0000-0000-0000-000000000000"
    try:
        uuid_obj = uuid.UUID(str(val))
        return str(uuid_obj)
    except ValueError:
        return "00000000-0000-0000-0000-000000000000"

async def clean_vertical(vertical: str, user_id: str):
    load_dotenv()
    
    if not user_id:
        user_id = "anonymous_demo"

    db_user_id = sanitize_uuid(user_id)
    print(f"Cleaning data for vertical: {vertical} (User: {user_id}, DB UUID: {db_user_id})")
    
    # Special handler for Pipeline Runs Observability / History
    if vertical == "runs":
        telemetry_dir = PROJECT_ROOT / "data" / "telemetry"
        runs_jsonl = telemetry_dir / "runs.jsonl"
        if runs_jsonl.exists():
            try:
                lines_to_keep = []
                with open(runs_jsonl, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            try:
                                r_data = json.loads(line)
                                if r_data.get("user_id") and r_data.get("user_id") != user_id:
                                    lines_to_keep.append(line)
                            except Exception:
                                pass
                with open(runs_jsonl, "w", encoding="utf-8") as f:
                    if lines_to_keep:
                        f.writelines(lines_to_keep)
                    else:
                        f.write("")
                print(f"✅ Cleared telemetry run logs for user '{user_id}' in data/telemetry/runs.jsonl")
            except Exception as e:
                print(f"Error clearing runs.jsonl: {e}")

        if telemetry_dir.exists():
            for f in telemetry_dir.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as rf:
                        data = json.load(rf)
                        if data.get("user_id") == user_id or user_id in f.name:
                            rf.close()
                            f.unlink()
                except Exception:
                    pass
        return

    # 1. Clean local files (Isolated by user)
    if vertical == "mappings":
        paths = [
            PROJECT_ROOT / "data/output" / user_id / "entity_mapping_log.csv",
            PROJECT_ROOT / "data/output/entity_mapping_log.csv",
        ]
        for p in paths:
            if p.exists():
                try:
                    p.unlink()
                    print(f"✅ Deleted local file: {p.relative_to(PROJECT_ROOT)}")
                except Exception as e:
                    print(f"Error unlinking {p}: {e}")
    else:
        dirs = ["raw", "structured", "resolved", "quarantine"]
        for d in dirs:
            paths = [PROJECT_ROOT / f"data/{d}/{user_id}/{vertical}.jsonl"]
            if user_id == "anonymous_demo":
                paths.append(PROJECT_ROOT / f"data/{d}/{vertical}.jsonl")
            for p in paths:
                if p.exists():
                    try:
                        p.unlink()
                        print(f"✅ Deleted local file: {p.relative_to(PROJECT_ROOT)}")
                    except Exception as e:
                        print(f"Error unlinking {p}: {e}")

    # 2. Clean Supabase (Isolated by user)
    client = get_supabase_client()
    table_name = TABLE_MAP.get(vertical)
    if client.is_configured and table_name:
        try:
            # Only delete rows belonging to this user
            await client.delete_user_records(table_name, db_user_id)
            print(f"✅ Cleared user's data from Supabase table '{table_name}'.")
        except Exception as e:
            print(f"⚠️ Supabase delete error: {e}")

    # 3. Clean Google Sheets
    try:
        exporter = GoogleSheetsExporter(user_id=user_id)
        if exporter.authenticate() and exporter.spreadsheet_id:
            spreadsheet = exporter.client.open_by_key(exporter.spreadsheet_id)
            tab_name = TAB_MAP.get(vertical)
            if tab_name:
                try:
                    worksheet = spreadsheet.worksheet(tab_name)
                    rows = exporter.load_rows_for_tab(tab_name)
                    worksheet.clear()
                    try:
                        worksheet.update(values=rows, range_name="A1")
                    except Exception:
                        try:
                            worksheet.update("A1", rows)
                        except Exception:
                            worksheet.update(rows)
                    print(f"✅ Cleared user data from Google Sheets tab '{tab_name}'.")
                except Exception as e:
                    print(f"⚠️ Could not clear Google Sheets tab '{tab_name}': {e}")
    except Exception as e:
        print(f"⚠️ Google Sheets connection error during clean: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vertical", type=str, required=True)
    parser.add_argument("--user-id", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(clean_vertical(args.vertical, args.user_id))
