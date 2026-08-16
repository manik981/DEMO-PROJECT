"""Unit tests for Phase IV Deterministic Entity Resolution.

Tests legal normalization, RapidFuzz threshold matching, CSV mapping generation,
and the mandatory assignment test ensuring 'OpenAI', 'OpenAI, Inc.', and 'Open AI'
all resolve to canonical 'OpenAI'.
"""

import csv
import json
from pathlib import Path
import pytest
from src.resolver.entity_resolver import EntityResolver


@pytest.fixture
def resolver(tmp_path):
    """Fixture providing an EntityResolver initialized with test seed catalog."""
    seed_file = tmp_path / "canonical_startups.json"
    seed_data = [
        "OpenAI",
        "Anthropic",
        "Google DeepMind",
        "Mistral AI",
        "Cohere",
        "Hugging Face",
        "Stability AI",
        "Scale AI",
    ]
    seed_file.write_text(json.dumps(seed_data), encoding="utf-8")

    out_csv = tmp_path / "entity_mapping_log.csv"
    review_csv = tmp_path / "manual_review_entities.csv"

    return EntityResolver(
        seed_path=str(seed_file),
        output_csv_path=str(out_csv),
        review_csv_path=str(review_csv),
    )


def test_openai_variants_resolve_to_canonical(resolver):
    """MANDATORY ASSIGNMENT TEST:

    Verify 'OpenAI', 'OpenAI, Inc.', and 'Open AI' all resolve to 'OpenAI'.
    """
    res1 = resolver.resolve("OpenAI")
    res2 = resolver.resolve("OpenAI, Inc.")
    res3 = resolver.resolve("Open AI")

    assert res1.canonical_name == "OpenAI"
    assert res2.canonical_name == "OpenAI"
    assert res3.canonical_name == "OpenAI"


def test_seed_legal_suffix_stripping(resolver):
    """Test resolution of various legal entity forms to canonical seed names."""
    assert resolver.resolve("Anthropic, PBC").canonical_name == "Anthropic"
    assert resolver.resolve("Anthropic LLC").canonical_name == "Anthropic"
    assert resolver.resolve("Google DeepMind Ltd.").canonical_name == "Google DeepMind"
    assert resolver.resolve("Cohere Technologies Inc.").canonical_name == "Cohere"
    assert resolver.resolve("Stability AI Labs").canonical_name == "Stability AI"


def test_threshold_auto_merge_and_new_entity(resolver):
    """Test threshold tiers: >=90 auto-merge, <75 new entity."""
    # High similarity (>90) -> Auto merge
    res_high = resolver.resolve("HuggingFace")
    assert res_high.canonical_name == "Hugging Face"
    assert res_high.match_score >= 90.0
    assert not res_high.requires_review

    # Unknown novel entity (<75) -> New canonical entity
    res_new = resolver.resolve("Quantum Frontier Cybernetics Inc")
    assert res_new.canonical_name == "Quantum Frontier Cybernetics Inc"
    assert res_new.method == "new_entity"
    assert not res_new.requires_review


def test_cross_run_canonical_learning(resolver):
    """Test that a newly registered entity can match subsequent mentions."""
    # First encounter
    res1 = resolver.resolve("Decagon Technologies Inc")
    assert res1.method == "new_entity"

    # Second encounter of same company with different legal suffix
    res2 = resolver.resolve("Decagon LLC")
    assert res2.canonical_name == "Decagon Technologies Inc"
    assert res2.method in ("cross_run_match", "exact_cross_run")


def test_csv_mapping_log_generation(tmp_path):
    """Test output CSV generation with required headers and content."""
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(["OpenAI"]), encoding="utf-8")
    out_csv = tmp_path / "entity_mapping_log.csv"

    resolver = EntityResolver(
        seed_path=str(seed_file),
        output_csv_path=str(out_csv),
    )

    resolver.resolve("OpenAI, Inc.", source_url="https://example.com", entity_type="STARTUP")

    assert out_csv.exists()
    with open(out_csv, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    assert len(reader) == 2  # Header + 1 record
    header = reader[0]
    row = reader[1]

    assert header[0] == "raw_name"
    assert header[1] == "canonical_name"
    assert header[2] == "match_score"
    assert header[3] == "method"

    assert row[0] == "OpenAI, Inc."
    assert row[1] == "OpenAI"
    assert float(row[2]) == 100.0
    assert row[3] == "seed_match"
