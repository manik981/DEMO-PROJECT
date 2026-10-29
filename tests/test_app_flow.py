"""UI flow: a finished analysis must render, not merely report success."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from src import analyzer
from src.analyzer import AnalysisResult, analyze_document
from src.document_processor import ExtractedDocument, PageText
from src.schemas import CitationCheck, DocumentAnalysis, EvidenceAudit, TokenUsage
from tests.helpers import FakeGroqClient, chunk_payload, populated_analysis_payload

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

ROOT = Path(__file__).resolve().parents[1]


def _six_page_document() -> ExtractedDocument:
    pages = [
        PageText(
            page_number=page,
            text=(
                f"Section {page}. The permit portal must support 500 concurrent users, with page {page} "
                "describing intake, review, fees and public records."
            ),
        )
        for page in range(1, 7)
    ]
    return ExtractedDocument(
        filename="six_page_rfp.txt",
        file_type="txt",
        pages=pages,
        char_count=sum(len(page.text) for page in pages),
    )


def _six_section_responses() -> list[str]:
    descriptions = [
        "Applicants submit permit applications online.",
        "Staff review and approve each application.",
        "The system calculates and collects permit fees.",
        "Public records requests are tracked.",
        "Email notifications confirm submission status.",
        "Managers export monthly activity reports.",
    ]
    responses: list[str] = []
    for page, description in enumerate(descriptions, start=1):
        payload = chunk_payload()
        payload["functional_requirements"] = [
            {
                "id": "FR-1",
                "description": description,
                "category": "Permitting",
                "priority": "High",
                "source_page": page,
                "evidence": f"Section {page}",
            }
        ]
        if page == 1:
            payload["risks"] = populated_analysis_payload()["risks"]
        responses.append(json.dumps(payload))
    responses.append(json.dumps(populated_analysis_payload()))
    return responses


@pytest.fixture
def six_page_result(settings):
    chunked = dataclasses.replace(
        settings,
        direct_analysis_chars=0,
        chunk_chars=200,
        chunk_overlap_chars=20,
        max_chunks=8,
    )
    document = _six_page_document()
    client = FakeGroqClient(_six_section_responses())

    result = analyze_document(document, chunked, client=client, sleep=lambda _s: None)

    assert result.chunks_analyzed == 6
    assert len(result.analysis.functional_requirements) == 6
    assert result.analysis.risks
    return document, result


def _launch_ui(monkeypatch, document: ExtractedDocument, result: AnalysisResult):
    """Run the app with a pre-built result and return the rendered AppTest."""
    monkeypatch.setenv("AGNES_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        analyzer,
        "analyze_document",
        lambda document, settings, progress=None, client=None, sleep=None: result,
    )
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    at.session_state["document"] = document
    at.session_state["upload_meta"] = {"name": document.filename, "size": 4096}
    at.run()
    next(button for button in at.button if "Analyze RFP" in button.label).click()
    at.run()
    return at


def _citation_result(checks: list[CitationCheck]) -> AnalysisResult:
    verified = sum(1 for check in checks if check.verified)
    audit = EvidenceAudit(
        checks=checks,
        total=len(checks),
        verified=verified,
        verification_rate=round(verified / len(checks), 3) if checks else 0.0,
    )
    return AnalysisResult(
        analysis=DocumentAnalysis.model_validate(populated_analysis_payload()),
        evidence=audit,
        mode="direct",
        chunks_analyzed=1,
        model="agnes-2.5-flash",
        usage=TokenUsage(),
        warnings=[],
    )


def test_source_table_shows_only_unverified_citations(monkeypatch):
    document = _six_page_document()
    result = _citation_result(
        [
            CitationCheck(
                check_id="functional_requirement:FR-01",
                item_kind="functional_requirement",
                item_id="FR-01",
                source_page=9,
                verified=False,
                reason="Cited page 9 does not exist in the extracted document.",
            ),
            CitationCheck(
                check_id="risk:RK-01",
                item_kind="risk",
                item_id="RK-01",
                source_page=1,
                verified=True,
                reason="Evidence matched page 1 text.",
            ),
        ]
    )

    at = _launch_ui(monkeypatch, document, result)

    source_frames = [
        frame.value
        for frame in at.dataframe
        if {"Item", "Page", "Evidence", "Reason"}.issubset(frame.value.columns)
    ]
    assert len(source_frames) == 1
    frame = source_frames[0]
    assert "functional_requirement:FR-01" in frame["Item"].tolist()
    assert "risk:RK-01" not in frame["Item"].tolist()
    assert "Cited page 9 does not exist" in frame["Reason"].iloc[0]
    assert frame["Evidence"].iloc[0] == "The portal must support 500 concurrent users"

    markdown = " ".join(block.value for block in at.markdown)
    assert "1 of 2" in markdown


def test_source_table_replaced_by_success_message_when_all_verified(monkeypatch):
    document = _six_page_document()
    result = _citation_result(
        [
            CitationCheck(
                check_id="functional_requirement:FR-01",
                item_kind="functional_requirement",
                item_id="FR-01",
                source_page=1,
                verified=True,
                reason="Evidence matched page 1 text.",
            )
        ]
    )

    at = _launch_ui(monkeypatch, document, result)

    assert any("All sources were verified successfully." in block.value for block in at.success)
    assert not [
        frame
        for frame in at.dataframe
        if {"Item", "Page", "Evidence", "Reason"}.issubset(frame.value.columns)
    ]


def test_six_page_analysis_renders_findings_and_risks_in_ui(
    six_page_result, monkeypatch
):
    document, result = six_page_result

    monkeypatch.setenv("AGNES_API_KEY", "test-key-not-real")
    # The app imports analyze_document from this module at script start.
    monkeypatch.setattr(
        analyzer,
        "analyze_document",
        lambda document, settings, progress=None, client=None, sleep=None: result,
    )

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
    at.run()
    at.session_state["document"] = document
    at.session_state["upload_meta"] = {"name": document.filename, "size": 4096}
    at.run()

    next(button for button in at.button if "Analyze RFP" in button.label).click()
    at.run()

    assert not at.exception
    assert at.session_state["analysis_error"] is None
    assert at.session_state["result"] is not None

    markdown = [block.value for block in at.markdown]
    assert any("Analysis dashboard" in value for value in markdown)
    assert "### Permit Portal" in markdown
    assert "Risks" in [tab.label for tab in at.tabs]

    frames = [frame.value for frame in at.dataframe]
    requirement_frames = [frame for frame in frames if "Requirement" in frame.columns]
    risk_frames = [frame for frame in frames if "Risk" in frame.columns]
    assert any(
        "Applicants submit permit applications online." in frame["Requirement"].tolist()
        for frame in requirement_frames
    )
    assert any(
        "ERP integration may be harder than expected." in frame["Risk"].tolist()
        for frame in risk_frames
    )
