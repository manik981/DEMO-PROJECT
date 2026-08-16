"""SQLAlchemy Declarative Models for Supabase PostgreSQL Database."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class StartupModel(Base):
    """Startups entity table."""
    __tablename__ = "startups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_version = Column(String(10), nullable=False, default="1.0")
    record_type = Column(String(50), nullable=False, default="STARTUP")
    source_name = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=False)
    entity_name = Column(String(255), nullable=False, index=True)
    employee_count = Column(Integer, nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("record_type", "source_url", name="uq_startups_record_source"),
    )


class ProductModel(Base):
    """AI products entity table."""
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_version = Column(String(10), nullable=False, default="1.0")
    record_type = Column(String(50), nullable=False, default="PRODUCT")
    source_name = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=False)
    startup_name = Column(String(255), nullable=False, index=True)
    pricing_model = Column(String(50), nullable=False, index=True)  # FREE, FREEMIUM, PAID, ENTERPRISE
    collected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("record_type", "source_url", name="uq_products_record_source"),
    )


class ResearchPaperModel(Base):
    """AI Research papers entity table with zero-hallucination nullable GitHub fields."""
    __tablename__ = "research_papers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_version = Column(String(10), nullable=False, default="1.0")
    record_type = Column(String(50), nullable=False, default="RESEARCH_PAPER")
    title = Column(Text, nullable=False)
    authors = Column(JSONB, nullable=False, default=list)
    paper_url = Column(Text, nullable=False, unique=True, index=True)
    github_url = Column(Text, nullable=True)  # NULL if not verified
    github_stars = Column(Integer, nullable=True)  # NULL if not verified
    published_date = Column(DateTime(timezone=True), nullable=False, index=True)
    collected_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class JobModel(Base):
    """Jobs entity table with deterministic role family and 24h freshness."""
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_version = Column(String(10), nullable=False, default="1.0")
    record_type = Column(String(50), nullable=False, default="JOB")
    company = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    source_name = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=False)
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    is_remote = Column(Boolean, nullable=False, default=True)
    role_family = Column(String(50), nullable=False, index=True)  # Engineering, Research, Product, Other
    collected_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("company", "title", "source_url", "date", name="uq_jobs_composite"),
    )


class NewsModel(Base):
    """News entity table with 24h freshness."""
    __tablename__ = "news"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_version = Column(String(10), nullable=False, default="1.0")
    record_type = Column(String(50), nullable=False, default="NEWS")
    source_name = Column(String(255), nullable=False, index=True)
    source_url = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    published_date = Column(DateTime(timezone=True), nullable=False, index=True)
    content = Column(Text, nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("record_type", "source_url", name="uq_news_record_source"),
    )


class EntityMappingLogModel(Base):
    """Entity canonicalization audit log table."""
    __tablename__ = "entity_mapping_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_name = Column(String(255), nullable=False)
    canonical_name = Column(String(255), nullable=False, index=True)
    match_score = Column(Numeric(5, 2), nullable=False)
    method = Column(String(50), nullable=False, index=True)  # seed_match, cross_run_match, manual_review, new_entity
    entity_type = Column(String(50), nullable=False, default="STARTUP")
    source_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("raw_name", "entity_type", name="uq_entity_mapping"),
    )


class IngestionRunModel(Base):
    """Ingestion pipeline run audit table."""
    __tablename__ = "ingestion_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(String(100), nullable=False, index=True)
    phase = Column(String(50), nullable=False, index=True)
    source_name = Column(String(255), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=False, default="running", index=True)
    candidate_count = Column(Integer, nullable=False, default=0)
    accepted_count = Column(Integer, nullable=False, default=0)
    stale_count = Column(Integer, nullable=False, default=0)
    duplicate_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SourceRecordsAuditModel(Base):
    """Distributed crawler state and content hash audit table."""
    __tablename__ = "source_records_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=False, unique=True, index=True)
    content_hash = Column(String(64), nullable=True, index=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    published_date = Column(DateTime(timezone=True), nullable=True)
    processing_status = Column(String(50), nullable=False, default="raw", index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class LLMLogModel(Base):
    """LLM router execution, token budgeting, latency, and failover log table."""
    __tablename__ = "llm_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_name = Column(String(100), nullable=False, index=True)
    tier = Column(String(50), nullable=False, default="primary")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    status = Column(String(50), nullable=False, default="success", index=True)
    error_message = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)
    record_type = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

