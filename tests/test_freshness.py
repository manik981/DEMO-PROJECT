"""Unit tests for Phase II Date Resolution, Freshness Auditing, and Role Classification."""

from datetime import datetime, timedelta, timezone
import pytest
from src.utils.date_resolver import DateResolver
from src.utils.role_classifier import classify_role_family
from src.scrapers.news import NewsScraper

SAMPLE_NEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>TechCrunch AI</title>
    <link>https://techcrunch.com/category/artificial-intelligence/</link>
    <item>
      <title>Frontier Labs Unveils New Multimodal Architecture</title>
      <link>https://techcrunch.com/2026/08/14/frontier-labs-multimodal</link>
      <pubDate>Fri, 14 Aug 2026 14:00:00 GMT</pubDate>
      <description>&lt;p&gt;A detailed analysis of the newly released model weights.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Legacy AI Framework Sunset Announced</title>
      <link>https://techcrunch.com/2026/08/01/legacy-ai-sunset</link>
      <pubDate>Sat, 01 Aug 2026 10:00:00 GMT</pubDate>
      <description>The team has announced the deprecation schedule.</description>
    </item>
  </channel>
</rss>
"""


def test_rfc822_and_iso_date_parsing(tmp_path):
    """Test standard date string parsing."""
    resolver = DateResolver(cache_file=str(tmp_path / "cache.json"))

    dt1 = resolver.parse_rfc822_or_iso("Fri, 14 Aug 2026 14:00:00 GMT")
    assert dt1 is not None
    assert dt1.year == 2026
    assert dt1.month == 8
    assert dt1.day == 14
    assert dt1.tzinfo is not None

    dt2 = resolver.parse_rfc822_or_iso("2026-08-14T15:30:00Z")
    assert dt2 is not None
    assert dt2.minute == 30


def test_freshness_window_evaluation(tmp_path):
    """Test strict 24-hour freshness boundaries (rejecting stale and far-future dates)."""
    resolver = DateResolver(cache_file=str(tmp_path / "cache.json"))
    now = datetime.now(timezone.utc)

    # 1. Fresh date: 2 hours ago
    fresh_date = now - timedelta(hours=2)
    assert resolver.is_within_freshness_window(fresh_date, hours=24.0) is True

    # 2. Stale date: 28 hours ago
    stale_date = now - timedelta(hours=28)
    assert resolver.is_within_freshness_window(stale_date, hours=24.0) is False

    # 3. Far future invalid date: 3 days ahead -> rejected
    future_date = now + timedelta(days=3)
    assert resolver.is_within_freshness_window(future_date, hours=24.0) is False

    # 4. Near future within clock skew tolerance (e.g. 2 minutes) -> allowed
    near_future = now + timedelta(minutes=2)
    assert resolver.is_within_freshness_window(near_future, hours=24.0) is True


def test_heuristic_date_fallback_and_persistence(tmp_path):
    """Test heuristic date registration and cache consistency."""
    cache_file = tmp_path / "obs_cache.json"
    resolver = DateResolver(cache_file=str(cache_file))

    url = "https://example.com/undated-job-posting-123"
    dt1, source1, is_heur1, verified1 = resolver.resolve_date(url=url)

    assert source1 == "first_observed"
    assert is_heur1 is True
    assert verified1 is False

    # Re-instantiating resolver must load the same observed date for this URL
    resolver2 = DateResolver(cache_file=str(cache_file))
    dt2, source2, is_heur2, _ = resolver2.resolve_date(url=url)

    assert source2 == "first_observed"
    assert is_heur2 is True
    assert dt1.isoformat() == dt2.isoformat()


def test_deterministic_role_family_classifier():
    """Test rule-based classification into Research, Engineering, Product, and Other."""
    # Research
    assert classify_role_family("AI Research Scientist") == "Research"
    assert classify_role_family("Postdoctoral Fellow - Machine Learning") == "Research"
    assert classify_role_family("Deep Learning Researcher") == "Research"
    assert classify_role_family("Research Engineer") == "Research"

    # Engineering
    assert classify_role_family("Senior Machine Learning Engineer") == "Engineering"
    assert classify_role_family("Full Stack Software Developer") == "Engineering"
    assert classify_role_family("MLOps Infrastructure Architect") == "Engineering"
    assert classify_role_family("Backend Engineer - Python") == "Engineering"

    # Product
    assert classify_role_family("Product Manager - AI Platform") == "Product"
    assert classify_role_family("Technical Product Lead") == "Product"
    assert classify_role_family("UI/UX Designer") == "Product"

    # Other
    assert classify_role_family("Head of Sales and Business Development") == "Other"
    assert classify_role_family("Talent Acquisition Lead") == "Other"
    assert classify_role_family("Finance Analyst") == "Other"


def test_news_rss_parser(tmp_path):
    """Test NewsScraper parses items and strips HTML properly."""
    scraper = NewsScraper(raw_output_path=None)
    candidates = scraper.parse_feed_xml(SAMPLE_NEWS_RSS, "TechCrunch AI")

    assert len(candidates) == 2
    assert candidates[0]["title"] == "Frontier Labs Unveils New Multimodal Architecture"
    assert "detailed analysis" in candidates[0]["summary"]
    assert "<p>" not in candidates[0]["summary"]
    assert candidates[0]["url"] == "https://techcrunch.com/2026/08/14/frontier-labs-multimodal"
