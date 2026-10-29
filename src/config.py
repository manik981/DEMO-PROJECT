"""Application configuration loaded from environment variables / .env.

Secrets are read once and never logged or rendered in the UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
DEFAULT_MODEL = "agnes-2.5-flash"
DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Tests construct this directly instead of using env vars."""

    api_key: str | None
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    max_upload_mb: float = 10.0
    max_document_chars: int = 120_000
    direct_analysis_chars: int = 24_000
    chunk_chars: int = 12_000
    chunk_overlap_chars: int = 800
    max_chunks: int = 8
    max_output_tokens: int = 16_000
    max_request_tokens: int = 64_000
    max_findings_per_category: int = 10
    request_timeout_seconds: float = 90.0
    # The provider's per-minute token window can be shorter than one analysis,
    # so the second stage may need to wait before it can run.
    max_retries: int = 3
    temperature: float = 0.1

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    @property
    def safe_model_name(self) -> str:
        return self.model


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(minimum, min(maximum, int(raw)))
    except ValueError:
        return default


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(minimum, min(maximum, float(raw)))
    except ValueError:
        return default


def _streamlit_secret(name: str) -> str | None:
    """Streamlit Community Cloud exposes secrets via st.secrets, not env vars."""
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:  # no secrets file, or running outside Streamlit
        return None
    return str(value) if value else None


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from `.env` (if present) and the process environment."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    api_key = (os.getenv("AGNES_API_KEY") or _streamlit_secret("AGNES_API_KEY") or "").strip() or None
    model = os.getenv("AGNES_MODEL", "").strip() or _streamlit_secret("AGNES_MODEL") or DEFAULT_MODEL
    base_url = (
        os.getenv("AGNES_BASE_URL", "").strip() or _streamlit_secret("AGNES_BASE_URL") or DEFAULT_BASE_URL
    )
    return Settings(
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_upload_mb=_float_env("MAX_UPLOAD_MB", 10.0, 0.1, 100.0),
        max_document_chars=_int_env("MAX_DOCUMENT_CHARS", 120_000, 5_000, 400_000),
        direct_analysis_chars=_int_env("DIRECT_ANALYSIS_CHARS", 24_000, 2_000, 60_000),
        chunk_chars=_int_env("CHUNK_CHARS", 12_000, 2_000, 30_000),
        chunk_overlap_chars=_int_env("CHUNK_OVERLAP_CHARS", 800, 0, 5_000),
        max_chunks=_int_env("MAX_CHUNKS", 8, 1, 20),
        max_output_tokens=_int_env("MAX_OUTPUT_TOKENS", 16_000, 512, 65_536),
        # Agnes 2.5 Flash: 512K context window, 65,536 max output tokens.
        max_request_tokens=_int_env("MAX_REQUEST_TOKENS", 64_000, 1_000, 200_000),
        max_findings_per_category=_int_env("MAX_FINDINGS_PER_CATEGORY", 10, 3, 50),
        request_timeout_seconds=_float_env("REQUEST_TIMEOUT_SECONDS", 90.0, 10.0, 300.0),
        max_retries=_int_env("MAX_RETRIES", 3, 0, 4),
        temperature=_float_env("TEMPERATURE", 0.1, 0.0, 1.0),
    )
