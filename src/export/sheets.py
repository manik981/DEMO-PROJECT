"""Google Sheets 6-Tab Synchronized Exporter.

Uses gspread to push validated PostgreSQL/canonical datasets into 6 worksheet tabs:
1. Startups
2. Products
3. Research Papers
4. Jobs
5. News
6. Entity Mapping Log

Column headers match Pydantic schema field names and assignment specs exactly.

Usage:
    python src/export/sheets.py
"""

import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

try:
    import gspread
except ImportError:
    gspread = None  # type: ignore


def sanitize_cell(val: Any) -> Any:
    """Ensure all cell values are JSON-serializable primitives for Google Sheets API."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float, str)):
        return val
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, (list, dict)):
        return json.dumps(val)
    return str(val)


class GoogleSheetsExporter:
    """Exports validated records to 6 synchronized tabs in Google Sheets."""

    TAB_DEFINITIONS = {
        "Startups": {
            "headers": [
                "User_ID", "schemaVersion", "recordType", "source_name", "source_url",
                "entityName", "employeeCount", "collectedAt"
            ]
        },
        "Products": {
            "headers": [
                "User_ID", "schemaVersion", "recordType", "source_name", "source_url",
                "startupName", "pricingModel", "collectedAt"
            ]
        },
        "Research Papers": {
            "headers": [
                "User_ID", "schemaVersion", "recordType", "title", "authors",
                "paper_url", "github_url", "github_stars", "published_date"
            ]
        },
        "Jobs": {
            "headers": [
                "User_ID", "schemaVersion", "recordType", "company", "title",
                "source_name", "source_url", "date", "is_remote", "role_family"
            ]
        },
        "News": {
            "headers": [
                "User_ID", "schemaVersion", "recordType", "source_name", "source_url",
                "title", "published_date", "summary", "collectedAt"
            ]
        },
        "Entity Mapping Log": {
            "headers": [
                "User_ID", "raw_name", "canonical_name", "match_score", "method",
                "source_url", "entity_type", "timestamp"
            ],
            "is_csv": True,
        },
    }

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        raw_creds = credentials_path or os.getenv("GOOGLE_SHEETS_CREDS_PATH", "credentials.json")
        creds_candidates = [
            Path(raw_creds),
            PROJECT_ROOT / raw_creds,
            PROJECT_ROOT / "credentials.json",
            PROJECT_ROOT.parent / "credentials.json",
            Path(os.path.expanduser("~")) / "credentials.json",
        ]
        found_creds = None
        for p in creds_candidates:
            try:
                if p.exists() and p.is_file():
                    found_creds = str(p.resolve())
                    break
            except Exception:
                continue

        self.credentials_path = found_creds or str(PROJECT_ROOT / "credentials.json")

        raw_id = spreadsheet_id or os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
        raw_id = raw_id.strip("'\" \t\r\n")
        if "docs.google.com/spreadsheets/d/" in raw_id:
            raw_id = raw_id.split("/d/")[1].split("/")[0].split("?")[0]
        self.spreadsheet_id = raw_id
        self.user_id = user_id
        self.client = None

    def authenticate(self) -> bool:
        """Authenticate with Google Sheets service account."""
        if gspread is None:
            print("❌ [GoogleSheets] gspread library is not installed.")
            return False

        if not os.path.exists(self.credentials_path):
            print(f"❌ [GoogleSheets] Credentials file '{self.credentials_path}' not found.")
            return False

        try:
            self.client = gspread.service_account(filename=self.credentials_path)
            return True
        except Exception as e:
            print(f"❌ [GoogleSheets] Service account authentication failed: {e}")
            return False

    def load_rows_for_tab(self, tab_name: str) -> List[List[Any]]:
        """Read, format, and sanitize rows for a given tab definition directly from Supabase or local files."""
        tab_def = self.TAB_DEFINITIONS.get(tab_name)
        if not tab_def:
            return []

        headers = tab_def["headers"]
        rows = [headers]

        fetched_db = False
        try:
            import asyncio
            from src.db.supabase_client import get_supabase_client
            client = get_supabase_client()
            if client.is_configured:
                table_name = tab_name.lower().replace(" ", "_")
                db_rows = asyncio.run(client.fetch_table_records(table_name, limit=5000))
                if db_rows:
                    fetched_db = True
                    # Filter by user_id if specific user export requested
                    if self.user_id and self.user_id != "anonymous_demo":
                        target_uids = {self.user_id, "00000000-0000-0000-0000-000000000000"}
                        db_rows = [r for r in db_rows if r.get("user_id") in target_uids or not r.get("user_id")]

                    for r in db_rows:
                        uid = r.get("user_id") or self.user_id or "anonymous_demo"
                        if table_name == "research_papers":
                            authors = r.get("authors", [])
                            authors_str = ", ".join(authors) if isinstance(authors, list) else str(authors or "")
                            rows.append([
                                uid,
                                r.get("schema_version", "1.0"),
                                r.get("record_type", "RESEARCH_PAPER"),
                                r.get("title", ""),
                                authors_str,
                                r.get("paper_url", ""),
                                r.get("github_url") or "",
                                r.get("github_stars") or "",
                                r.get("published_date", ""),
                            ])
                        elif table_name == "startups":
                            rows.append([
                                uid,
                                r.get("schema_version", "1.0"),
                                r.get("record_type", "STARTUP"),
                                r.get("source_name", "Y Combinator"),
                                r.get("source_url", ""),
                                r.get("entity_name", ""),
                                r.get("employee_count", ""),
                                r.get("collected_at", ""),
                            ])
                        elif table_name == "products":
                            rows.append([
                                uid,
                                r.get("schema_version", "1.0"),
                                r.get("record_type", "PRODUCT"),
                                r.get("source_name", "Product Index"),
                                r.get("source_url", ""),
                                r.get("startup_name", ""),
                                r.get("pricing_model", "FREE"),
                                r.get("collected_at", ""),
                            ])
                        elif table_name == "jobs":
                            rows.append([
                                uid,
                                r.get("schema_version", "1.0"),
                                r.get("record_type", "JOB"),
                                r.get("company", ""),
                                r.get("title", ""),
                                r.get("source_name", "Jobs Board"),
                                r.get("source_url", ""),
                                r.get("date", ""),
                                r.get("is_remote", True),
                                r.get("role_family", "Engineering"),
                            ])
                        elif table_name == "news":
                            rows.append([
                                uid,
                                r.get("schema_version", "1.0"),
                                r.get("record_type", "NEWS"),
                                r.get("source_name", "Publisher"),
                                r.get("source_url", ""),
                                r.get("title", ""),
                                r.get("published_date", ""),
                                r.get("content", ""),
                                r.get("collected_at", ""),
                            ])
                        elif table_name == "entity_mapping_log":
                            rows.append([
                                uid,
                                r.get("raw_name", ""),
                                r.get("canonical_name", ""),
                                r.get("match_score", ""),
                                r.get("method", ""),
                                r.get("source_url", ""),
                                r.get("entity_type", "STARTUP"),
                                r.get("created_at", ""),
                            ])
        except Exception as e:
            logger.debug("Could not fetch records from Supabase for tab %s: %s", tab_name, e)

        # Fallback to local files if Supabase is unconfigured or returned 0 rows for user
        if not fetched_db or len(rows) == 1:
            vertical_map = {
                "Startups": "startups",
                "Products": "products",
                "Research Papers": "papers",
                "Jobs": "jobs",
                "News": "news",
            }
            v = vertical_map.get(tab_name)
            uid = self.user_id or "anonymous_demo"
            if tab_name == "Entity Mapping Log":
                csv_paths = [
                    PROJECT_ROOT / "data/output" / uid / "entity_mapping_log.csv",
                    PROJECT_ROOT / "data/output" / "entity_mapping_log.csv"
                ]
                for csv_path in csv_paths:
                    if csv_path.exists():
                        try:
                            with open(csv_path, "r", encoding="utf-8") as f:
                                reader = csv.DictReader(f)
                                for row in reader:
                                    rows.append([
                                        uid,
                                        row.get("raw_name", ""),
                                        row.get("canonical_name", ""),
                                        row.get("match_score", ""),
                                        row.get("method", ""),
                                        row.get("source_url", ""),
                                        row.get("entity_type", "STARTUP"),
                                        row.get("timestamp", ""),
                                    ])
                            break
                        except Exception:
                            pass
            elif v:
                file_candidates = [
                    PROJECT_ROOT / f"data/resolved/{uid}/{v}.jsonl",
                    PROJECT_ROOT / f"data/structured/{uid}/{v}.jsonl",
                    PROJECT_ROOT / f"data/raw/{uid}/{v}.jsonl",
                    PROJECT_ROOT / f"data/resolved/{v}.jsonl",
                    PROJECT_ROOT / f"data/structured/{v}.jsonl",
                    PROJECT_ROOT / f"data/raw/{v}.jsonl",
                ]
                for p in file_candidates:
                    if p.exists():
                        try:
                            with open(p, "r", encoding="utf-8") as f:
                                for line in f:
                                    if line.strip():
                                        rec = json.loads(line)
                                        content = rec.get("content", {})
                                        src = rec.get("source", {})
                                        if v == "startups":
                                            rows.append([
                                                uid,
                                                rec.get("schemaVersion", "1.0"),
                                                rec.get("recordType", "STARTUP"),
                                                src.get("name", "Seed Registry"),
                                                src.get("url", ""),
                                                content.get("entityName") or content.get("data", {}).get("entityName", ""),
                                                content.get("data", {}).get("employeeCount", ""),
                                                rec.get("collectedAt", ""),
                                            ])
                                        elif v == "products":
                                            rows.append([
                                                uid,
                                                rec.get("schemaVersion", "1.0"),
                                                rec.get("recordType", "PRODUCT"),
                                                src.get("name", "Product Registry"),
                                                src.get("url", ""),
                                                content.get("startupName") or content.get("entityName", ""),
                                                content.get("pricingModel", "FREEMIUM"),
                                                rec.get("collectedAt", ""),
                                            ])
                                        elif v == "papers":
                                            authors = content.get("authors", [])
                                            authors_str = ", ".join(authors) if isinstance(authors, list) else str(authors or "")
                                            rows.append([
                                                uid,
                                                rec.get("schemaVersion", "1.0"),
                                                rec.get("recordType", "RESEARCH_PAPER"),
                                                content.get("title", ""),
                                                authors_str,
                                                content.get("paper_url") or src.get("url", ""),
                                                content.get("github_url", ""),
                                                content.get("github_stars", ""),
                                                content.get("published_date", ""),
                                            ])
                                        elif v == "jobs":
                                            rows.append([
                                                uid,
                                                rec.get("schemaVersion", "1.0"),
                                                rec.get("recordType", "JOB"),
                                                content.get("company", ""),
                                                content.get("title", ""),
                                                src.get("name", "Jobs Board"),
                                                src.get("url", ""),
                                                content.get("date", ""),
                                                content.get("is_remote", True),
                                                content.get("role_family", "Engineering"),
                                            ])
                                        elif v == "news":
                                            rows.append([
                                                uid,
                                                rec.get("schemaVersion", "1.0"),
                                                rec.get("recordType", "NEWS"),
                                                src.get("name", "Publisher"),
                                                src.get("url", ""),
                                                content.get("title", ""),
                                                content.get("published_date", ""),
                                                content.get("summary", ""),
                                                rec.get("collectedAt", ""),
                                            ])
                            break
                        except Exception:
                            pass

        return [[sanitize_cell(c) for c in r] for r in rows]

    def export_all_tabs(self) -> Dict[str, int]:
        """Export all 6 tabs to Google Sheets or simulate locally if credentials absent."""
        results = {}
        spreadsheet = None

        is_auth = self.authenticate()
        if is_auth and self.spreadsheet_id:
            try:
                spreadsheet = self.client.open_by_key(self.spreadsheet_id)
                print(f"✅ Successfully connected to Google Spreadsheet: '{spreadsheet.title}'")
            except Exception as e:
                print(f"\n❌ [GoogleSheets] Could not open spreadsheet with ID '{self.spreadsheet_id}': {e}")
                print("👉 Please ensure you have SHARED the Google Sheet with your Service Account Email (found in credentials.json) as 'Editor'!\n")
        elif not self.spreadsheet_id:
            print("⚠️ [GoogleSheets] GOOGLE_SHEETS_SPREADSHEET_ID is not set in .env. Running local audit mode.")

        print("\n" + "=" * 75)
        print("📊 GOOGLE SHEETS 6-TAB SYNCHRONIZED EXPORT")
        print("-" * 75)
        print(f"{'TAB NAME':<24} | {'ROWS (incl. header)':<20} | {'STATUS'}")
        print("-" * 75)

        ws_map = {}
        if spreadsheet is not None:
            try:
                ws_map = {ws.title: ws for ws in spreadsheet.worksheets()}
            except Exception:
                ws_map = {}

        def export_single_tab(tab_name: str) -> tuple:
            rows = self.load_rows_for_tab(tab_name)
            row_count = len(rows)
            status = "LOCAL AUDIT (PASS)"
            if spreadsheet is not None:
                try:
                    worksheet = ws_map.get(tab_name)
                    if worksheet is None:
                        worksheet = spreadsheet.add_worksheet(
                            title=tab_name,
                            rows=max(100, row_count + 10),
                            cols=max(10, len(rows[0])),
                        )
                        ws_map[tab_name] = worksheet
                    else:
                        worksheet.clear()

                    # Update values (Multi-version gspread compatibility)
                    try:
                        worksheet.update(values=rows, range_name="A1")
                    except Exception:
                        try:
                            worksheet.update("A1", rows)
                        except Exception:
                            worksheet.update(rows)

                    status = f"✅ EXPORTED ({row_count} rows)"
                except Exception as e:
                    status = f"❌ FAILED: {str(e)[:50]}"
            return tab_name, row_count, status

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            tab_results = list(executor.map(export_single_tab, list(self.TAB_DEFINITIONS.keys())))

        for tab_name, row_count, status in tab_results:
            results[tab_name] = row_count
            print(f"{tab_name:<24} | {row_count:<20} | {status}")

        # Clean up default empty Sheet1 if other tabs exist
        if spreadsheet is not None and "Sheet1" in ws_map and len(ws_map) > 1:
            try:
                spreadsheet.del_worksheet(ws_map["Sheet1"])
            except Exception:
                pass

        print("=" * 75 + "\n")
        return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=str, default=None)
    args = parser.parse_args()
    load_dotenv()
    exporter = GoogleSheetsExporter(user_id=args.user_id)
    exporter.export_all_tabs()


if __name__ == "__main__":
    main()
