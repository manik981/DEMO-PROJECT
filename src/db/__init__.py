"""Database package providing SQLAlchemy models and Supabase repository client."""

from src.db.models import (
    Base,
    EntityMappingLogModel,
    IngestionRunModel,
    JobModel,
    NewsModel,
    ProductModel,
    ResearchPaperModel,
    SourceRecordsAuditModel,
    StartupModel,
)
from src.db.supabase_client import SupabaseClient, get_supabase_client

__all__ = [
    "Base",
    "StartupModel",
    "ProductModel",
    "ResearchPaperModel",
    "JobModel",
    "NewsModel",
    "EntityMappingLogModel",
    "IngestionRunModel",
    "SourceRecordsAuditModel",
    "SupabaseClient",
    "get_supabase_client",
]
