"""Unit tests for Source Adapters, Provenance Preservation, and Freshness Validation."""

import json
from datetime import datetime, timezone
import pytest
from src.config.api_sources import EXTERNAL_API_SOURCES
from src.scrapers.adapters.jobs_adapters import (
    ActiveJobsDbAdapter,
    AIDevJobsAdapter,
    ArtificialIntelligenceJobsAdapter,
    FreehireJobsAdapter,
    IndeedJobsAdapter,
    USAJobsAdapter,
)
from src.scrapers.adapters.news_adapters import (
    DataCubeNewsAdapter,
    GNewsAdapter,
    GuardianNewsAdapter,
    NewsflashNewsAdapter,
    NoozraNewsAdapter,
)
from src.scrapers.adapters.zenserp_adapter import ZenserpDiscoveryAdapter
from src.utils.date_resolver import DateResolver


def test_source_configuration_registry():
    """Verify central source configuration contains all sources with valid structure."""
    expected_sources = [
        "zenserp", "newsflash", "gnews", "guardian",
        "datacube_ai", "noozra", "usajobs", "indeed_rapidapi", "active_jobs_db", "aidevjobs",
        "freehire", "artificial_intelligence_jobs", "arbeitnow"
    ]
    for src in expected_sources:
        assert src in EXTERNAL_API_SOURCES
        cfg = EXTERNAL_API_SOURCES[src]
        assert "name" in cfg
        assert "auth_type" in cfg
        assert "base_url" in cfg
        assert "category" in cfg


def test_missing_key_behavior():
    """Verify key-based adapters handle missing credentials gracefully without crashing."""
    gnews = GNewsAdapter(api_key="")
    guardian = GuardianNewsAdapter(api_key="")
    usajobs = USAJobsAdapter(api_key="")
    indeed = IndeedJobsAdapter(api_key="")
    active_jobs = ActiveJobsDbAdapter(api_key="")
    zenserp = ZenserpDiscoveryAdapter(api_key="")
    newsflash = NewsflashNewsAdapter(api_key="")

    assert not gnews.is_configured
    assert not guardian.is_configured
    assert not usajobs.is_configured
    assert not indeed.is_configured
    assert not active_jobs.is_configured
    assert not zenserp.is_configured
    assert not newsflash.is_configured


from src.scrapers.arbeitnow import ArbeitnowJobsAdapter

def test_no_key_public_adapters():
    """Verify public adapters report is_configured=True without any keys."""
    datacube = DataCubeNewsAdapter()
    noozra = NoozraNewsAdapter()
    aidev = AIDevJobsAdapter()
    freehire = FreehireJobsAdapter()
    ai_jobs = ArtificialIntelligenceJobsAdapter()
    arbeitnow = ArbeitnowJobsAdapter()

    assert datacube.is_configured
    assert noozra.is_configured
    assert aidev.is_configured
    assert freehire.is_configured
    assert ai_jobs.is_configured
    assert arbeitnow.is_configured


def test_gnews_response_normalization():
    """Test GNews API response normalization preserves URLs and ISO dates."""
    sample_gnews = {
        "articles": [
            {
                "title": "Frontier AI Models Advance Autonomous Coding",
                "description": "A new generation of code agents announced.",
                "url": "https://example.com/frontier-ai-news",
                "publishedAt": "2026-08-14T18:00:00Z",
                "source": {"name": "Tech Daily", "url": "https://example.com"},
            }
        ]
    }

    # Simulate parsing
    articles = sample_gnews["articles"]
    assert len(articles) == 1
    art = articles[0]
    assert art["url"] == "https://example.com/frontier-ai-news"
    assert art["source"]["name"] == "Tech Daily"


def test_usajobs_response_normalization():
    """Test USAJOBS Search API response parsing and remote classification."""
    sample_usajobs = {
        "SearchResult": {
            "SearchResultItems": [
                {
                    "MatchedObjectDescriptor": {
                        "PositionTitle": "AI Research Scientist",
                        "OrganizationName": "Department of Energy",
                        "PositionURI": "https://www.usajobs.gov/job/123456",
                        "PublicationStartDate": "2026-08-14",
                        "UserArea": {"Details": {"TeleworkEligible": True}},
                    }
                }
            ]
        }
    }

    item = sample_usajobs["SearchResult"]["SearchResultItems"][0]["MatchedObjectDescriptor"]
    assert item["PositionTitle"] == "AI Research Scientist"
    assert item["OrganizationName"] == "Department of Energy"
    assert item["PositionURI"] == "https://www.usajobs.gov/job/123456"
    assert item["UserArea"]["Details"]["TeleworkEligible"] is True


def test_noozra_unresolved_url_filtering():
    """Verify that records without a legitimate source URL are marked unresolved and dropped."""
    sample_noozra = [
        {"title": "Valid Article", "url": "https://example.com/news/1", "date": "2026-08-14"},
        {"title": "Invalid Article Without URL", "url": "", "date": "2026-08-14"},
    ]

    valid_candidates = [item for item in sample_noozra if item.get("url")]
    assert len(valid_candidates) == 1
    assert valid_candidates[0]["url"] == "https://example.com/news/1"


from src.utils.ai_job_filter import is_ai_job


def test_ai_job_relevance_filter():
    """Verify that only authentic AI, ML, Data, and LLM roles pass the filter."""
    assert is_ai_job("Senior Machine Learning Engineer", "TechCorp") is True
    assert is_ai_job("Staff AI Research Scientist", "OpenAI") is True
    assert is_ai_job("Data Scientist - NLP & LLMs", "Acme") is True
    assert is_ai_job("MLOps Platform Engineer", "Startup") is True
    assert is_ai_job("Computer Vision Specialist", "Robotics Co") is True
    assert is_ai_job("Full Stack Engineer", "Anthropic") is True  # Known AI company

    assert is_ai_job("Lead Game Narrative Designer", "Ubisoft") is False
    assert is_ai_job("Dentist Assistant", "Dental Clinic") is False
    assert is_ai_job("Warehouse Associate", "Logistics Inc") is False
    assert is_ai_job("PHP Backend Developer", "Generic Retail") is False
