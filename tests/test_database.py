"""Unit tests for Supabase PostgreSQL Models and Repository Client."""

from datetime import datetime, timezone
import pytest
from src.db.models import (
    Base,
    EntityMappingLogModel,
    IngestionRunModel,
    JobModel,
    NewsModel,
    ProductModel,
    ResearchPaperModel,
    SourceRecordsAuditModel,
    StartupModel,
)
from src.db.supabase_client import SupabaseClient


def test_model_table_definitions():
    """Verify all 8 tables are defined with required columns."""
    tables = Base.metadata.tables

    assert "startups" in tables
    assert "products" in tables
    assert "research_papers" in tables
    assert "jobs" in tables
    assert "news" in tables
    assert "entity_mapping_log" in tables
    assert "ingestion_runs" in tables
    assert "source_records_audit" in tables
    assert "llm_logs" in tables


def test_research_paper_nullable_github_fields():
    """Verify research paper model permits nullable github_url and github_stars."""
    paper = ResearchPaperModel(
        title="Attention Is All You Need",
        authors=["Vaswani et al."],
        paper_url="https://arxiv.org/abs/1706.03762",
        github_url=None,
        github_stars=None,
        published_date=datetime.now(timezone.utc),
    )

    assert paper.github_url is None
    assert paper.github_stars is None
    assert paper.title == "Attention Is All You Need"


def test_supabase_client_content_hash():
    """Test SHA-256 content hashing for distributed deduplication."""
    client = SupabaseClient()
    content = "Sample raw HTML blob from scraped page"
    h1 = client.compute_content_hash(content)
    h2 = client.compute_content_hash(content)
    h3 = client.compute_content_hash(content + " modified")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_supabase_configured_status():
    """Verify is_configured handles missing vs populated environment values safely."""
    client_unconfigured = SupabaseClient(supabase_url="https://your-project-ref.supabase.co", supabase_secret_key="sb_secret_...")
    assert not client_unconfigured.is_configured
