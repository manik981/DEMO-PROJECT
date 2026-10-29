"""Pydantic v2 schemas for structured RFP analysis.

The model is asked for JSON matching these schemas. Nothing in the UI or exports
trusts raw model output: every response is validated here first.
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NOT_FOUND = "Not found in supplied document"


class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    UNKNOWN = "Unknown"


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Complexity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    UNKNOWN = "Unknown"


class Origin(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class NFRStatus(str, Enum):
    EXPLICIT = "explicit"
    RECOMMENDED = "recommended"


class NFRCategory(str, Enum):
    PERFORMANCE = "performance"
    SCALABILITY = "scalability"
    AVAILABILITY = "availability"
    SECURITY = "security"
    PRIVACY = "privacy"
    RELIABILITY = "reliability"
    ACCESSIBILITY = "accessibility"
    MAINTAINABILITY = "maintainability"
    COMPLIANCE = "compliance"
    OTHER = "other"


class TechCategory(str, Enum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    API = "api"
    INTEGRATION = "integration"
    INFRASTRUCTURE = "infrastructure"
    AUTHENTICATION = "authentication"
    OTHER = "other"


class TechStatus(str, Enum):
    EXPLICIT = "explicitly_specified"
    SUGGESTED = "suggested"
    NOT_SPECIFIED = "not_specified"


class AmbiguityKind(str, Enum):
    VAGUE = "vague_requirement"
    CONFLICT = "conflict"
    UNDEFINED_TERM = "undefined_terminology"
    INCONSISTENT = "inconsistent_numbers_or_timeline"


class AmbiguityStatus(str, Enum):
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"


class RiskCategory(str, Enum):
    TECHNICAL = "technical"
    DELIVERY = "delivery"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    INTEGRATION = "integration"
    SCOPE = "scope"
    OTHER = "other"


_RISK_CATEGORY_ALIASES = {
    "technical_risk": "technical",
    "tech": "technical",
    "delivery_risk": "delivery",
    "schedule": "delivery",
    "scheduling": "delivery",
    "timeline": "delivery",
    "vendor": "delivery",
    "vendors": "delivery",
    "resource": "delivery",
    "resources": "delivery",
    "data": "technical",
    "operational": "other",
    "business": "other",
    "legal": "compliance",
    "regulatory": "compliance",
    "privacy": "compliance",
    "financial": "other",
    "cyber": "security",
    "infosec": "security",
}

# Ordered keyword fallback for values the model invents. The first token that
# matches a known category wins; anything unrecognised becomes "other".
_RISK_CATEGORY_KEYWORDS = (
    ("security", "security"),
    ("compliance", "compliance"),
    ("regulat", "compliance"),
    ("legal", "compliance"),
    ("audit", "compliance"),
    ("integration", "integration"),
    ("interface", "integration"),
    ("scope", "scope"),
    ("delivery", "delivery"),
    ("schedule", "delivery"),
    ("timeline", "delivery"),
    ("vendor", "delivery"),
    ("resource", "delivery"),
    ("technical", "technical"),
    ("technology", "technical"),
    ("architecture", "technical"),
    ("performance", "technical"),
    ("data", "technical"),
)


class Severity(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class RiskBasis(str, Enum):
    SOURCE_SUPPORTED = "source_supported"
    INFERRED = "inferred"


class _Schema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class _EvidenceMixin(_Schema):
    """Never leave evidence blank: mark absence explicitly instead of inventing text."""

    @model_validator(mode="before")
    @classmethod
    def _normalise_evidence(cls, data: Any) -> Any:
        if isinstance(data, dict):
            value = data.get("evidence")
            if value is None or (isinstance(value, str) and not value.strip()):
                data = {**data, "evidence": NOT_FOUND}
        return data


def _coerce_page(value: Any) -> int | None:
    """Accept 3, "3", "p. 3", "Page 3"; reject anything that is not a real page number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            number = int(match.group())
            return number if number > 0 else None
    return None


class ExecutiveSummary(_Schema):
    project_title: str = Field(default="Untitled RFP", min_length=1)
    project_overview: str = Field(min_length=1)
    business_objective: str = Field(min_length=1)
    intended_users: list[str] = Field(default_factory=list)
    project_category: str = Field(min_length=1)
    overall_complexity: Complexity
    complexity_rationale: str = Field(min_length=1)


class Requirement(_EvidenceMixin):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: str = Field(default="General", min_length=1)
    priority: Priority = Priority.UNKNOWN
    source_page: int | None = None
    source_section: str | None = None
    evidence: str
    confidence: Confidence = Confidence.MEDIUM
    origin: Origin = Origin.EXPLICIT

    _page = field_validator("source_page", mode="before")(_coerce_page)


class NonFunctionalRequirement(_EvidenceMixin):
    id: str = Field(min_length=1)
    category: NFRCategory
    description: str = Field(min_length=1)
    status: NFRStatus = NFRStatus.EXPLICIT
    priority: Priority = Priority.UNKNOWN
    source_page: int | None = None
    evidence: str
    confidence: Confidence = Confidence.MEDIUM

    _page = field_validator("source_page", mode="before")(_coerce_page)

    @field_validator("category", mode="before")
    @classmethod
    def _category_alias(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        aliases = {
            "uptime": "availability",
            "capacity": "scalability",
            "load": "scalability",
            "data_protection": "privacy",
            "compliance_regulatory": "compliance",
            "supportability": "maintainability",
            "usability": "accessibility",
        }
        key = value.strip().lower().replace(" ", "_").replace("-", "_")
        return aliases.get(key, key)


class TechnicalRequirement(_EvidenceMixin):
    id: str = Field(min_length=1)
    technology: str = Field(min_length=1)
    category: TechCategory = TechCategory.OTHER
    status: TechStatus = TechStatus.NOT_SPECIFIED
    notes: str = ""
    source_page: int | None = None
    evidence: str
    confidence: Confidence = Confidence.MEDIUM

    _page = field_validator("source_page", mode="before")(_coerce_page)

    @field_validator("category", mode="before")
    @classmethod
    def _category_alias(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        aliases = {
            "cloud": "infrastructure",
            "hosting": "infrastructure",
            "devops": "infrastructure",
            "deployment": "infrastructure",
            "third_party": "integration",
            "thirdparty": "integration",
            "messaging": "integration",
            "payment": "integration",
            "payments": "integration",
            "frontend": "framework",
            "backend": "framework",
            "library": "framework",
            "identity": "authentication",
            "sso": "authentication",
            "security": "authentication",
            "network": "infrastructure",
        }
        key = value.strip().lower().replace(" ", "_").replace("-", "_")
        return aliases.get(key, key)


class MissingInformation(_Schema):
    id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    priority: Priority = Priority.MEDIUM
    potential_impact: str = "Not assessed"


class Ambiguity(_EvidenceMixin):
    id: str = Field(min_length=1)
    kind: AmbiguityKind
    description: str = Field(min_length=1)
    evidence: str
    source_page: int | None = None
    status: AmbiguityStatus = AmbiguityStatus.POSSIBLE

    _page = field_validator("source_page", mode="before")(_coerce_page)


class Risk(_EvidenceMixin):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: RiskCategory
    severity: Severity
    reason: str = Field(min_length=1)
    evidence: str
    mitigation: str = Field(min_length=1)
    basis: RiskBasis = RiskBasis.INFERRED
    source_page: int | None = None

    _page = field_validator("source_page", mode="before")(_coerce_page)

    @field_validator("category", mode="before")
    @classmethod
    def _category_alias(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        if key in {member.value for member in RiskCategory}:
            return key
        for token in key.split("_"):
            if token in _RISK_CATEGORY_ALIASES:
                return _RISK_CATEGORY_ALIASES[token]
        for token in key.split("_"):
            for needle, category in _RISK_CATEGORY_KEYWORDS:
                if needle in token:
                    return category
        return RiskCategory.OTHER.value


class ClarificationQuestion(_Schema):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    priority: Priority = Priority.MEDIUM
    related_to: str = "General"


class TechnologyOption(_Schema):
    name: str
    reason: str


class ImplementationPhase(_Schema):
    name: str
    scope: str
    deliverables: list[str] = Field(default_factory=list)


class SolutionRecommendations(_Schema):
    potential_architecture: str
    technology_options: list[TechnologyOption] = Field(default_factory=list)
    integration_considerations: list[str] = Field(default_factory=list)
    security_recommendations: list[str] = Field(default_factory=list)
    implementation_phases: list[ImplementationPhase] = Field(default_factory=list)
    dependencies_and_assumptions: list[str] = Field(default_factory=list)


class ComplexityAssessment(_Schema):
    level: Complexity
    reasons: list[str] = Field(min_length=1)
    complexity_drivers: list[str] = Field(default_factory=list)
    major_unknowns: list[str] = Field(default_factory=list)


class ChunkExtraction(_Schema):
    """Reduced schema used for map-stage calls on long documents."""

    functional_requirements: list[Requirement] = Field(default_factory=list)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    technical_requirements: list[TechnicalRequirement] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    chunk_summary: str = ""
    has_more: bool = False


class FindingsAnalysis(_Schema):
    """Stage 1 output: document-grounded findings.

    Collection fields default to empty: a document may legitimately contain no
    item for a category, and treating that as a schema failure forced wasteful
    repairs. The executive summary remains mandatory.
    """

    executive_summary: ExecutiveSummary
    functional_requirements: list[Requirement] = Field(default_factory=list)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    technical_requirements: list[TechnicalRequirement] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    has_more: bool = False


class AdvisoryAnalysis(_Schema):
    """Stage 2 output: recommendations derived from validated findings."""

    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    solution_recommendations: SolutionRecommendations
    complexity_assessment: ComplexityAssessment
    limitations: list[str] = Field(default_factory=list)


class SummaryAdvisory(AdvisoryAnalysis):
    """Stage 2 output for long documents: summary plus advisory sections."""

    executive_summary: ExecutiveSummary


class DocumentAnalysis(_Schema):
    executive_summary: ExecutiveSummary
    functional_requirements: list[Requirement] = Field(default_factory=list)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    technical_requirements: list[TechnicalRequirement] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    solution_recommendations: SolutionRecommendations
    complexity_assessment: ComplexityAssessment
    limitations: list[str] = Field(default_factory=list)
    document_filename: str = ""
    analysis_date: date | None = None


class CitationCheck(_Schema):
    check_id: str
    item_kind: str
    item_id: str
    source_page: int | None
    verified: bool
    reason: str


class EvidenceAudit(_Schema):
    checks: list[CitationCheck]
    total: int
    verified: int
    verification_rate: float


class TokenUsage(_Schema):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )
