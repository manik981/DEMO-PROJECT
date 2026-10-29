"""Cynbit AI Proposal Analyst - Streamlit application."""

from __future__ import annotations

import hashlib
from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from src.analyzer import AnalysisError, AnalysisResult, analyze_document
from src.config import Settings, load_settings
from src.document_processor import (
    DocumentError,
    ExtractedDocument,
    extract_document,
    validate_upload,
)
from src.report_export import build_json_report, build_markdown_report, safe_report_stem
from src.ui_state import can_start_analysis
from src.schemas import CitationCheck
from src.validator import flagged_checks

st.set_page_config(
    page_title="Cynbit AI Proposal Analyst",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,500&display=swap');

:root {
  --navy: #0D1B2A;
  --navy-2: #1B263B;
  --canvas: #F8F7F4;
  --surface: #FFFFFF;
  --line: #E5E1D8;
  --muted: #4E5D6C;
  --accent: #3D5A78;
  --accent-soft: #778DA9;
}

html, body, .stApp {
  background: var(--canvas) !important;
  color: var(--navy);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { visibility: hidden; }
#MainMenu, footer { visibility: hidden; }
.block-container { max-width: 1180px; padding: 2.2rem 2rem 4rem; }

h1, h2, h3, h4 { color: var(--navy) !important; letter-spacing: -0.02em; }
p, li, label, .stMarkdown { color: var(--navy); }
a { color: var(--accent); }

/* Streamlit keeps the sidebar dark in dark-mode browsers; the global text colour
   above would make its copy unreadable, so give the sidebar its own palette. */
[data-testid="stSidebar"] { background: var(--navy) !important; }
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #D5DDE7 !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4 { color: #FFFFFF !important; }
[data-testid="stSidebar"] .cb-section-label { color: #9FB0C2; }
[data-testid="stSidebar"] code { color: #FFFFFF; background: rgba(255,255,255,.09); }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.14); }

.cb-header { padding: 1.4rem 0 1.7rem; border-bottom: 1px solid var(--line); margin-bottom: 1.6rem; }
.cb-eyebrow {
  font-size: .68rem; letter-spacing: .16em; text-transform: uppercase;
  color: var(--accent); font-weight: 600; margin-bottom: .7rem;
}
.cb-header h1 {
  font-family: "Source Serif 4", Georgia, serif;
  font-size: 2.55rem; font-weight: 500; line-height: 1.1; margin: 0 0 .55rem;
}
.cb-header p { color: var(--muted); font-size: 1.02rem; margin: 0; max-width: 48rem; }

.cb-section-label {
  font-size: .7rem; letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted); font-weight: 600; margin: 0 0 .55rem;
}
.cb-card {
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 1.15rem 1.25rem; margin-bottom: 1rem;
}
.cb-card h3 { font-size: 1rem; margin: 0 0 .45rem; }
.cb-card p { color: var(--muted); font-size: .88rem; margin: 0; line-height: 1.55; }

.cb-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .8rem; margin: .4rem 0 1.3rem; }
.cb-metric {
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 1rem 1.05rem;
}
.cb-metric-value { font-family: "Source Serif 4", Georgia, serif; font-size: 1.9rem; line-height: 1; color: var(--navy); }
.cb-metric-label { font-size: .74rem; color: var(--muted); margin-top: .45rem; letter-spacing: .01em; }

.cb-doc {
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 1rem 1.15rem; display: flex; justify-content: space-between; gap: 1rem;
  align-items: center; margin-bottom: 1rem;
}
.cb-doc-name { font-weight: 600; font-size: .95rem; color: var(--navy); }
.cb-doc-meta { color: var(--muted); font-size: .8rem; margin-top: .2rem; }
.cb-chip {
  display: inline-block; border: 1px solid var(--line); background: #FBFAF7;
  color: var(--muted); border-radius: 999px; padding: .2rem .6rem;
  font-size: .72rem; margin: 0 .35rem .35rem 0;
}

.cb-note { color: var(--muted); font-size: .8rem; line-height: 1.55; }
.cb-disclaimer {
  border-top: 1px solid var(--line); margin-top: 2.5rem; padding-top: 1rem;
  color: var(--muted); font-size: .76rem; line-height: 1.6;
}

[data-testid="stFileUploaderDropzone"] {
  background: var(--surface); border: 1px dashed #C9C3B7; border-radius: 12px;
  padding: 1.4rem;
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--accent-soft); }

/* The dark theme draws the uploaded-file chip near-black with mixed inherited
   ink. Keep it on the app's light surface with navy content. */
[data-testid="stMain"] [data-testid="stFileChip"] {
  background: var(--surface) !important; border: 1px solid var(--line);
}
[data-testid="stMain"] [data-testid="stFileChip"] *,
[data-testid="stMain"] [data-testid="stFileChips"] [data-testid="stBaseButton-borderlessIcon"] * {
  color: var(--navy) !important;
}

.stButton > button, .stDownloadButton > button {
  border-radius: 8px; border: 1px solid #CFC9BD; font-weight: 500;
  transition: none; box-shadow: none;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: var(--navy); color: #FFFFFF; border-color: var(--navy);
}
.stButton > button[kind="primary"]:hover { background: var(--navy-2); border-color: var(--navy-2); }
/* Streamlit nests button labels in a <p>, which the global p rule paints navy
   on the primary button's navy surface. Force white for every descendant. */
[data-testid="stMain"] [data-testid="stBaseButton-primary"],
[data-testid="stMain"] [data-testid="stBaseButton-primary"] * { color: #FFFFFF !important; }

/* Streamlit's dark theme gives secondary buttons a near-black surface while the
   app's global ink is navy, which makes the uploader's "Upload" label invisible.
   Keep those controls dark and force white text (including the hover state). */
[data-testid="stMain"] .stButton > button[kind="secondary"],
[data-testid="stMain"] .stDownloadButton > button[kind="secondary"],
[data-testid="stMain"] [data-testid="stBaseButton-secondary"] {
  background: var(--navy) !important; color: #FFFFFF !important;
  border-color: var(--navy) !important;
}
[data-testid="stMain"] .stButton > button[kind="secondary"]:hover,
[data-testid="stMain"] .stDownloadButton > button[kind="secondary"]:hover,
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:hover {
  background: var(--navy-2) !important; color: #FFFFFF !important;
  border-color: var(--navy-2) !important;
}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"] * { color: #FFFFFF !important; }
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}

.stTabs [data-baseweb="tab-list"] {
  gap: 1.4rem; border-bottom: 1px solid var(--line); padding-bottom: 0;
}
.stTabs [data-baseweb="tab"] {
  height: 2.6rem; padding: 0; background: transparent; color: var(--muted);
  font-size: .85rem; font-weight: 500;
}
.stTabs [aria-selected="true"] { color: var(--navy) !important; border-bottom: 2px solid var(--navy); }
.stTabs [data-baseweb="tab-highlight"] { background: transparent; }

[data-testid="stExpander"] {
  border: 1px solid var(--line); border-radius: 10px; background: var(--surface);
}
/* st.status is an expander. Streamlit's dark theme paints its <summary> dark,
   while the app's global text colour is navy: dark-on-dark. Force the app's
   light surface + ink for the header and body. */
[data-testid="stExpander"] summary {
  font-size: .86rem; color: var(--navy) !important;
  background: var(--surface) !important; border-radius: 10px;
}
[data-testid="stExpander"] summary p { color: var(--navy) !important; }
[data-testid="stExpander"] [data-testid="stExpanderDetails"] { background: var(--surface); }
/* Dark-theme spans (st.text preview, status lines) stay white inside the light
   expander body. Force the app ink on the body's text nodes. */
[data-testid="stExpander"] [data-testid="stExpanderDetails"] p,
[data-testid="stExpander"] [data-testid="stExpanderDetails"] span,
[data-testid="stMain"] [data-testid="stText"],
[data-testid="stMain"] [data-testid="stText"] span { color: var(--navy) !important; }
[data-testid="stStatusWidget"] p,
[data-testid="stStatusWidget"] span,
[data-testid="stStatusWidget"] label { color: var(--navy) !important; }

/* Alerts inside the light main column get light-theme colours. Without this,
   the global p rule overrides Streamlit's alert ink and the dark-theme pastel
   text lands on the light canvas. Sidebar alerts keep their dark styling. */
[data-testid="stMain"] [data-testid="stAlertContainer"] { border: 1px solid transparent; }
[data-testid="stMain"] [data-testid="stAlertContainer"] p,
[data-testid="stMain"] [data-testid="stAlertContainer"] li,
[data-testid="stMain"] [data-testid="stAlertContainer"] .stMarkdown { color: inherit !important; }
[data-testid="stMain"] [data-testid="stAlertContentError"] { color: #8A1C1C !important; }
[data-testid="stMain"] [data-testid="stAlertContentWarning"] { color: #6B4700 !important; }
[data-testid="stMain"] [data-testid="stAlertContentInfo"] { color: #1F3A57 !important; }
[data-testid="stMain"] [data-testid="stAlertContentSuccess"] { color: #1E4D36 !important; }
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
  background: #FDECEC !important; border-color: #E0B4B4;
}
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {
  background: #FFF6E0 !important; border-color: #E4C98F;
}
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {
  background: #EAF2FB !important; border-color: #B7CCE3;
}
[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
  background: #EAF5EE !important; border-color: #B2D5C1;
}
[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
[data-testid="stAlert"] { border-radius: 10px; }
hr { border-color: var(--line); }

@media (max-width: 760px) {
  .block-container { padding: 1.2rem 1rem 3rem; }
  .cb-header h1 { font-size: 2rem; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def _init_state() -> None:
    defaults = {
        "uploader_key": 0,
        "document": None,
        "file_digest": None,
        "result": None,
        "extraction_error": None,
        "analysis_error": None,
        "analysis_running": False,
        "upload_meta": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_all() -> None:
    st.session_state.document = None
    st.session_state.file_digest = None
    st.session_state.result = None
    st.session_state.extraction_error = None
    st.session_state.analysis_error = None
    st.session_state.analysis_running = False
    st.session_state.upload_meta = None
    st.session_state.uploader_key += 1


def _source_label(page: int | None, section: str | None = None) -> str:
    if page is not None:
        return f"Page {page}" + (f" · {section}" if section else "")
    return section or "Not found"


def _audit_lookup(result: AnalysisResult) -> dict[str, CitationCheck]:
    return {check.check_id: check for check in result.evidence.checks}


_EVIDENCE_FIELDS = {
    "functional_requirement": "functional_requirements",
    "non_functional_requirement": "non_functional_requirements",
    "technical_requirement": "technical_requirements",
    "ambiguity": "ambiguities",
    "risk": "risks",
}


def _check_evidence(result: AnalysisResult, check: CitationCheck) -> str:
    """Resolve the quoted evidence for a citation check, when it still exists."""
    items = getattr(result.analysis, _EVIDENCE_FIELDS.get(check.item_kind, ""), [])
    for item in items:
        if item.id == check.item_id:
            return getattr(item, "evidence", "") or "Not recorded"
    return "Not recorded"


def _evidence_flag(audit: dict[str, CitationCheck], kind: str, item_id: str) -> str:
    check = audit.get(f"{kind}:{item_id}")
    if check is None:
        return "Not checked"
    return "Verified" if check.verified else "Flagged"


def _render_metric_grid(result: AnalysisResult) -> None:
    metrics = [
        (len(result.analysis.functional_requirements), "Functional requirements"),
        (len(result.analysis.non_functional_requirements), "Non-functional requirements"),
        (len(result.analysis.risks), "Risks identified"),
        (len(result.analysis.missing_information), "Missing information items"),
        (len(result.analysis.clarification_questions), "Clarification questions"),
    ]
    cells = "".join(
        f'<div class="cb-metric"><div class="cb-metric-value">{value}</div>'
        f'<div class="cb-metric-label">{label}</div></div>'
        for value, label in metrics
    )
    st.markdown(f'<div class="cb-metrics">{cells}</div>', unsafe_allow_html=True)


def _render_header() -> None:
    st.markdown(
        """
        <div class="cb-header">
          <div class="cb-eyebrow">Independent AI/ML Assessment Prototype</div>
          <h1>Cynbit AI Proposal Analyst</h1>
          <p>Turn complex client requirements into actionable project intelligence.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar(settings: Settings) -> None:
    with st.sidebar:
        st.markdown('<div class="cb-section-label">Configuration</div>', unsafe_allow_html=True)
        st.caption(f"Model: `{settings.model}`")
        st.caption(f"Upload limit: {settings.max_upload_mb:.0f} MB")
        st.caption(f"Chunk limit: {settings.max_chunks} sections")
        if settings.is_configured:
            st.success("Agnes API key configured", icon="✅")
        else:
            st.warning("Agnes API key not configured")

        st.divider()
        st.markdown('<div class="cb-section-label">How it works</div>', unsafe_allow_html=True)
        st.caption(
            "1. Text is extracted in memory with page references.\n\n"
            "2. Short documents are analyzed directly; long documents use bounded "
            "section extraction and consolidation.\n\n"
            "3. Responses are validated with Pydantic, then citations are checked "
            "against the extracted page text."
        )
        st.divider()
        st.markdown('<div class="cb-section-label">Privacy</div>', unsafe_allow_html=True)
        st.caption(
            "Extracted text is sent to Agnes for inference. This app does not write "
            "uploads or reports to disk. Do not upload material you are not permitted "
            "to share with a third-party model provider."
        )
        st.divider()
        st.caption(
            "Independent prototype proposed for Cynbit. Not an official Cynbit product "
            "and not affiliated with or endorsed by Cynbit."
        )


def _handle_upload(settings: Settings) -> None:
    uploaded = st.file_uploader(
        "Upload a client RFP",
        type=["pdf", "docx", "txt"],
        help="Text-based PDF, DOCX or TXT. Scanned PDFs require OCR, which this MVP does not support.",
        key=f"uploader_{st.session_state.uploader_key}",
        max_upload_size=int(settings.max_upload_mb),
    )
    if uploaded is None:
        return

    data = uploaded.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if digest == st.session_state.file_digest:
        return

    st.session_state.file_digest = digest
    st.session_state.document = None
    st.session_state.result = None
    st.session_state.extraction_error = None
    st.session_state.analysis_error = None
    st.session_state.upload_meta = None

    try:
        validate_upload(uploaded.name, len(data), settings.max_upload_bytes)
        st.session_state.document = extract_document(data, uploaded.name, settings.max_document_chars)
        st.session_state.upload_meta = {"name": uploaded.name, "size": len(data)}
    except DocumentError as exc:
        st.session_state.extraction_error = str(exc)
    except Exception:
        st.session_state.extraction_error = (
            "The document could not be processed. It may be corrupted or use an unsupported encoding."
        )


def _render_document_card(document: ExtractedDocument, meta: dict) -> None:
    pages = f"{document.page_count} pages" if document.page_count else "No page metadata"
    st.markdown(
        f"""
        <div class="cb-doc">
          <div>
            <div class="cb-doc-name">{escape(document.filename)}</div>
            <div class="cb-doc-meta">{meta["size"] / 1024:.0f} KB · {pages} · {document.char_count:,} characters extracted</div>
          </div>
          <div class="cb-chip">{escape(document.file_type.upper())}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_upload_screen(settings: Settings) -> None:
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.markdown('<div class="cb-section-label">Document intake</div>', unsafe_allow_html=True)
        _handle_upload(settings)
        st.caption(
            "Supported: PDF, DOCX, TXT · Maximum 10 MB (configurable) · Text-based documents only. "
            "Scanned PDFs are detected and rejected because OCR is not supported."
        )

        if st.session_state.extraction_error:
            st.error(st.session_state.extraction_error)
        elif st.session_state.document is not None:
            _render_document_card(st.session_state.document, st.session_state.upload_meta)
            for warning in st.session_state.document.warnings:
                st.warning(warning)
            with st.expander("Preview extracted text", expanded=False):
                preview = st.session_state.document.full_text[:12000]
                st.text(preview + ("\n\n[Preview truncated]" if len(st.session_state.document.full_text) > 12000 else ""))
            if st.session_state.document.truncated:
                st.info(
                    f"Only the first {settings.max_document_chars:,} characters will be analyzed. "
                    "Upload a smaller document for complete coverage."
                )

            if not settings.is_configured:
                st.error(
                    "AGNES_API_KEY is not configured. Copy `.env.example` to `.env`, add your key, "
                    "and restart the app before running an analysis."
                )
            analyze = st.button(
                "Analyze RFP",
                type="primary",
                disabled=not can_start_analysis(
                    configured=settings.is_configured,
                    has_document=True,
                    running=st.session_state.analysis_running,
                ),
                width="stretch",
            )
            if analyze:
                _run_analysis(settings)

            if st.session_state.analysis_error:
                st.error(st.session_state.analysis_error)
                st.caption("No analysis was produced and no partial result was saved.")

    with right:
        st.markdown('<div class="cb-section-label">What the analysis delivers</div>', unsafe_allow_html=True)
        cards = [
            ("Evidence-backed requirements", "Functional, non-functional and technical needs, each with source page and supporting text."),
            ("Gaps and ambiguities", "Undefined scope, missing operational details and contradictions flagged for clarification."),
            ("Risk and complexity", "Source-supported and inferred risks, with a reasoned complexity assessment."),
            ("Client questions", "Prioritized, non-redundant clarification questions tied to findings."),
            ("Solution direction", "Clearly labelled architecture and technology recommendations, not assumed requirements."),
            ("Exportable report", "Validated Markdown and JSON downloads for review and sharing."),
        ]
        for title, body in cards:
            st.markdown(
                f'<div class="cb-card"><h3>{title}</h3><p>{body}</p></div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<p class="cb-note">AI output is decision support, not a substitute for human review. '
            "This MVP does not estimate cost, team size or delivery dates.</p>",
            unsafe_allow_html=True,
        )


def _run_analysis(settings: Settings) -> None:
    document = st.session_state.document
    if document is None:
        return
    if not can_start_analysis(
        configured=settings.is_configured,
        has_document=True,
        running=st.session_state.analysis_running,
    ):
        st.warning("An analysis is already running. Wait for it to finish.")
        return
    st.session_state.analysis_running = True
    st.session_state.analysis_error = None
    completed = False
    try:
        with st.status("Preparing analysis...", expanded=True) as status:
            try:
                def progress(message: str) -> None:
                    status.write(message)

                result = analyze_document(document, settings, progress=progress)
                st.session_state.result = result
                status.update(label="Analysis complete", state="complete", expanded=False)
                completed = True
            except AnalysisError as exc:
                st.session_state.analysis_error = str(exc)
                status.update(label="Analysis failed", state="error", expanded=True)
            except Exception:
                st.session_state.analysis_error = (
                    "An unexpected error occurred during analysis. No analysis was saved. "
                    "Check the console for diagnostics and try again."
                )
                status.update(label="Analysis failed", state="error", expanded=True)
    finally:
        st.session_state.analysis_running = False
    if completed:
        # The dashboard branch in main() was already evaluated before this button
        # ran, so the stored result would only appear on a later interaction.
        st.rerun()


def _render_overview(result: AnalysisResult) -> None:
    analysis = result.analysis
    summary = analysis.executive_summary
    st.markdown(f"### {summary.project_title}")
    st.write(summary.project_overview)
    st.markdown("**Business objective**")
    st.write(summary.business_objective)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Intended users**")
        users = summary.intended_users or ["Not found in supplied document"]
        st.markdown("\n".join(f"- {user}" for user in users))
    with col2:
        st.markdown("**Category**")
        st.write(summary.project_category)
        st.markdown("**Overall complexity**")
        st.write(summary.overall_complexity.value)

    st.markdown("**Complexity rationale**")
    st.write(summary.complexity_rationale)

    with st.expander("Complexity assessment details", expanded=True):
        st.markdown(f"**Level:** {analysis.complexity_assessment.level.value}")
        for heading, items in (
            ("Reasons", analysis.complexity_assessment.reasons),
            ("Complexity drivers", analysis.complexity_assessment.complexity_drivers),
            ("Major unknowns", analysis.complexity_assessment.major_unknowns),
        ):
            st.markdown(f"**{heading}**")
            if items:
                st.markdown("\n".join(f"- {item}" for item in items))
            else:
                st.caption("None recorded.")

    for warning in result.warnings:
        st.warning(warning)

    st.markdown("---")
    info_cols = st.columns(4)
    info_cols[0].caption("Analysis mode")
    info_cols[0].write(result.mode.title())
    info_cols[1].caption("Sections analyzed")
    info_cols[1].write(str(result.chunks_analyzed))
    info_cols[2].caption("Model")
    info_cols[2].write(result.model)
    info_cols[3].caption("Tokens used")
    info_cols[3].write(f"{result.usage.total_tokens:,}")

    with st.expander("Document limitations", expanded=False):
        if analysis.limitations:
            st.markdown("\n".join(f"- {item}" for item in analysis.limitations))
        else:
            st.caption("No document-specific limitations recorded.")
        st.caption(
            "Reliable cost, timeline, team-size and ROI estimates require additional information and human review. "
            "This report deliberately does not invent them."
        )


def _render_requirements(result: AnalysisResult) -> None:
    analysis = result.analysis
    audit = _audit_lookup(result)

    st.markdown("### Functional requirements")
    rows = [
        {
            "ID": r.id,
            "Requirement": r.description,
            "Category": r.category,
            "Priority": r.priority.value,
            "Source": _source_label(r.source_page, r.source_section),
            "Confidence": r.confidence.value,
            "Basis": "Explicit" if r.origin.value == "explicit" else "AI inference",
            "Evidence check": _evidence_flag(audit, "functional_requirement", r.id),
        }
        for r in analysis.functional_requirements
    ]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Requirement": st.column_config.TextColumn(width="large"),
                "Category": st.column_config.TextColumn(width="small"),
                "Priority": st.column_config.TextColumn(width="small"),
                "Source": st.column_config.TextColumn(width="small"),
                "Confidence": st.column_config.TextColumn(width="small"),
                "Basis": st.column_config.TextColumn(width="small"),
                "Evidence check": st.column_config.TextColumn(width="small"),
            },
        )
        with st.expander("Supporting evidence for each requirement", expanded=False):
            for requirement in analysis.functional_requirements:
                check = audit.get(f"functional_requirement:{requirement.id}")
                st.markdown(f"**{requirement.id}** · {requirement.description}")
                st.caption(f"Evidence: {requirement.evidence}")
                if check:
                    st.caption(f"{'✓ Verified' if check.verified else '⚠ Flagged'} · {check.reason}")
                st.divider()
    else:
        st.info("No functional requirements were identified in the supplied document.")

    st.markdown("### Non-functional requirements")
    st.caption(
        "Items marked **Explicit** are stated by the client. Items marked **AI recommendation** are "
        "recommended by the model because the document omits them; they are not client requirements."
    )
    nfr_rows = [
        {
            "ID": r.id,
            "Category": r.category.value.title(),
            "Requirement": r.description,
            "Status": "Explicit" if r.status.value == "explicit" else "AI recommendation",
            "Priority": r.priority.value,
            "Source": _source_label(r.source_page),
            "Confidence": r.confidence.value,
            "Evidence check": _evidence_flag(audit, "non_functional_requirement", r.id),
        }
        for r in analysis.non_functional_requirements
    ]
    if nfr_rows:
        st.dataframe(pd.DataFrame(nfr_rows), width="stretch", hide_index=True)
    else:
        st.info("No non-functional requirements were identified in the supplied document.")

    with st.expander("Non-functional evidence", expanded=False):
        for requirement in analysis.non_functional_requirements:
            check = audit.get(f"non_functional_requirement:{requirement.id}")
            st.markdown(f"**{requirement.id}** · {requirement.description}")
            st.caption(f"Evidence: {requirement.evidence}")
            if check:
                st.caption(f"{'✓ Verified' if check.verified else '⚠ Flagged'} · {check.reason}")
            st.divider()

    st.markdown("### Requirement metrics")
    total = len(analysis.functional_requirements) + len(analysis.non_functional_requirements)
    high = sum(
        1
        for r in analysis.functional_requirements + analysis.non_functional_requirements
        if r.priority.value == "High"
    )
    st.caption(f"{total} requirements in total · {high} marked High priority · "
               f"{len(analysis.functional_requirements)} functional · {len(analysis.non_functional_requirements)} non-functional")


def _render_technical(result: AnalysisResult) -> None:
    analysis = result.analysis
    audit = _audit_lookup(result)
    st.markdown("### Technical requirements and technologies")
    st.caption(
        "**Explicitly specified** means the client named it. **Suggested by document** means it is implied. "
        "**Not specified** means the document is silent. Inferred technologies are never treated as confirmed requirements."
    )
    rows = [
        {
            "ID": t.id,
            "Technology / need": t.technology,
            "Category": t.category.value.title(),
            "Status": {
                "explicitly_specified": "Explicitly specified",
                "suggested": "Suggested by document",
                "not_specified": "Not specified",
            }[t.status.value],
            "Source": _source_label(t.source_page),
            "Evidence": t.evidence,
            "Notes": t.notes,
            "Evidence check": _evidence_flag(audit, "technical_requirement", t.id),
        }
        for t in analysis.technical_requirements
    ]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Technology / need": st.column_config.TextColumn(width="medium"),
                "Evidence": st.column_config.TextColumn(width="large"),
                "Notes": st.column_config.TextColumn(width="medium"),
            },
        )
    else:
        st.info("No technical requirements or technologies were identified in the supplied document.")

    explicit = sum(1 for t in analysis.technical_requirements if t.status.value == "explicitly_specified")
    st.caption(
        f"{explicit} of {len(analysis.technical_requirements)} technical items are explicitly specified by the client. "
        "Everything else requires confirmation."
    )


def _render_gaps(result: AnalysisResult) -> None:
    analysis = result.analysis
    st.markdown("### Missing information")
    st.caption("A gap is not automatically a defect. Each item explains why the missing detail matters.")
    rows = [
        {
            "ID": m.id,
            "Topic": m.topic,
            "Why it matters": m.why_it_matters,
            "Priority": m.priority.value,
            "Potential impact": m.potential_impact,
        }
        for m in analysis.missing_information
    ]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Why it matters": st.column_config.TextColumn(width="large"),
                "Potential impact": st.column_config.TextColumn(width="medium"),
            },
        )
    else:
        st.info("No missing information was identified.")

    st.markdown("### Ambiguities and contradictions")
    st.caption(
        "**Confirmed** means the document itself shows conflicting statements. "
        "**Possible** means interpretation needs client verification."
    )
    audit = _audit_lookup(result)
    ambiguity_rows = [
        {
            "ID": a.id,
            "Type": a.kind.value.replace("_", " ").title(),
            "Description": a.description,
            "Status": "Confirmed" if a.status.value == "confirmed" else "Possible",
            "Source": _source_label(a.source_page),
            "Evidence": a.evidence,
            "Evidence check": _evidence_flag(audit, "ambiguity", a.id),
        }
        for a in analysis.ambiguities
    ]
    if ambiguity_rows:
        st.dataframe(
            pd.DataFrame(ambiguity_rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Description": st.column_config.TextColumn(width="large"),
                "Evidence": st.column_config.TextColumn(width="large"),
            },
        )
    else:
        st.info("No ambiguities or contradictions were identified.")


def _render_risks(result: AnalysisResult) -> None:
    analysis = result.analysis
    audit = _audit_lookup(result)
    st.markdown("### Risk analysis")
    st.caption(
        "**Source-supported** risks have direct documentary evidence. **AI inference** risks are potential "
        "consequences of gaps or ambiguities and need validation."
    )
    rows = [
        {
            "ID": r.id,
            "Risk": r.description,
            "Category": r.category.value.title(),
            "Severity": r.severity.value,
            "Basis": "Source-supported" if r.basis.value == "source_supported" else "AI inference",
            "Source": _source_label(r.source_page),
            "Reason": r.reason,
            "Evidence": r.evidence,
            "Mitigation": r.mitigation,
            "Evidence check": _evidence_flag(audit, "risk", r.id),
        }
        for r in analysis.risks
    ]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Risk": st.column_config.TextColumn(width="medium"),
                "Reason": st.column_config.TextColumn(width="medium"),
                "Evidence": st.column_config.TextColumn(width="large"),
                "Mitigation": st.column_config.TextColumn(width="medium"),
            },
        )
        high = sum(1 for r in analysis.risks if r.severity.value == "High")
        st.caption(f"{high} High-severity risk(s) of {len(analysis.risks)} total.")
    else:
        st.info("No risks were identified.")


def _render_questions(result: AnalysisResult) -> None:
    analysis = result.analysis
    st.markdown("### Prioritized client clarification questions")
    rows = [
        {
            "ID": q.id,
            "Question": q.question,
            "Why it matters": q.why_it_matters,
            "Priority": q.priority.value,
            "Related to": q.related_to,
        }
        for q in analysis.clarification_questions
    ]
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Question": st.column_config.TextColumn(width="large"),
                "Why it matters": st.column_config.TextColumn(width="large"),
                "Related to": st.column_config.TextColumn(width="small"),
            },
        )
    else:
        st.info("No clarification questions were generated.")

    st.markdown("### Suggested next step")
    st.write(
        "Send the High-priority questions to the client before committing to architecture, scope or delivery dates. "
        "Confirm every inferred requirement in writing."
    )


def _render_recommendations(result: AnalysisResult) -> None:
    recommendations = result.analysis.solution_recommendations
    st.markdown("### Proposed solution direction")
    st.info(
        "These are AI suggestions, not confirmed RFP requirements. Use them as a starting point for discussion."
    )
    st.markdown("**Potential architecture**")
    st.write(recommendations.potential_architecture)

    st.markdown("**Technology options**")
    if recommendations.technology_options:
        st.dataframe(
            pd.DataFrame([{"Option": t.name, "Reason": t.reason} for t in recommendations.technology_options]),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("None proposed.")

    left, right = st.columns(2)
    with left:
        st.markdown("**Integration considerations**")
        items = recommendations.integration_considerations
        st.markdown("\n".join(f"- {item}" for item in items) if items else "_None recorded._")
        st.markdown("**Security recommendations**")
        items = recommendations.security_recommendations
        st.markdown("\n".join(f"- {item}" for item in items) if items else "_None recorded._")
    with right:
        st.markdown("**Dependencies and assumptions**")
        items = recommendations.dependencies_and_assumptions
        st.markdown("\n".join(f"- {item}" for item in items) if items else "_None recorded._")

    st.markdown("**Implementation phases**")
    if recommendations.implementation_phases:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Phase": phase.name,
                        "Scope": phase.scope,
                        "Deliverables": "; ".join(phase.deliverables) if phase.deliverables else "Not specified",
                    }
                    for phase in recommendations.implementation_phases
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("None proposed.")

    st.caption(
        "This MVP does not produce cost estimates, precise timelines, team sizes or ROI figures. "
        "Those require client input and human review."
    )


def _render_evidence(result: AnalysisResult) -> None:
    audit = result.evidence
    st.markdown("### Source evidence audit")
    st.write(
        f"**{audit.verified} of {audit.total}** evidence checks passed the lightweight verification "
        f"({audit.verification_rate:.0%} traceability)."
    )
    st.caption(
        "The check confirms that a cited page exists and that the quoted evidence appears on it. "
        "It is a wording check, not proof that the interpretation is correct. Flagged items require human review."
    )
    unverified = flagged_checks(audit)
    if not audit.checks:
        st.info("No citations were generated, so there was nothing to verify.")
    elif not unverified:
        st.success("All sources were verified successfully.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Item": check.check_id,
                        "Page": check.source_page if check.source_page is not None else "None",
                        "Evidence": _check_evidence(result, check),
                        "Reason": check.reason,
                    }
                    for check in unverified
                ]
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "Evidence": st.column_config.TextColumn(width="large"),
                "Reason": st.column_config.TextColumn(width="large"),
            },
        )

    st.markdown("### Extracted page reference")
    document = st.session_state.document
    if document is not None:
        pages = document.page_map()
        if pages:
            page_number = st.selectbox(
                "Inspect extracted page text",
                options=sorted(pages),
                format_func=lambda n: f"Page {n}",
            )
            st.text(pages[page_number][:6000] or "[No text extracted from this page]")
        else:
            st.caption("This file format has no page metadata. Citations are document-level only.")
            with st.expander("Show extracted text", expanded=False):
                st.text(document.full_text[:6000])

        with st.expander("Extraction warnings", expanded=False):
            if document.warnings:
                for warning in document.warnings:
                    st.warning(warning)
            else:
                st.caption("No extraction warnings.")


def _render_dashboard(settings: Settings) -> None:
    result: AnalysisResult = st.session_state.result
    document: ExtractedDocument = st.session_state.document

    head_left, head_right = st.columns([2.2, 1])
    with head_left:
        st.markdown('<div class="cb-section-label">Analysis dashboard</div>', unsafe_allow_html=True)
        _render_document_card(document, st.session_state.upload_meta)
    with head_right:
        st.write("")
        stem = safe_report_stem(result.analysis.document_filename or "rfp")
        st.download_button(
            "Download Markdown",
            data=build_markdown_report(result),
            file_name=f"{stem}.md",
            mime="text/markdown",
            width="stretch",
        )
        st.download_button(
            "Download JSON",
            data=build_json_report(result),
            file_name=f"{stem}.json",
            mime="application/json",
            width="stretch",
        )

    _render_metric_grid(result)

    action_left, action_mid, action_right = st.columns([1, 1, 2])
    with action_left:
        if st.button("Analyze another document", width="stretch"):
            _reset_all()
            st.rerun()
    with action_mid:
        if st.button("Clear current analysis", width="stretch"):
            st.session_state.result = None
            st.session_state.analysis_error = None
            st.rerun()
    with action_right:
        st.caption(
            f"Analysis date: {(result.analysis.analysis_date or date.today()).isoformat()} · "
            f"{result.mode} mode · {result.usage.total_tokens:,} tokens"
        )

    tabs = st.tabs(
        [
            "Overview",
            "Requirements",
            "Technical Needs",
            "Gaps & Ambiguities",
            "Risks",
            "Client Questions",
            "Recommendations",
            "Source Evidence",
        ]
    )
    with tabs[0]:
        _render_overview(result)
    with tabs[1]:
        _render_requirements(result)
    with tabs[2]:
        _render_technical(result)
    with tabs[3]:
        _render_gaps(result)
    with tabs[4]:
        _render_risks(result)
    with tabs[5]:
        _render_questions(result)
    with tabs[6]:
        _render_recommendations(result)
    with tabs[7]:
        _render_evidence(result)


def main() -> None:
    _init_state()
    settings = load_settings()
    _render_header()
    _render_sidebar(settings)

    if not settings.is_configured:
        st.info(
            "**Configuration required.** Copy `.env.example` to `.env`, set `AGNES_API_KEY` to a valid "
            "Agnes key, and restart the app. You can extract and preview a document without a key, "
            "but analysis is disabled."
        )

    if st.session_state.result is not None and st.session_state.document is not None:
        _render_dashboard(settings)
    else:
        _render_upload_screen(settings)

    st.markdown(
        '<div class="cb-disclaimer">Independent AI/ML assessment prototype proposed for Cynbit. '
        "Not an official Cynbit product. Outputs are AI-generated decision support and require human review. "
        "Citation checks are lexical and do not guarantee correctness.</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
