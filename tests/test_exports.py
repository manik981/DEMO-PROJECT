from __future__ import annotations

import json

from src.analyzer import AnalysisResult
from src.document_processor import extract_document
from src.report_export import build_json_report, build_markdown_report, safe_report_stem
from src.schemas import DocumentAnalysis, TokenUsage
from src.validator import verify_citations
from tests.helpers import make_pdf, populated_analysis_payload


def _result() -> AnalysisResult:
    payload = populated_analysis_payload()
    payload["document_filename"] = "client_rfp.pdf"
    payload["analysis_date"] = "2026-01-15"
    analysis = DocumentAnalysis.model_validate(payload)
    document = extract_document(make_pdf(["The portal must support 500 concurrent users"]), "client_rfp.pdf", 10_000)
    audit = verify_citations(analysis, document)
    return AnalysisResult(
        analysis=analysis,
        evidence=audit,
        mode="direct",
        chunks_analyzed=1,
        model="agnes-2.5-flash",
        usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        warnings=["Example processing warning"],
    )


def test_markdown_export_contains_all_sections_and_actual_values():
    report = build_markdown_report(_result())

    assert "# Permit Portal - AI Proposal Analysis" in report
    assert "client_rfp.pdf" in report
    assert "2026-01-15" in report
    assert "## 1. Executive summary" in report
    assert "## 2. Functional requirements" in report
    assert "## 4. Technical requirements" in report
    assert "## 5. Missing information" in report
    assert "## 6. Ambiguities and contradictions" in report
    assert "## 7. Risk analysis" in report
    assert "## 8. Client clarification questions" in report
    assert "## 9. Solution recommendations" in report
    assert "## 10. Complexity assessment" in report
    assert "## 11. Source evidence audit" in report
    assert "FR-01" in report
    assert "Applicants must submit permit applications online." in report
    assert "Independent AI/ML Assessment Prototype" in report
    assert "Reliable cost, timeline, team-size and ROI estimates" in report
    assert "Example processing warning" in report


def test_markdown_export_marks_flagged_citations_for_review():
    result = _result()
    result.analysis.functional_requirements[0].source_page = 99
    document = extract_document(make_pdf(["The portal must support 500 concurrent users"]), "client_rfp.pdf", 10_000)
    result.evidence = verify_citations(result.analysis, document)

    report = build_markdown_report(result)

    assert "require human review" in report
    assert "does not exist" in report
    assert "functional_requirement:FR-01" in report
    assert "risk:RK-01" not in report


def test_markdown_source_audit_hides_verified_citations():
    report = build_markdown_report(_result())

    assert "All sources were verified successfully." in report
    assert "functional_requirement:FR-01" not in report


def test_json_export_is_valid_and_contains_validated_data():
    raw = build_json_report(_result())
    parsed = json.loads(raw)

    assert parsed["analysis"]["functional_requirements"][0]["id"] == "FR-01"
    assert parsed["analysis"]["document_filename"] == "client_rfp.pdf"
    assert parsed["evidence_audit"]["total"] == 5
    assert parsed["metadata"]["model"] == "agnes-2.5-flash"
    assert parsed["metadata"]["token_usage"]["total_tokens"] == 150


def test_export_handles_empty_sections_without_placeholders():
    payload = populated_analysis_payload()
    payload["functional_requirements"] = []
    payload["risks"] = []
    payload["document_filename"] = "empty_sections.txt"
    analysis = DocumentAnalysis.model_validate(payload)
    document = extract_document(b"The portal must support 500 concurrent users", "empty_sections.txt", 10_000)
    result = AnalysisResult(
        analysis=analysis,
        evidence=verify_citations(analysis, document),
        mode="direct",
        chunks_analyzed=1,
        model="test-model",
    )

    report = build_markdown_report(result)

    assert "_No items identified in the supplied document._" in report
    assert "lorem ipsum" not in report.lower()


def test_report_stem_is_filesystem_safe():
    from datetime import date

    suffix = f"_cynbit_analysis_{date.today().isoformat()}"
    assert safe_report_stem("../../Client RFP 2026 (final).pdf").endswith(suffix)
    assert "/" not in safe_report_stem("../../Client RFP 2026 (final).pdf")
    assert safe_report_stem("!!!.pdf").startswith("document_cynbit_analysis_")
