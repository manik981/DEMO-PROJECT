"""Unit tests for Pydantic entity schema models and validation."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from src.schemas import (
    JobContent,
    JobEntity,
    NewsContent,
    NewsEntity,
    ProductContent,
    ProductEntity,
    ResearchPaperContent,
    ResearchPaperEntity,
    SourceInfo,
    StartupContent,
    StartupData,
    StartupEntity,
)


def test_startup_entity_instantiation():
    """Test clean instantiation of StartupEntity with valid dummy data."""
    startup = StartupEntity(
        schemaVersion="1.0",
        recordType="STARTUP",
        source=SourceInfo(name="Y Combinator", url="https://ycombinator.com/companies/stripe"),
        content=StartupContent(
            entityName="Stripe",
            data=StartupData(employeeCount=8000),
        ),
        collectedAt=datetime.now(timezone.utc),
    )

    assert startup.recordType == "STARTUP"
    assert startup.content.entityName == "Stripe"
    assert startup.content.data.employeeCount == 8000
    assert startup.source.name == "Y Combinator"
    assert startup.source.url == "https://ycombinator.com/companies/stripe"


def test_product_entity_instantiation():
    """Test clean instantiation of ProductEntity with valid dummy data."""
    product = ProductEntity(
        schemaVersion="1.0",
        recordType="PRODUCT",
        source=SourceInfo(name="ProductHunt", url="https://producthunt.com/posts/claude-3-5-sonnet"),
        content=ProductContent(
            startupName="Anthropic",
            pricingModel="FREEMIUM",
        ),
        collectedAt=datetime.now(timezone.utc),
    )

    assert product.recordType == "PRODUCT"
    assert product.content.startupName == "Anthropic"
    assert product.content.pricingModel == "FREEMIUM"
    assert product.source.name == "ProductHunt"


def test_product_invalid_pricing_model():
    """Test that invalid pricingModel raises ValidationError."""
    with pytest.raises(ValidationError):
        ProductEntity(
            schemaVersion="1.0",
            recordType="PRODUCT",
            source=SourceInfo(name="ProductHunt", url="https://producthunt.com"),
            content=ProductContent(
                startupName="Anthropic",
                pricingModel="INVALID_TIER",  # type: ignore
            ),
            collectedAt=datetime.now(timezone.utc),
        )


def test_research_paper_entity_instantiation():
    """Test clean instantiation of ResearchPaperEntity with valid dummy data."""
    paper = ResearchPaperEntity(
        schemaVersion="1.0",
        recordType="RESEARCH_PAPER",
        content=ResearchPaperContent(
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"],
            paper_url="https://arxiv.org/abs/1706.03762",
            github_url="https://github.com/tensorflow/tensor2tensor",
            github_stars=14500,
            published_date=datetime(2017, 6, 12, 0, 0, tzinfo=timezone.utc),
        ),
    )

    assert paper.recordType == "RESEARCH_PAPER"
    assert paper.content.title == "Attention Is All You Need"
    assert len(paper.content.authors) == 4
    assert paper.content.github_stars == 14500


def test_job_entity_instantiation():
    """Test clean instantiation of JobEntity with valid dummy data."""
    job = JobEntity(
        schemaVersion="1.0",
        recordType="JOB",
        content=JobContent(
            company="OpenAI",
            date=datetime.now(timezone.utc),
            is_remote=True,
            role_family="Machine Learning Engineering",
        ),
    )

    assert job.recordType == "JOB"
    assert job.content.company == "OpenAI"
    assert job.content.is_remote is True
    assert job.content.role_family == "Machine Learning Engineering"


def test_news_entity_instantiation():
    """Test clean instantiation of NewsEntity with valid dummy data."""
    news = NewsEntity(
        schemaVersion="1.0",
        recordType="NEWS",
        source=SourceInfo(name="TechCrunch", url="https://techcrunch.com/ai"),
        content=NewsContent(
            title="Next Generation Reasoning Models Released",
            url="https://techcrunch.com/2026/08/new-models",
            published_date=datetime.now(timezone.utc),
            summary="A breakthrough in autonomous LLM reasoning agents announced today.",
        ),
        collectedAt=datetime.now(timezone.utc),
    )

    assert news.recordType == "NEWS"
    assert news.content.title == "Next Generation Reasoning Models Released"
    assert news.source.name == "TechCrunch"
    assert len(news.content.summary) > 0


def test_json_serialization_roundtrip():
    """Test that all entities serialize and deserialize cleanly to/from JSON."""
    startup = StartupEntity(
        source=SourceInfo(name="Directory", url="https://example.com"),
        content=StartupContent(entityName="TestAI", data=StartupData(employeeCount=42)),
        collectedAt=datetime.now(timezone.utc),
    )

    json_data = startup.model_dump_json()
    assert "TestAI" in json_data

    reloaded = StartupEntity.model_validate_json(json_data)
    assert reloaded.content.entityName == "TestAI"
    assert reloaded.content.data.employeeCount == 42
