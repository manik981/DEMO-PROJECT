"""Small, Streamlit-free UI predicates so the guards can be unit tested."""

from __future__ import annotations


def can_start_analysis(*, configured: bool, has_document: bool, running: bool) -> bool:
    """An analysis needs a key, a parsed document, and no run already in flight."""
    return configured and has_document and not running
