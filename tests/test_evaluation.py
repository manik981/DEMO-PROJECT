from __future__ import annotations

import json
from pathlib import Path

from evaluation.evaluate import evaluate, match_items
from src.schemas import DocumentAnalysis
from tests.helpers import populated_analysis_payload


def test_evaluation_runs_on_synthetic_ground_truth():
    ground_truth = json.loads(Path("evaluation/ground_truth.json").read_text(encoding="utf-8"))
    analysis = DocumentAnalysis.model_validate(populated_analysis_payload())

    metrics = evaluate(analysis, ground_truth, threshold=0.42)

    overall = metrics["requirement_extraction"]["overall"]
    assert overall["actual_count"] == 2  # one functional + one non-functional fixture
    assert 0 <= overall["precision"] <= 1
    assert 0 <= overall["recall"] <= 1
    assert metrics["missing_information_detection"]["actual_count"] == 1
    assert "technical_requirements" in metrics


def test_match_items_is_one_to_one_and_reports_gaps():
    ground_truth = [
        {"id": "GT-1", "canonical": "Support 500 concurrent users", "aliases": []},
        {"id": "GT-2", "canonical": "WCAG 2.1 AA accessibility compliance", "aliases": []},
    ]
    actual = [("FR-1", "The system must support 500 concurrent users."), ("FR-2", "Unrelated reporting feature")]

    result = match_items(ground_truth, actual, threshold=0.42)

    assert result["true_positives"] == 1
    assert result["recall"] == 0.5
    assert result["precision"] == 0.5
    assert result["missed_ground_truth"] == ["GT-2"]
    assert result["unmatched_actual_items"] == ["FR-2"]
