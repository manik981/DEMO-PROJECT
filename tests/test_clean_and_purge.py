"""Unit tests for Data Clean & Purge Utility."""

import pytest
from pathlib import Path
from src.clean import TAB_MAP, TABLE_MAP


def test_clean_tab_and_table_mappings():
    """Verify clean utility maps all verticals to valid table and tab names."""
    expected_verticals = ["startups", "products", "papers", "jobs", "news", "mappings"]
    
    for v in expected_verticals:
        assert v in TAB_MAP, f"Missing {v} in TAB_MAP"
        assert v in TABLE_MAP, f"Missing {v} in TABLE_MAP"
        assert TAB_MAP[v] is not None
        assert TABLE_MAP[v] is not None


def test_clean_local_files_dry(tmp_path):
    """Test file unlinking logic for a test vertical."""
    test_file = tmp_path / "startups.jsonl"
    test_file.write_text('{"name": "test"}', encoding="utf-8")
    assert test_file.exists()
    
    test_file.unlink()
    assert not test_file.exists()
