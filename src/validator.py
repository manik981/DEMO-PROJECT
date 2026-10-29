"""Post-processing: de-duplication, ID hygiene and citation/evidence auditing.

The audit is deliberately lightweight and lexical. It catches fabricated page
numbers and evidence that is not traceable to the page text, but it cannot prove
semantic correctness. Flagged items are surfaced for human review.
"""

from __future__ import annotations

import re

from .document_processor import ExtractedDocument
from .schemas import (
    NOT_FOUND,
    CitationCheck,
    DocumentAnalysis,
    EvidenceAudit,
)

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "will",
    "shall", "must", "should", "have", "has", "been", "being", "into", "not", "but",
    "all", "any", "can", "may", "their", "its", "our", "you", "your", "they", "them",
    "which", "when", "where", "who", "what", "how", "per", "via", "than", "then",
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _dedupe(items: list, key: str | Callable[[object], str]) -> list:
    seen: set[str] = set()
    unique = []
    for item in items:
        value = key(item) if callable(key) else getattr(item, key)
        normalized = _normalise(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(item)
    return unique


def _unique_ids(items: list, prefix: str) -> list:
    seen: dict[str, int] = {}
    for index, item in enumerate(items, start=1):
        item_id = (item.id or "").strip() or f"{prefix}-{index:02d}"
        if item_id in seen:
            seen[item_id] += 1
            item_id = f"{item_id}-{seen[item_id]}"
        else:
            seen[item_id] = 1
        item.id = item_id
    return items


def normalize_analysis(analysis: DocumentAnalysis) -> DocumentAnalysis:
    """Remove exact duplicates and guarantee unique IDs. No semantic rewriting."""
    analysis.functional_requirements = _unique_ids(
        _dedupe(analysis.functional_requirements, "description"), "FR"
    )
    analysis.non_functional_requirements = _unique_ids(
        _dedupe(analysis.non_functional_requirements, "description"), "NFR"
    )
    analysis.technical_requirements = _unique_ids(
        _dedupe(
            analysis.technical_requirements,
            lambda item: f"{item.technology}|{item.status.value}",
        ),
        "TR",
    )
    analysis.missing_information = _unique_ids(
        _dedupe(analysis.missing_information, "topic"), "MI"
    )
    analysis.ambiguities = _unique_ids(_dedupe(analysis.ambiguities, "description"), "AM")
    analysis.risks = _unique_ids(_dedupe(analysis.risks, "description"), "RK")
    analysis.clarification_questions = _unique_ids(
        _dedupe(analysis.clarification_questions, "question"), "CQ"
    )
    return analysis


def _evidence_traceable(evidence: str, source_text: str) -> bool:
    """Check that evidence words actually appear in the source text (lexical only)."""
    if not evidence or evidence.strip() == NOT_FOUND:
        return False
    evidence_norm = _normalise(evidence)
    source_norm = _normalise(source_text)
    if not evidence_norm or not source_norm:
        return False
    if len(evidence_norm) >= 12 and evidence_norm in source_norm:
        return True
    tokens = {token for token in evidence_norm.split() if len(token) >= 3 and token not in _STOPWORDS}
    if not tokens:
        return evidence_norm in source_norm
    source_tokens = set(source_norm.split())
    matched = sum(1 for token in tokens if token in source_tokens)
    return matched / len(tokens) >= 0.6 and matched >= 2


def _check_item(
    kind: str,
    item_id: str,
    source_page: int | None,
    evidence: str,
    pages: dict[int, str],
    full_text: str,
    page_capable: bool,
) -> CitationCheck:
    check_id = f"{kind}:{item_id}"
    if not evidence or evidence.strip() == NOT_FOUND:
        return CitationCheck(
            check_id=check_id,
            item_kind=kind,
            item_id=item_id,
            source_page=source_page,
            verified=False,
            reason="No supporting evidence supplied; cannot verify this item.",
        )

    if source_page is not None:
        if not page_capable:
            return CitationCheck(
                check_id=check_id,
                item_kind=kind,
                item_id=item_id,
                source_page=source_page,
                verified=False,
                reason="A page number was cited but this file format has no page metadata.",
            )
        if source_page not in pages:
            return CitationCheck(
                check_id=check_id,
                item_kind=kind,
                item_id=item_id,
                source_page=source_page,
                verified=False,
                reason=f"Cited page {source_page} does not exist in the extracted document.",
            )
        if _evidence_traceable(evidence, pages[source_page]):
            return CitationCheck(
                check_id=check_id,
                item_kind=kind,
                item_id=item_id,
                source_page=source_page,
                verified=True,
                reason=f"Evidence matched page {source_page} text.",
            )
        elsewhere = _evidence_traceable(evidence, full_text)
        return CitationCheck(
            check_id=check_id,
            item_kind=kind,
            item_id=item_id,
            source_page=source_page,
            verified=False,
            reason=(
                f"Evidence was not found on cited page {source_page}."
                + (" It does appear elsewhere in the document; the page citation may be wrong." if elsewhere else "")
            ),
        )

    traceable = _evidence_traceable(evidence, full_text)
    if not page_capable:
        return CitationCheck(
            check_id=check_id,
            item_kind=kind,
            item_id=item_id,
            source_page=None,
            verified=traceable,
            reason=(
                "No page metadata for this format; evidence traced to full document text."
                if traceable
                else "No page metadata and evidence could not be matched to the document text."
            ),
        )
    return CitationCheck(
        check_id=check_id,
        item_kind=kind,
        item_id=item_id,
        source_page=None,
        verified=False,
        reason=(
            "No page cited; evidence matched the full document but the page is unverified."
            if traceable
            else "No page cited and evidence could not be matched to the document text."
        ),
    )


def verify_citations(analysis: DocumentAnalysis, document: ExtractedDocument) -> EvidenceAudit:
    """Verify cited page existence and lexical traceability of supporting evidence."""
    pages = document.page_map()
    page_capable = bool(pages)
    full_text = document.full_text

    targets: list[tuple[str, object]] = []
    targets += [("functional_requirement", item) for item in analysis.functional_requirements]
    targets += [("non_functional_requirement", item) for item in analysis.non_functional_requirements]
    targets += [("technical_requirement", item) for item in analysis.technical_requirements]
    targets += [("ambiguity", item) for item in analysis.ambiguities]
    targets += [("risk", item) for item in analysis.risks]

    checks = [
        _check_item(
            kind,
            item.id,
            getattr(item, "source_page", None),
            getattr(item, "evidence", ""),
            pages,
            full_text,
            page_capable,
        )
        for kind, item in targets
    ]
    total = len(checks)
    verified = sum(1 for check in checks if check.verified)
    return EvidenceAudit(
        checks=checks,
        total=total,
        verified=verified,
        verification_rate=round(verified / total, 3) if total else 0.0,
    )


def flagged_checks(audit: EvidenceAudit) -> list[CitationCheck]:
    return [check for check in audit.checks if not check.verified]
