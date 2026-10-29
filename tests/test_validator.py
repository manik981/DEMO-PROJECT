from __future__ import annotations

import copy

from src.document_processor import extract_document
from src.schemas import DocumentAnalysis, NOT_FOUND
from src.validator import normalize_analysis, verify_citations
from tests.helpers import make_docx, make_pdf, populated_analysis_payload

EVIDENCE = "The portal must support 500 concurrent users"


def _analysis(payload: dict) -> DocumentAnalysis:
    return DocumentAnalysis.model_validate(payload)


def test_matching_page_and_evidence_is_verified():
    pdf = make_pdf([f"Requirement: {EVIDENCE}."])
    document = extract_document(pdf, "rfp.pdf", max_chars=10_000)
    result = _analysis(populated_analysis_payload())

    audit = verify_citations(result, document)

    assert audit.total == 5
    assert audit.verified == 5
    assert audit.verification_rate == 1.0
    assert all(check.reason for check in audit.checks)


def test_nonexistent_page_is_flagged():
    pdf = make_pdf([f"Requirement: {EVIDENCE}."])
    document = extract_document(pdf, "rfp.pdf", max_chars=10_000)
    payload = populated_analysis_payload()
    payload["functional_requirements"][0]["source_page"] = 99

    audit = verify_citations(_analysis(payload), document)
    check = next(c for c in audit.checks if c.item_id == "FR-01")

    assert check.verified is False
    assert "does not exist" in check.reason
    assert audit.verified == 4


def test_evidence_on_wrong_page_is_flagged_with_extra_context():
    pdf = make_pdf([f"Requirement: {EVIDENCE}.", "Unrelated appendix text."])
    document = extract_document(pdf, "rfp.pdf", max_chars=10_000)
    payload = populated_analysis_payload()
    payload["functional_requirements"][0]["source_page"] = 2

    audit = verify_citations(_analysis(payload), document)
    check = next(c for c in audit.checks if c.item_id == "FR-01")

    assert check.verified is False
    assert "not found on cited page 2" in check.reason
    assert "elsewhere" in check.reason


def test_missing_page_on_pdf_is_flagged_as_unverified():
    pdf = make_pdf([f"Requirement: {EVIDENCE}."])
    document = extract_document(pdf, "rfp.pdf", max_chars=10_000)
    payload = populated_analysis_payload()
    payload["functional_requirements"][0]["source_page"] = None

    audit = verify_citations(_analysis(payload), document)
    check = next(c for c in audit.checks if c.item_id == "FR-01")

    assert check.verified is False
    assert "page is unverified" in check.reason


def test_docx_evidence_without_pages_is_traceable():
    data = make_docx([f"Requirement: {EVIDENCE}."])
    document = extract_document(data, "rfp.docx", max_chars=10_000)
    payload = populated_analysis_payload()
    for collection in (
        "functional_requirements",
        "non_functional_requirements",
        "technical_requirements",
        "ambiguities",
        "risks",
    ):
        for item in payload[collection]:
            item["source_page"] = None

    audit = verify_citations(_analysis(payload), document)

    assert audit.verified == audit.total
    assert "No page metadata" in audit.checks[0].reason


def test_absent_evidence_is_flagged():
    pdf = make_pdf([f"Requirement: {EVIDENCE}."])
    document = extract_document(pdf, "rfp.pdf", max_chars=10_000)
    payload = populated_analysis_payload()
    payload["functional_requirements"][0]["evidence"] = NOT_FOUND

    audit = verify_citations(_analysis(payload), document)
    check = next(c for c in audit.checks if c.item_id == "FR-01")

    assert check.verified is False
    assert "No supporting evidence" in check.reason


def test_fabricated_evidence_is_flagged():
    pdf = make_pdf([f"Requirement: {EVIDENCE}."])
    document = extract_document(pdf, "rfp.pdf", max_chars=10_000)
    payload = populated_analysis_payload(evidence="The client promised a ten million dollar budget.")
    payload["functional_requirements"][0]["evidence"] = "A completely invented quotation"

    audit = verify_citations(_analysis(payload), document)
    check = next(c for c in audit.checks if c.item_id == "FR-01")

    assert check.verified is False


def test_empty_analysis_has_zero_rate_without_division_error():
    document = extract_document(make_pdf([f"Requirement: {EVIDENCE}."]), "rfp.pdf", max_chars=10_000)
    payload = populated_analysis_payload()
    for collection in (
        "functional_requirements",
        "non_functional_requirements",
        "technical_requirements",
        "ambiguities",
        "risks",
    ):
        payload[collection] = []

    audit = verify_citations(_analysis(payload), document)

    assert audit.total == 0
    assert audit.verified == 0
    assert audit.verification_rate == 0.0


def test_normalize_deduplicates_and_repairs_ids():
    payload = copy.deepcopy(populated_analysis_payload())
    duplicate = copy.deepcopy(payload["functional_requirements"][0])
    duplicate["id"] = "FR-01"
    another = copy.deepcopy(payload["functional_requirements"][0])
    another["id"] = "FR-02"
    another["description"] = "Different requirement about notifications."
    payload["functional_requirements"] = [payload["functional_requirements"][0], duplicate, another]
    payload["non_functional_requirements"][0]["id"] = "NFR-01"
    payload["technical_requirements"][0]["id"] = "TR-01"

    analysis = normalize_analysis(_analysis(payload))

    assert len(analysis.functional_requirements) == 2
    assert [r.id for r in analysis.functional_requirements] == ["FR-01", "FR-02"]
    assert len({r.id for r in analysis.functional_requirements}) == 2


def test_normalize_keeps_technical_items_with_different_status():
    payload = populated_analysis_payload()
    suggested = copy.deepcopy(payload["technical_requirements"][0])
    suggested["id"] = "TR-02"
    suggested["status"] = "suggested"
    payload["technical_requirements"].append(suggested)

    analysis = normalize_analysis(_analysis(payload))

    assert len(analysis.technical_requirements) == 2
