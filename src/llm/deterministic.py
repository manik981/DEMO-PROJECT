"""Source-Specific Deterministic Extraction Layer.

Executes deterministic parsers, regex extractors, date normalizers, and keyword
classifiers across all 5 verticals before any LLM is considered.

The LLM is invoked ONLY when a required field is genuinely missing and requires
semantic interpretation.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar
from dateutil import parser as dt_parser

from src.schemas import (
    JobContent,
    JobEntity,
    NewsContent,
    NewsEntity,
    ProductContent,
    ProductEntity,
    ResearchPaperContent,
    ResearchPaperEntity,
    SourceInfo,
    StartupContent,
    StartupData,
    StartupEntity,
)

logger = logging.getLogger("deterministic_extractor")

T = TypeVar("T")


def parse_iso_or_flexible_date(date_val: Any) -> Optional[datetime]:
    """Parse flexible date representations into timezone-aware UTC datetime."""
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        if date_val.tzinfo is None:
            return date_val.replace(tzinfo=timezone.utc)
        return date_val.astimezone(timezone.utc)
    if isinstance(date_val, (int, float)):
        # Epoch timestamp
        try:
            return datetime.fromtimestamp(date_val, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(date_val, str):
        date_str = date_val.strip()
        if not date_str:
            return None
        try:
            dt = dt_parser.parse(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def extract_deterministic_paper(raw_record: dict) -> Tuple[Optional[ResearchPaperEntity], Optional[str]]:
    """Deterministic extractor for Research Papers (Crossref REST API / metadata)."""
    content = raw_record.get("content", {})
    if not isinstance(content, dict):
        content = raw_record

    title = content.get("title") or raw_record.get("title")
    authors = content.get("authors") or raw_record.get("authors")
    paper_url = content.get("paper_url") or raw_record.get("paper_url") or raw_record.get("url") or raw_record.get("source", {}).get("url")
    pub_date_val = content.get("published_date") or raw_record.get("published_date") or raw_record.get("published")

    summary_text = str(content.get("summary", "") or content.get("abstract", "") or raw_record.get("summary", "") or raw_record.get("abstract", "") or raw_record.get("text", "") or raw_record.get("raw_text", ""))

    if not title or not isinstance(title, str) or not title.strip():
        # Check if title can be extracted from first line
        if summary_text:
            title = summary_text.split(".")[0].strip()
        if not title:
            return None, "missing_required_title"

    if not authors and summary_text:
        match_auth = re.search(r"Authors?:\s*([^\.]+)", summary_text, re.IGNORECASE)
        if match_auth:
            authors = [a.strip() for a in re.split(r",|\band\b", match_auth.group(1)) if a.strip()]

    if isinstance(authors, str):
        authors = [a.strip() for a in re.split(r",|\band\b", authors) if a.strip()]
    if not isinstance(authors, list) or len(authors) == 0:
        authors = ["Anonymous / Crossref Contributor"]

    if not paper_url or not isinstance(paper_url, str) or not (paper_url.startswith("http://") or paper_url.startswith("https://") or "doi.org" in paper_url):
        return None, "missing_valid_paper_url"

    pub_dt = parse_iso_or_flexible_date(pub_date_val)
    if not pub_dt:
        return None, "missing_valid_published_date"

    # Optional fields (null is completely valid)
    github_url = content.get("github_url") or raw_record.get("github_url")
    if not github_url and summary_text:
        match_gh = re.search(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", summary_text)
        if match_gh:
            github_url = match_gh.group(0).rstrip(".,)")

    github_stars = content.get("github_stars") if content.get("github_stars") is not None else raw_record.get("github_stars")
    if github_stars is not None:
        try:
            github_stars = int(github_stars)
        except Exception:
            github_stars = None

    try:
        paper_content = ResearchPaperContent(
            title=title.strip(),
            authors=[str(a).strip() for a in authors],
            paper_url=paper_url.strip(),
            github_url=github_url.strip() if isinstance(github_url, str) and github_url.strip() else None,
            github_stars=github_stars,
            published_date=pub_dt,
        )
        return ResearchPaperEntity(
            schemaVersion="1.0",
            recordType="RESEARCH_PAPER",
            content=paper_content,
        ), None
    except Exception as e:
        return None, f"schema_validation_error: {e}"


def extract_deterministic_startup(raw_record: dict) -> Tuple[Optional[StartupEntity], Optional[str]]:
    """Deterministic extractor for Startups (YC, Techstars, Product Hunt, etc.)."""
    content = raw_record.get("content", {})
    if not isinstance(content, dict):
        content = raw_record

    name = content.get("entityName") or raw_record.get("name") or raw_record.get("company_name") or raw_record.get("title") or raw_record.get("entity_name")
    summary_text = str(raw_record.get("text", "") or raw_record.get("raw_snippet", "") or content.get("description", ""))

    if not name and summary_text:
        match_name = re.match(r"^([A-Za-z0-9\s]+?)\s+(?:is|delivers|builds|provides|announced)\b", summary_text)
        if match_name:
            name = match_name.group(1).strip()

    source_obj = raw_record.get("source", {})
    source_name = source_obj.get("name") or raw_record.get("source_name") or "Startup Directory"
    source_url = source_obj.get("url") or raw_record.get("source_url") or raw_record.get("url")

    if not name or not isinstance(name, str) or not name.strip():
        return None, "missing_required_entityName"

    if not source_url or not isinstance(source_url, str) or not source_url.startswith("http"):
        return None, "missing_required_source_url"

    # Optional employeeCount extraction
    emp_count = None
    data_dict = content.get("data", {}) if isinstance(content.get("data"), dict) else {}
    raw_emp = data_dict.get("employeeCount") or raw_record.get("employeeCount") or raw_record.get("employees")
    if raw_emp is not None:
        try:
            emp_count = int(raw_emp)
        except Exception:
            match = re.search(r"(\d+)", str(raw_emp))
            emp_count = int(match.group(1)) if match else None
    elif summary_text:
        match = re.search(r"(\d+)\s*(?:employees|people|team members)", summary_text, re.IGNORECASE)
        if match:
            emp_count = int(match.group(1))

    collected_at = parse_iso_or_flexible_date(raw_record.get("collectedAt")) or datetime.now(timezone.utc)

    try:
        return StartupEntity(
            schemaVersion="1.0",
            recordType="STARTUP",
            source=SourceInfo(name=source_name.strip(), url=source_url.strip()),
            content=StartupContent(
                entityName=name.strip(),
                data=StartupData(employeeCount=emp_count),
            ),
            collectedAt=collected_at,
        ), None
    except Exception as e:
        return None, f"schema_validation_error: {e}"


def extract_deterministic_product(raw_record: dict) -> Tuple[Optional[ProductEntity], Optional[str]]:
    """Deterministic extractor for Products (Product Hunt, BetaList, etc.)."""
    content = raw_record.get("content", {})
    if not isinstance(content, dict):
        content = raw_record

    startup_name = content.get("startupName") or raw_record.get("startupName") or raw_record.get("name") or raw_record.get("title")
    source_obj = raw_record.get("source", {})
    source_name = source_obj.get("name") or raw_record.get("source_name") or "Product Source"
    source_url = source_obj.get("url") or raw_record.get("source_url") or raw_record.get("url")

    if not startup_name or not isinstance(startup_name, str) or not startup_name.strip():
        return None, "missing_required_startupName"

    if not source_url or not isinstance(source_url, str) or not source_url.startswith("http"):
        return None, "missing_required_source_url"

    # Deterministic pricing model rule
    raw_pricing = str(content.get("pricingModel") or raw_record.get("pricingModel") or raw_record.get("pricing") or "").upper()
    pricing_model = "FREEMIUM"
    if raw_pricing in ("FREE", "FREEMIUM", "PAID", "ENTERPRISE"):
        pricing_model = raw_pricing
    else:
        text_corpus = f"{raw_pricing} {content.get('description', '')} {raw_record.get('description', '')}".lower()
        if any(w in text_corpus for w in ["open source", "free software", "100% free", "mit license", "apache-2.0", "$0"]):
            pricing_model = "FREE"
        elif any(w in text_corpus for w in ["enterprise", "custom quote", "contact sales", "volume licensing"]):
            pricing_model = "ENTERPRISE"
        elif any(w in text_corpus for w in ["paid", "$", "per month", "subscription", "billed monthly", "/mo"]):
            pricing_model = "PAID"
        else:
            pricing_model = "FREEMIUM"

    collected_at = parse_iso_or_flexible_date(raw_record.get("collectedAt")) or datetime.now(timezone.utc)

    try:
        return ProductEntity(
            schemaVersion="1.0",
            recordType="PRODUCT",
            source=SourceInfo(name=source_name.strip(), url=source_url.strip()),
            content=ProductContent(
                startupName=startup_name.strip(),
                pricingModel=pricing_model,
            ),
            collectedAt=collected_at,
        ), None
    except Exception as e:
        return None, f"schema_validation_error: {e}"


def extract_deterministic_news(raw_record: dict) -> Tuple[Optional[NewsEntity], Optional[str]]:
    """Deterministic extractor for News (RSS feeds, GNews, Guardian, Newsflash, DataCube)."""
    content = raw_record.get("content", {})
    if not isinstance(content, dict):
        content = raw_record

    title = content.get("title") or raw_record.get("title")
    url = content.get("url") or raw_record.get("url") or raw_record.get("source", {}).get("url")
    pub_date_val = content.get("published_date") or raw_record.get("published_date") or raw_record.get("publishedAt") or raw_record.get("pubDate")
    summary = content.get("summary") or raw_record.get("summary") or raw_record.get("description") or raw_record.get("contentSnippet") or raw_record.get("snippet")

    source_obj = raw_record.get("source", {})
    source_name = source_obj.get("name") or raw_record.get("source_name") or "News Source"
    source_url = source_obj.get("url") or url

    if not title or not isinstance(title, str) or not title.strip():
        return None, "missing_required_title"

    if not url or not isinstance(url, str) or not url.startswith("http"):
        return None, "missing_required_url"

    pub_dt = parse_iso_or_flexible_date(pub_date_val)
    if not pub_dt:
        return None, "missing_valid_published_date"

    if not summary or not isinstance(summary, str) or not summary.strip():
        # Fallback to title as clean fallback summary if description absent
        summary = title.strip()

    collected_at = parse_iso_or_flexible_date(raw_record.get("collectedAt")) or datetime.now(timezone.utc)

    try:
        return NewsEntity(
            schemaVersion="1.0",
            recordType="NEWS",
            source=SourceInfo(name=source_name.strip(), url=source_url.strip()),
            content=NewsContent(
                title=title.strip(),
                url=url.strip(),
                published_date=pub_dt,
                summary=summary.strip(),
            ),
            collectedAt=collected_at,
        ), None
    except Exception as e:
        return None, f"schema_validation_error: {e}"


def extract_deterministic_job(raw_record: dict) -> Tuple[Optional[JobEntity], Optional[str]]:
    """Deterministic extractor for Jobs (RemoteOK, WeWorkRemotely, USAJOBS, AI Dev Jobs)."""
    content = raw_record.get("content", {})
    if not isinstance(content, dict):
        content = raw_record

    company = content.get("company") or raw_record.get("company") or raw_record.get("company_name") or raw_record.get("employer")
    date_val = content.get("date") or raw_record.get("date") or raw_record.get("created_at") or raw_record.get("published")
    is_remote_val = content.get("is_remote") if content.get("is_remote") is not None else raw_record.get("is_remote")
    role_val = content.get("role_family") or raw_record.get("role_family")

    if not company or not isinstance(company, str) or not company.strip():
        return None, "missing_required_company"

    date_dt = parse_iso_or_flexible_date(date_val)
    if not date_dt:
        return None, "missing_valid_date"

    # Deterministic remote status
    if isinstance(is_remote_val, bool):
        is_remote = is_remote_val
    else:
        loc = str(raw_record.get("location", "")).lower()
        is_remote = "remote" in loc or "anywhere" in loc or "wfh" in loc or is_remote_val is True

    # Deterministic role_family classification
    if role_val in ("Engineering", "Research", "Product", "Other"):
        role_family = role_val
    else:
        title_str = str(content.get("title") or raw_record.get("title", "")).lower()
        if any(k in title_str for k in ["engineer", "developer", "software", "backend", "frontend", "fullstack", "devops", "infra", "data eng", "architect", "sysadmin"]):
            role_family = "Engineering"
        elif any(k in title_str for k in ["research", "scientist", "ai resident", "postdoc", "phd", "fellow", "lab"]):
            role_family = "Research"
        elif any(k in title_str for k in ["product manager", "pm ", "product owner", "head of product", "vp product"]):
            role_family = "Product"
        else:
            role_family = "Other"

    try:
        return JobEntity(
            schemaVersion="1.0",
            recordType="JOB",
            content=JobContent(
                company=company.strip(),
                date=date_dt,
                is_remote=is_remote,
                role_family=role_family,
            ),
        ), None
    except Exception as e:
        return None, f"schema_validation_error: {e}"


def should_call_llm(raw_record: dict, vertical: str, schema_cls: Type[T]) -> Tuple[bool, Optional[T], str]:
    """Single central LLM Gate.
    
    Returns:
        (False, validated_entity, 'deterministic_success') if deterministically complete.
        (True, None, reason) ONLY when a required field cannot be obtained deterministically.
    
    Default: FALSE.
    """
    if not isinstance(raw_record, dict):
        return True, None, "unstructured_raw_format"

    # 1. Try Direct Pydantic Validation on existing structure
    try:
        entity = schema_cls.model_validate(raw_record)
        return False, entity, "deterministic_schema_match"
    except Exception:
        pass

    # 2. Run Vertical-Specific Deterministic Parser
    entity = None
    reason = "parser_failure"

    if vertical == "papers":
        entity, reason = extract_deterministic_paper(raw_record)
    elif vertical == "startups":
        entity, reason = extract_deterministic_startup(raw_record)
    elif vertical == "products":
        entity, reason = extract_deterministic_product(raw_record)
    elif vertical == "news":
        entity, reason = extract_deterministic_news(raw_record)
    elif vertical == "jobs":
        entity, reason = extract_deterministic_job(raw_record)

    if entity is not None:
        return False, entity, "deterministic_extractor_success"

    # LLM is required only if deterministic extractor could not resolve a required field
    return True, None, reason or "semantic_extraction_required"
