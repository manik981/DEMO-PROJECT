"""Ground-truth evaluation for the RFP analysis pipeline.

This script calls the real Agnes API. It compares actual model output with the
manually annotated synthetic dataset and writes measured metrics. No metric is
hardcoded. The dataset is intentionally small; see evaluation/README.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analyzer import AnalysisError, analyze_document  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.document_processor import DocumentError, extract_document  # noqa: E402
from src.schemas import DocumentAnalysis  # noqa: E402

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "is", "it", "of", "on", "or", "that", "the", "their", "this", "to", "was",
    "were", "will", "with", "must", "should", "shall", "can", "may", "all", "any",
    "each", "provide", "support", "system", "portal", "solution", "city", "vendor",
    "applicant", "applicants", "required", "requirement", "using", "use", "into",
}


def _tokens(text: str) -> set[str]:
    normalized = text.lower().replace(",", "").replace("%", "")
    words = re.findall(r"[a-z0-9][a-z0-9.]+", normalized)
    tokens = set()
    for word in words:
        if word in STOPWORDS or len(word) < 3:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        tokens.add(word)
    return tokens


def _similarity(expected: str, actual: str) -> float:
    expected_tokens, actual_tokens = _tokens(expected), _tokens(actual)
    if not expected_tokens or not actual_tokens:
        return 0.0
    overlap = len(expected_tokens & actual_tokens)
    if overlap == 0:
        return 0.0
    precision = overlap / len(actual_tokens)
    recall = overlap / len(expected_tokens)
    return 2 * precision * recall / (precision + recall)


def _best_score(ground_truth_item: dict[str, Any], actual_text: str) -> float:
    variants = [ground_truth_item.get("canonical", "")]
    variants += ground_truth_item.get("aliases", [])
    return max((_similarity(variant, actual_text) for variant in variants if variant), default=0.0)


def _metrics(true_positives: int, actual_count: int, ground_truth_count: int) -> dict[str, Any]:
    false_positives = max(actual_count - true_positives, 0)
    false_negatives = max(ground_truth_count - true_positives, 0)
    precision = true_positives / actual_count if actual_count else 0.0
    recall = true_positives / ground_truth_count if ground_truth_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "actual_count": actual_count,
        "ground_truth_count": ground_truth_count,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def match_items(
    ground_truth: list[dict[str, Any]],
    actual: list[tuple[str, str]],
    threshold: float,
) -> dict[str, Any]:
    """Greedy one-to-one lexical matching between annotated and actual items."""
    pair_scores = []
    for gt_index, gt_item in enumerate(ground_truth):
        for actual_index, (_, text) in enumerate(actual):
            score = _best_score(gt_item, text)
            if score >= threshold:
                pair_scores.append((score, gt_index, actual_index))
    pair_scores.sort(reverse=True)

    matched_gt: dict[int, tuple[int, float]] = {}
    matched_actual: set[int] = set()
    for score, gt_index, actual_index in pair_scores:
        if gt_index in matched_gt or actual_index in matched_actual:
            continue
        matched_gt[gt_index] = (actual_index, score)
        matched_actual.add(actual_index)

    matches = [
        {
            "ground_truth_id": ground_truth[gt_index]["id"],
            "actual_id": actual[actual_index][0],
            "score": round(score, 3),
        }
        for gt_index, (actual_index, score) in sorted(matched_gt.items())
    ]
    missed = [gt["id"] for index, gt in enumerate(ground_truth) if index not in matched_gt]
    extra = [actual[index][0] for index in range(len(actual)) if index not in matched_actual]

    result = _metrics(len(matched_gt), len(actual), len(ground_truth))
    result.update({"matches": matches, "missed_ground_truth": missed, "unmatched_actual_items": extra})
    return result


def _actual_items(analysis: DocumentAnalysis, section: str) -> list[tuple[str, str]]:
    model_items = getattr(analysis, section)
    attribute = {
        "missing_information": "topic",
        "technical_requirements": "technology",
    }.get(section, "description")
    return [(item.id, getattr(item, attribute)) for item in model_items]


def evaluate(analysis: DocumentAnalysis, ground_truth: dict[str, Any], threshold: float) -> dict[str, Any]:
    functional = match_items(
        ground_truth["functional_requirements"],
        _actual_items(analysis, "functional_requirements"),
        threshold,
    )
    non_functional = match_items(
        ground_truth["non_functional_requirements"],
        _actual_items(analysis, "non_functional_requirements"),
        threshold,
    )
    combined_gt = ground_truth["functional_requirements"] + ground_truth["non_functional_requirements"]
    combined_actual = _actual_items(analysis, "functional_requirements") + _actual_items(
        analysis, "non_functional_requirements"
    )
    overall_requirements = match_items(combined_gt, combined_actual, threshold)
    missing = match_items(
        ground_truth["missing_information"],
        _actual_items(analysis, "missing_information"),
        threshold,
    )
    return {
        "requirement_extraction": {
            "overall": overall_requirements,
            "functional": functional,
            "non_functional": non_functional,
        },
        "missing_information_detection": missing,
        "technical_requirements": match_items(
            ground_truth["technical_requirements"],
            _actual_items(analysis, "technical_requirements"),
            threshold,
        ),
        "ambiguity_detection": match_items(
            ground_truth["ambiguities"],
            _actual_items(analysis, "ambiguities"),
            threshold,
        ),
        "risk_detection": match_items(
            ground_truth["risks"],
            _actual_items(analysis, "risks"),
            threshold,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the analyzer against the synthetic ground truth.")
    parser.add_argument("--document", default=str(PROJECT_ROOT / "sample_data" / "sample_rfp.pdf"))
    parser.add_argument("--ground-truth", default=str(PROJECT_ROOT / "evaluation" / "ground_truth.json"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "evaluation" / "results.json"))
    parser.add_argument("--model", default=None, help="Override AGNES_MODEL for this run.")
    parser.add_argument("--threshold", type=float, default=0.42, help="Lexical match threshold (0-1).")
    args = parser.parse_args()

    settings = load_settings()
    if args.model:
        settings = replace(settings, model=args.model)
    if not settings.is_configured:
        print("AGNES_API_KEY is not configured. Add it to .env before running evaluation.", file=sys.stderr)
        return 1

    ground_truth = json.loads(Path(args.ground_truth).read_text(encoding="utf-8"))
    try:
        data = Path(args.document).read_bytes()
        document = extract_document(data, Path(args.document).name, settings.max_document_chars)
    except (OSError, DocumentError) as exc:
        print(f"Could not load evaluation document: {exc}", file=sys.stderr)
        return 1

    started = time.perf_counter()
    try:
        result = analyze_document(document, settings, progress=lambda message: print(f"  {message}"))
    except AnalysisError as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1
    elapsed = round(time.perf_counter() - started, 2)

    metrics = evaluate(result.analysis, ground_truth, args.threshold)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": ground_truth["dataset_name"],
        "dataset_note": ground_truth["labelling_note"],
        "document": Path(args.document).name,
        "model": settings.model,
        "mode": result.mode,
        "structured_output_valid": True,
        "valid_structured_output_rate": 1.0,
        "runs": 1,
        "runtime_seconds": elapsed,
        "token_usage": result.usage.model_dump(mode="json"),
        "citation_verification": {
            "checks": result.evidence.total,
            "verified": result.evidence.verified,
            "rate": result.evidence.verification_rate,
        },
        "metrics": metrics,
        "match_threshold": args.threshold,
        "limitations": [
            "One synthetic document and one model run; the valid structured-output rate is 1/1 by construction.",
            "Lexical matching can under-credit correct paraphrases and over-credit shared vocabulary.",
            "The ground truth covers this document only and does not generalize to real RFPs.",
        ],
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    overall = metrics["requirement_extraction"]["overall"]
    missing = metrics["missing_information_detection"]
    print("\nMeasured results")
    print(f"  Requirements: precision {overall['precision']:.3f}, recall {overall['recall']:.3f}, F1 {overall['f1']:.3f}")
    print(f"  Missing info: precision {missing['precision']:.3f}, recall {missing['recall']:.3f}, F1 {missing['f1']:.3f}")
    print(
        f"  Citations: {report['citation_verification']['verified']}/"
        f"{report['citation_verification']['checks']} "
        f"({report['citation_verification']['rate']:.1%}) traced"
    )
    print(f"  Structured output: valid (1 run)")
    print(f"  Saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
