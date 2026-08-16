"""Unit and integration tests for Supabase PostgreSQL direct sync and CRUD operations."""

import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.db.supabase_client import SupabaseClient, get_supabase_client
from src.sync_supabase import load_jsonl_for_user


def test_supabase_client_initialization():
    """Verify SupabaseClient strips whitespace and formats REST endpoint correctly."""
    client = SupabaseClient(
        supabase_url=" https://xyzproject.supabase.co/ ",
        supabase_secret_key="  secret_token_123  ",
    )
    assert client.supabase_url == "https://xyzproject.supabase.co"
    assert client.supabase_key == "secret_token_123"
    assert client.rest_endpoint == "https://xyzproject.supabase.co/rest/v1"
    assert client.is_configured is True


def test_supabase_client_headers():
    """Verify headers include resolution=ignore-duplicates and Bearer token."""
    client = SupabaseClient(
        supabase_url="https://xyzproject.supabase.co",
        supabase_secret_key="test_token",
    )
    headers = client._get_headers(prefer_resolution="ignore-duplicates")
    assert headers["apikey"] == "test_token"
    assert headers["Authorization"] == "Bearer test_token"
    assert "resolution=ignore-duplicates" in headers["Prefer"]


@pytest.mark.asyncio
async def test_supabase_upsert_empty_records():
    """Verify upserting empty records returns 0 without network call."""
    client = SupabaseClient(
        supabase_url="https://xyzproject.supabase.co",
        supabase_secret_key="test_token",
    )
    count = await client.upsert_records("startups", [])
    assert count == 0


@pytest.mark.asyncio
async def test_supabase_unconfigured_client_safe_return():
    """Verify unconfigured client returns 0 safely without throwing exceptions."""
    client = SupabaseClient(
        supabase_url="https://your-project-ref.supabase.co",
        supabase_secret_key="your_service_role_secret_key_here",
    )
    count = await client.upsert_records("startups", [{"entity_name": "Test"}])
    assert count == 0
    
    total = await client.get_table_count("startups")
    assert total == 0


def test_jsonl_loader_fallback(tmp_path):
    """Test load_jsonl_for_user helper loads records from fallback paths."""
    file1 = tmp_path / "first.jsonl"
    file1.write_text('{"name": "Startup Alpha"}\n{"name": "Startup Beta"}\n', encoding="utf-8")
    
    records = load_jsonl_for_user([str(file1)], "test-user-id")
    assert len(records) == 2
    assert records[0]["name"] == "Startup Alpha"
    assert records[1]["name"] == "Startup Beta"


@pytest.mark.asyncio
async def test_supabase_upsert_400_failure_handling():
    """Verify that a 400 Bad Request (like a constraint mismatch) raises ValueError instead of silently failing."""
    client = SupabaseClient(
        supabase_url="https://xyzproject.supabase.co",
        supabase_secret_key="test_token",
    )
    
    mock_resp = MagicMock()
    mock_resp.status = 400
    mock_resp.text = AsyncMock(return_value='{"code":"42P10","message":"there is no unique or exclusion constraint matching the ON CONFLICT specification"}')
    
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_resp
    
    with patch("aiohttp.ClientSession.post", return_value=mock_cm):
        with pytest.raises(ValueError, match="Table 'startups' returned status 400"):
            await client.upsert_records("startups", [{"entity_name": "Test"}])
