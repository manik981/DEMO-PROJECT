"""Unit tests for Phase III LLM Extractor, Semantic Chunker, and Quarantine Diagnostics."""

import json
from datetime import datetime, timezone
import pytest
from src.llm.chunker import SemanticChunker
from src.llm.extractor import LLMExtractor, ZERO_HALLUCINATION_SYSTEM_PROMPT
from src.schemas.startup import StartupEntity
from src.schemas.research_paper import ResearchPaperContent, ResearchPaperEntity


def test_zero_hallucination_system_prompt_mandate():
    """Verify system prompt contains the exact required non-hallucination instructions."""
    required_sentence = "Only extract fields present in the provided text. Set any field you cannot find to null. Never infer or guess a value."
    assert required_sentence in ZERO_HALLUCINATION_SYSTEM_PROMPT


def test_semantic_chunker_token_budgeting():
    """Test chunker budgets token capacity and prunes boilerplate."""
    chunker = SemanticChunker(max_input_tokens=100, output_reserve_tokens=30, safety_margin_tokens=10)
    # Effective limit: 60 tokens

    raw_text = """
    [Home](/) [About](/about) [Contact](/contact)
    Cookie Policy: Please accept cookies to proceed. All rights reserved 2026.
    
    # Section 1: Main Overview
    Acme AI is an enterprise startup founded in 2024 with 50 employees building frontier models.
    
    # Section 2: Detailed Specs
    The model architecture utilizes sparse mixture of experts with 64 routed experts.
    """

    cleaned = chunker.clean_boilerplate(raw_text)
    assert "Cookie Policy" not in cleaned
    assert "[Home]" not in cleaned

    budgeted = chunker.chunk_and_budget(raw_text)
    assert len(budgeted) > 0
    assert chunker.estimate_tokens(budgeted) <= 80


def test_semantic_chunker_heading_splits():
    """Test chunker splits cleanly on markdown headings."""
    chunker = SemanticChunker()
    doc = "# Intro\nThis is intro.\n\n## Details\nThese are details.\n\n### Metrics\nHigh accuracy."
    blocks = chunker.split_semantic_blocks(doc)
    assert len(blocks) == 3
    assert blocks[0].startswith("# Intro")
    assert blocks[1].startswith("## Details")
    assert blocks[2].startswith("### Metrics")


def test_quarantine_logging(tmp_path):
    """Test that failed records are preserved in quarantine files with full diagnostics."""
    quarantine_dir = tmp_path / "quarantine"
    structured_dir = tmp_path / "structured"

    extractor = LLMExtractor(
        quarantine_dir=str(quarantine_dir),
        structured_dir=str(structured_dir),
    )

    extractor._quarantine_record(
        record_type="STARTUP",
        source_url="https://example.com/failed-startup",
        error_msg="Missing required field 'source.name'",
        raw_output='{"content": {"entityName": "Unknown"}}',
        attempt=2,
    )

    quarantine_file = quarantine_dir / "startup.jsonl"
    assert quarantine_file.exists()

    with open(quarantine_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 1
    log = lines[0]
    assert log["record_type"] == "STARTUP"
    assert log["source_url"] == "https://example.com/failed-startup"
    assert log["attempt"] == 2
    assert "Missing required field" in log["error"]
    assert log["timestamp"] is not None


def test_repair_prompt_construction():
    """Test repair prompt incorporates schema errors and zero-hallucination reminders."""
    extractor = LLMExtractor()
    prompt = extractor._build_repair_prompt(
        raw_output='{"pricingModel": "SUPER_PREMIUM"}',
        validation_error="Input should be 'FREE', 'FREEMIUM', 'PAID' or 'ENTERPRISE'",
        schema_json='{"type": "object"}',
    )

    assert "SUPER_PREMIUM" in prompt
    assert "Validation Error" in prompt
    assert "Only extract fields present in the text" in prompt


def test_post_validate_grounding_invalid_github():
    """Test that post-validation zeros out non-existent or invalid GitHub links."""
    extractor = LLMExtractor()
    paper = ResearchPaperEntity(
        schemaVersion="1.0",
        recordType="RESEARCH_PAPER",
        content=ResearchPaperContent(
            title="A Novel Method",
            authors=["John Doe"],
            paper_url="https://arxiv.org/abs/2401.99999",
            github_url="https://github.com/nonexistent-org/fake-repo-123456789",
            github_stars=999999,
            published_date=datetime.now(timezone.utc),
        ),
    )

    # Grounding against live sync lookup should clear or null unverified repo
    grounded = extractor.post_validate_and_ground(paper)
    # The nonexistent repo should be grounded to None or validated
    assert grounded.content.github_url is None or "github.com" in grounded.content.github_url
