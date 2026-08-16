"""Unit tests for Phase I bulk scrapers and zero-hallucination parsing."""

import json
from datetime import datetime, timezone
import pytest
from src.scrapers.papers import PapersScraper
from src.scrapers.products import ProductsScraper
from src.scrapers.startups import StartupsScraper

SAMPLE_CROSSREF_WORK = {
    "DOI": "10.1000/182",
    "URL": "https://doi.org/10.1000/182",
    "title": ["Scaling Laws for Autonomous Reasoning Agents"],
    "author": [
        {"given": "Alice", "family": "Researcher"},
        {"given": "Bob", "family": "Engineer"},
    ],
    "abstract": "<jats:p>We present scaling laws for agents. Code available at https://github.com/sample-org/reasoning-agent.</jats:p>",
    "container-title": ["Journal of Artificial Intelligence Research"],
    "publisher": "AI Access Foundation",
    "type": "journal-article",
    "is-referenced-by-count": 42,
    "published": {"date-parts": [[2024, 1, 15]]},
}


def test_crossref_work_normalization():
    """Test normalizing Crossref API work items."""
    scraper = PapersScraper(raw_output_path=None)
    res = scraper.normalize_crossref_work(SAMPLE_CROSSREF_WORK)

    assert res is not None
    assert res["title"] == "Scaling Laws for Autonomous Reasoning Agents"
    assert res["authors"] == ["Alice Researcher", "Bob Engineer"]
    assert res["paper_url"] == "https://doi.org/10.1000/182"
    assert res["doi"] == "10.1000/182"
    assert "https://github.com" in res["abstract"]
    assert "<jats:p>" not in res["abstract"]
    assert res["venue"] == "Journal of Artificial Intelligence Research"
    assert res["citation_count"] == 42
    assert res["published_date"].year == 2024
    assert res["source"] == "crossref"


def test_github_candidate_regex_extraction():
    """Test GitHub regex extractor identifies valid repos and ignores false positives."""
    scraper = PapersScraper(raw_output_path=None)

    # Valid candidate
    text_with_repo = "Our source code is at https://github.com/deepmind/alpha-code and licensed MIT."
    match = scraper.extract_github_candidate(text_with_repo)
    assert match == ("deepmind", "alpha-code")

    # With trailing punctuation
    text_punct = "Checkout github.com/openai/whisper.git for details!"
    match2 = scraper.extract_github_candidate(text_punct)
    assert match2 == ("openai", "whisper")

    # Excluded paths
    text_noise = "See our discussion on https://github.com/topics/machine-learning for info."
    assert scraper.extract_github_candidate(text_noise) is None


def test_zero_hallucination_guarantee():
    """Verify that text without a repository produces None and never hallucinates."""
    scraper = PapersScraper(raw_output_path=None)
    no_repo_text = "We evaluate 50 models without public weights or source code."
    assert scraper.extract_github_candidate(no_repo_text) is None


def test_product_pricing_model_normalization():
    """Test mapping of noisy pricing strings to valid schema enum literals."""
    scraper = ProductsScraper(raw_output_path=None)

    assert scraper.normalize_pricing_model("Free") == "FREE"
    assert scraper.normalize_pricing_model("Open Source") == "FREE"
    assert scraper.normalize_pricing_model("Freemium") == "FREEMIUM"
    assert scraper.normalize_pricing_model("Free trial available") == "FREEMIUM"
    assert scraper.normalize_pricing_model("$29/month") == "PAID"
    assert scraper.normalize_pricing_model("Contact Sales / Enterprise") == "ENTERPRISE"
    assert scraper.normalize_pricing_model(None) == "FREEMIUM"


def test_startup_deduplication(tmp_path):
    """Test that existing records in JSONL are loaded to prevent duplicate extraction."""
    jsonl_file = tmp_path / "startups.jsonl"
    existing_record = {
        "schemaVersion": "1.0",
        "recordType": "STARTUP",
        "source": {"name": "YC", "url": "https://www.ycombinator.com/companies/stripe"},
        "content": {"entityName": "Stripe", "data": {"employeeCount": 8000}},
        "collectedAt": datetime.now(timezone.utc).isoformat(),
    }
    jsonl_file.write_text(json.dumps(existing_record) + "\n", encoding="utf-8")

    scraper = StartupsScraper(raw_output_path=str(jsonl_file))
    assert "https://www.ycombinator.com/companies/stripe" in scraper.seen_urls
