"""Markdown and JSON report generation from validated analysis results."""

from __future__ import annotations

import json
import re
from datetime import date

from .analyzer import AnalysisResult
from .schemas import DocumentAnalysis

_KIND_LABELS = {
    "explicit": "Explicit (client stated)",
    "recommended": "AI recommendation (not client-stated)",
    "explicitly_specified": "Explicitly specified",
    "suggested": "Suggested by document",
    "not_specified": "Not specified",
    "source_supported": "Source-supported",
    "inferred": "AI inference",
    "confirmed": "Confirmed in document",
    "possible": "Possible - needs verification",
}


def _cell(value: object) -> str:
    if value is None or value == "":
        return "Not found in supplied document"
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _source(page: int | None, section: str | None = None) -> str:
    parts = []
    if page is not None:
        parts.append(f"Page {page}")
    if section:
        parts.append(section)
    return ", ".join(parts) if parts else "Not found in supplied document"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "_No items identified in the supplied document._"
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join(lines)


def _bullets(items: list[str]) -> str:
    if not items:
        return "_None recorded._"
    return "\n".join(f"- {item}" for item in items)


def build_markdown_report(result: AnalysisResult) -> str:
    """Build a self-contained Markdown report from actual validated data."""
    a: DocumentAnalysis = result.analysis
    generated = (a.analysis_date or date.today()).isoformat()
    s = a.executive_summary

    lines: list[str] = [
        f"# {s.project_title} - AI Proposal Analysis",
        "",
        "**Independent AI/ML Assessment Prototype - not an official Cynbit product.**",
        "",
        f"- **Analysis date:** {generated}",
        f"- **Document:** {_cell(a.document_filename)}",
        f"- **Analysis mode:** {result.mode} ({result.chunks_analyzed} section(s))",
        f"- **Model:** {result.model}",
        f"- **Evidence traceability:** {result.evidence.verified}/{result.evidence.total} citations verified "
        f"({result.evidence.verification_rate:.0%})",
        "",
        "---",
        "",
        "## 1. Executive summary",
        "",
        f"**Project overview:** {s.project_overview}",
        "",
        f"**Business objective:** {s.business_objective}",
        "",
        f"**Intended users:** {', '.join(s.intended_users) if s.intended_users else 'Not found in supplied document'}",
        "",
        f"**Project category:** {s.project_category}",
        "",
        f"**Overall complexity:** {s.overall_complexity.value}",
        "",
        f"**Complexity rationale:** {s.complexity_rationale}",
        "",
        "## 2. Functional requirements",
        "",
        _table(
            ["ID", "Requirement", "Category", "Priority", "Source", "Evidence", "Confidence", "Basis"],
            [
                [
                    r.id,
                    r.description,
                    r.category,
                    r.priority.value,
                    _source(r.source_page, r.source_section),
                    r.evidence,
                    r.confidence.value,
                    _KIND_LABELS.get(r.origin.value, r.origin.value),
                ]
                for r in a.functional_requirements
            ],
        ),
        "",
        "## 3. Non-functional requirements",
        "",
        _table(
            ["ID", "Category", "Requirement", "Status", "Priority", "Source", "Evidence", "Confidence"],
            [
                [
                    r.id,
                    r.category.value.title(),
                    r.description,
                    _KIND_LABELS.get(r.status.value, r.status.value),
                    r.priority.value,
                    _source(r.source_page),
                    r.evidence,
                    r.confidence.value,
                ]
                for r in a.non_functional_requirements
            ],
        ),
        "",
        "## 4. Technical requirements",
        "",
        _table(
            ["ID", "Technology / need", "Category", "Status", "Source", "Evidence", "Notes"],
            [
                [
                    t.id,
                    t.technology,
                    t.category.value.title(),
                    _KIND_LABELS.get(t.status.value, t.status.value),
                    _source(t.source_page),
                    t.evidence,
                    t.notes,
                ]
                for t in a.technical_requirements
            ],
        ),
        "",
        "## 5. Missing information",
        "",
        _table(
            ["ID", "Topic", "Why it matters", "Priority", "Potential impact"],
            [[m.id, m.topic, m.why_it_matters, m.priority.value, m.potential_impact] for m in a.missing_information],
        ),
        "",
        "## 6. Ambiguities and contradictions",
        "",
        _table(
            ["ID", "Type", "Description", "Status", "Source", "Evidence"],
            [
                [
                    x.id,
                    x.kind.value.replace("_", " ").title(),
                    x.description,
                    _KIND_LABELS.get(x.status.value, x.status.value),
                    _source(x.source_page),
                    x.evidence,
                ]
                for x in a.ambiguities
            ],
        ),
        "",
        "## 7. Risk analysis",
        "",
        _table(
            ["ID", "Risk", "Category", "Severity", "Basis", "Source", "Reason", "Evidence", "Mitigation"],
            [
                [
                    r.id,
                    r.description,
                    r.category.value.title(),
                    r.severity.value,
                    _KIND_LABELS.get(r.basis.value, r.basis.value),
                    _source(r.source_page),
                    r.reason,
                    r.evidence,
                    r.mitigation,
                ]
                for r in a.risks
            ],
        ),
        "",
        "## 8. Client clarification questions",
        "",
        _table(
            ["ID", "Question", "Why it matters", "Priority", "Related to"],
            [[q.id, q.question, q.why_it_matters, q.priority.value, q.related_to] for q in a.clarification_questions],
        ),
        "",
        "## 9. Solution recommendations",
        "",
        "> All architecture, technology and phase proposals below are AI recommendations, "
        "not confirmed client requirements.",
        "",
        "### Potential architecture",
        "",
        a.solution_recommendations.potential_architecture,
        "",
        "### Technology options",
        "",
        _table(
            ["Option", "Reason"],
            [[t.name, t.reason] for t in a.solution_recommendations.technology_options],
        ),
        "",
        "### Integration considerations",
        "",
        _bullets(a.solution_recommendations.integration_considerations),
        "",
        "### Security recommendations",
        "",
        _bullets(a.solution_recommendations.security_recommendations),
        "",
        "### Implementation phases",
        "",
        _table(
            ["Phase", "Scope", "Deliverables"],
            [
                [p.name, p.scope, "; ".join(p.deliverables) if p.deliverables else "Not specified"]
                for p in a.solution_recommendations.implementation_phases
            ],
        ),
        "",
        "### Dependencies and assumptions",
        "",
        _bullets(a.solution_recommendations.dependencies_and_assumptions),
        "",
        "## 10. Complexity assessment",
        "",
        f"**Level:** {a.complexity_assessment.level.value}",
        "",
        "**Reasons:**",
        "",
        _bullets(a.complexity_assessment.reasons),
        "",
        "**Complexity drivers:**",
        "",
        _bullets(a.complexity_assessment.complexity_drivers),
        "",
        "**Major unknowns:**",
        "",
        _bullets(a.complexity_assessment.major_unknowns),
        "",
        "## 11. Source evidence audit",
        "",
        f"{result.evidence.verified} of {result.evidence.total} evidence checks passed "
        f"({result.evidence.verification_rate:.0%} traceability).",
        "",
        "The audit checks that cited pages exist and that evidence words occur in the cited page text. "
        "It is a lexical check, not a semantic guarantee. All flagged items require human review.",
        "",
    ]
    flagged = [check for check in result.evidence.checks if not check.verified]
    if flagged:
        lines += [
            _table(
                ["Check", "Item", "Page", "Reason"],
                [[c.check_id, c.item_id, c.source_page, c.reason] for c in flagged],
            ),
            "",
        ]
    else:
        lines += ["All generated citations passed the lightweight verification check.", ""]

    if result.warnings:
        lines += ["## 12. Processing warnings", ""]
        lines += [f"- {warning}" for warning in result.warnings]
        lines.append("")

    lines += [
        "## 13. Limitations and human review",
        "",
        _bullets(a.limitations),
        "",
        "- This report was generated by an AI model from the supplied document only. It may omit context "
        "that the document does not contain.",
        "- Requirements, priorities, risks and recommendations must be validated by a business analyst, "
        "solution architect and the client before use in a proposal or estimate.",
        "- Reliable cost, timeline, team-size and ROI estimates require additional information and human review. "
        "This report deliberately does not invent them.",
        "- The evidence audit verifies page existence and lexical traceability only; it does not prove that "
        "an interpretation is correct.",
        "",
        f"_Generated by Cynbit AI Proposal Analyst (independent prototype) on {generated}._",
    ]
    return "\n".join(lines)


def build_json_report(result: AnalysisResult) -> str:
    return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)


def safe_report_stem(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.rsplit(".", 1)[0]).strip("._-") or "document"
    return f"{stem}_cynbit_analysis_{(date.today()).isoformat()}"
