import pytest

from src.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        api_key="test-key-not-real",
        model="agnes-2.5-flash",
        base_url="https://apihub.agnes-ai.com/v1",
        max_upload_mb=10,
        max_document_chars=120_000,
        direct_analysis_chars=100_000,
        chunk_chars=12_000,
        chunk_overlap_chars=800,
        max_chunks=8,
        max_output_tokens=1024,
        request_timeout_seconds=5,
        max_retries=2,
        temperature=0.1,
    )


@pytest.fixture
def unconfigured_settings() -> Settings:
    return Settings(api_key=None, max_output_tokens=1024, max_retries=0)
