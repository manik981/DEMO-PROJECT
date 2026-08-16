"""Unit tests for Google Sheets 6-Tab Synchronized Exporter."""

import os
from pathlib import Path
import pytest
from src.export.sheets import GoogleSheetsExporter, PROJECT_ROOT


def test_sheets_exporter_initialization():
    """Verify GoogleSheetsExporter parses credentials path and spreadsheet ID properly."""
    exporter = GoogleSheetsExporter(
        credentials_path="credentials.json",
        spreadsheet_id="https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0",
    )
    assert exporter.spreadsheet_id == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    assert "credentials.json" in exporter.credentials_path


def test_six_tabs_presence_in_definitions():
    """Verify all 6 required tabs are explicitly present in TAB_DEFINITIONS."""
    expected_tabs = [
        "Startups",
        "Products",
        "Research Papers",
        "Jobs",
        "News",
        "Entity Mapping Log",
    ]
    for tab in expected_tabs:
        assert tab in GoogleSheetsExporter.TAB_DEFINITIONS, f"Missing required tab: {tab}"


def test_tab_headers_match_specification():
    """Verify column headers match assignment and schema specifications."""
    defs = GoogleSheetsExporter.TAB_DEFINITIONS

    # 1. Startups
    assert defs["Startups"]["headers"] == [
        "User_ID", "schemaVersion", "recordType", "source_name", "source_url",
        "entityName", "employeeCount", "collectedAt"
    ]

    # 2. Products
    assert defs["Products"]["headers"] == [
        "User_ID", "schemaVersion", "recordType", "source_name", "source_url",
        "startupName", "pricingModel", "collectedAt"
    ]

    # 3. Research Papers
    assert defs["Research Papers"]["headers"] == [
        "User_ID", "schemaVersion", "recordType", "title", "authors",
        "paper_url", "github_url", "github_stars", "published_date"
    ]

    # 4. Jobs
    assert defs["Jobs"]["headers"] == [
        "User_ID", "schemaVersion", "recordType", "company", "title",
        "source_name", "source_url", "date", "is_remote", "role_family"
    ]

    # 5. News
    assert defs["News"]["headers"] == [
        "User_ID", "schemaVersion", "recordType", "source_name", "source_url",
        "title", "published_date", "summary", "collectedAt"
    ]

    # 6. Entity Mapping Log
    assert defs["Entity Mapping Log"]["headers"] == [
        "User_ID", "raw_name", "canonical_name", "match_score", "method",
        "source_url", "entity_type", "timestamp"
    ]


def test_load_rows_returns_header_at_minimum():
    """Verify load_rows_for_tab returns at least the header row even if no files exist."""
    exporter = GoogleSheetsExporter(user_id="test_user")
    for tab_name in GoogleSheetsExporter.TAB_DEFINITIONS:
        rows = exporter.load_rows_for_tab(tab_name)
        assert len(rows) >= 1
        assert rows[0] == GoogleSheetsExporter.TAB_DEFINITIONS[tab_name]["headers"]
        assert rows[0][0] == "User_ID"
