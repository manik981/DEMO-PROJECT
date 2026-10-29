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
DEFAULT_MODEL = "openai/gpt-oss-120b"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Tests construct this directly instead of using env vars."""

    groq_api_key: str | None
    groq_model: str = DEFAULT_MODEL
    max_upload_mb: float = 10.0
    max_document_chars: int = 120_000
    direct_analysis_chars: int = 24_000
    chunk_chars: int = 12_000
    chunk_overlap_chars: int = 800
    max_chunks: int = 8
    max_output_tokens: int = 8192
    request_timeout_seconds: float = 90.0
    max_retries: int = 2
    temperature: float = 0.1

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def is_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.strip())

    @property
    def safe_model_name(self) -> str:
        return self.groq_model


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


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from `.env` (if present) and the process environment."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    # Streamlit Community Cloud exposes secrets via st.secrets; env remains the primary source.
    api_key = os.getenv("GROQ_API_KEY", "").strip() or None
    model = os.getenv("GROQ_MODEL", "").strip() or DEFAULT_MODEL
    return Settings(
        groq_api_key=api_key,
        groq_model=model,
        max_upload_mb=_float_env("MAX_UPLOAD_MB", 10.0, 0.1, 100.0),
        max_document_chars=_int_env("MAX_DOCUMENT_CHARS", 120_000, 5_000, 400_000),
        direct_analysis_chars=_int_env("DIRECT_ANALYSIS_CHARS", 24_000, 2_000, 60_000),
        chunk_chars=_int_env("CHUNK_CHARS", 12_000, 2_000, 30_000),
        chunk_overlap_chars=_int_env("CHUNK_OVERLAP_CHARS", 800, 0, 5_000),
        max_chunks=_int_env("MAX_CHUNKS", 8, 1, 20),
        max_output_tokens=_int_env("MAX_OUTPUT_TOKENS", 8192, 512, 32_000),
        request_timeout_seconds=_float_env("REQUEST_TIMEOUT_SECONDS", 90.0, 10.0, 300.0),
        max_retries=_int_env("MAX_RETRIES", 2, 0, 4),
        temperature=_float_env("TEMPERATURE", 0.1, 0.0, 1.0),
    )
