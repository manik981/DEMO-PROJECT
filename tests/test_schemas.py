from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas import (
    NOT_FOUND,
    Complexity,
    DocumentAnalysis,
    FindingsAnalysis,
    Priority,
    Requirement,
    Risk,
)
from tests.helpers import empty_analysis_payload, populated_analysis_payload


def test_valid_analysis_payload_is_parsed():
    analysis = DocumentAnalysis.model_validate(populated_analysis_payload())

    assert analysis.executive_summary.overall_complexity is Complexity.MEDIUM
    assert analysis.functional_requirements[0].priority is Priority.HIGH
    assert analysis.functional_requirements[0].source_page == 1
    assert analysis.complexity_assessment.level is Complexity.MEDIUM


def test_enum_validation_rejects_unknown_priority():
    payload = populated_analysis_payload()
    payload["functional_requirements"][0]["priority"] = "Critical"

    with pytest.raises(ValidationError):
        DocumentAnalysis.model_validate(payload)


def test_invalid_enum_message_is_useful():
    with pytest.raises(ValidationError) as error:
        Requirement.model_validate(
            {
                "id": "FR-1",
                "description": "Something",
                "category": "General",
                "priority": "Urgent",
                "evidence": "text",
            }
        )
    assert "priority" in str(error.value)


def test_missing_finding_arrays_default_to_empty():
    payload = empty_analysis_payload()
    del payload["risks"]
    del payload["technical_requirements"]
    del payload["ambiguities"]

    analysis = DocumentAnalysis.model_validate(payload)

    assert analysis.risks == []
    assert analysis.technical_requirements == []
    assert analysis.ambiguities == []


def test_missing_required_summary_still_fails_validation():
    payload = empty_analysis_payload()
    del payload["executive_summary"]

    with pytest.raises(ValidationError, match="executive_summary"):
        DocumentAnalysis.model_validate(payload)


def test_missing_evidence_is_labelled_explicitly():
    requirement = Requirement.model_validate(
        {
            "id": "FR-1",
            "description": "The portal must accept online applications.",
            "category": "Permitting",
            "priority": "High",
            "source_page": None,
            "evidence": "",
        }
    )
    assert requirement.evidence == NOT_FOUND


def _risk(category: object) -> Risk:
    return Risk.model_validate(
        {
            "id": "RK-01",
            "description": "A risk.",
            "category": category,
            "severity": "High",
            "reason": "A reason.",
            "evidence": "A quote.",
            "mitigation": "A mitigation.",
        }
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("integration", "integration"),
        ("Technical", "technical"),
        ("technical_risk", "technical"),
        ("tech", "technical"),
        ("vendor risk", "delivery"),
        ("Schedule", "delivery"),
        ("resources", "delivery"),
        ("Security & Compliance", "security"),
        ("cyber", "security"),
        ("regulatory", "compliance"),
        ("architecture concern", "technical"),
        ("business", "other"),
        ("quality", "other"),
        ("", "other"),
    ],
)
def test_invalid_risk_categories_normalise_to_allowed_values(raw, expected):
    risk = _risk(raw)
    assert risk.category.value == expected


def test_valid_risk_category_is_preserved():
    assert _risk("scope").category.value == "scope"


def test_findings_analysis_accepts_has_more_indicator():
    payload = populated_analysis_payload()
    payload["has_more"] = True

    assert FindingsAnalysis.model_validate(payload).has_more is True


def test_page_numbers_are_coerced_from_common_formats():
    base = {
        "id": "FR-1",
        "description": "A requirement.",
        "category": "General",
        "evidence": "A requirement.",
    }
    assert Requirement.model_validate({**base, "source_page": "p. 4"}).source_page == 4
    assert Requirement.model_validate({**base, "source_page": "Page 12"}).source_page == 12
    assert Requirement.model_validate({**base, "source_page": 0}).source_page is None
    assert Requirement.model_validate({**base, "source_page": "not stated"}).source_page is None


def test_empty_required_text_fails_validation():
    with pytest.raises(ValidationError):
        Requirement.model_validate(
            {
                "id": "FR-1",
                "description": "",
                "category": "General",
                "evidence": "text",
            }
        )


def test_extra_keys_are_ignored_not_rejected():
    payload = populated_analysis_payload()
    payload["unexpected_key"] = "ignored"
    analysis = DocumentAnalysis.model_validate(payload)
    assert not hasattr(analysis, "unexpected_key")


def test_analysis_round_trip_json():
    analysis = DocumentAnalysis.model_validate(populated_analysis_payload())
    again = DocumentAnalysis.model_validate_json(analysis.model_dump_json())
    assert again.functional_requirements[0].id == "FR-01"
