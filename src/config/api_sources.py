"""External API Source Registry and Configuration Matrix.

Contains authoritative endpoint definitions, authentication types, environment variables,
and rate limit rules for all key-based and public data intelligence sources.

NEVER contains hardcoded credentials.
"""

from typing import Any, Dict

EXTERNAL_API_SOURCES: Dict[str, Dict[str, Any]] = {
    # -------------------------------------------------------------
    # 1. DISCOVERY & SEARCH UTILITIES
    # -------------------------------------------------------------
    "zenserp": {
        "name": "Zenserp Search API",
        "category": "Discovery / Search",
        "base_url": "https://app.zenserp.com/api/v2/search",
        "auth_type": "api_key_header",
        "environment_variable": "ZENSERP_API_KEY",
        "description": "SERP / Google search scraping for candidate URL discovery (not source of truth)",
        "enabled": True,
        "rate_limit_rpm": 60,
    },

    # -------------------------------------------------------------
    # 2. NEWS ADAPTERS (KEY-BASED)
    # -------------------------------------------------------------
    "newsflash": {
        "name": "Newsflash API",
        "category": "News",
        "base_url": "https://newsflash.io/api/v1/news",
        "auth_type": "api_key_header",
        "environment_variable": "NEWSFLASH_API_KEY",
        "description": "Real-time AI and tech news stream",
        "enabled": True,
        "rate_limit_rpm": 60,
    },
    "gnews": {
        "name": "GNews API",
        "category": "News",
        "base_url": "https://gnews.io/api/v4/search",
        "auth_type": "api_key_query",
        "environment_variable": "GNEWS_API_KEY",
        "description": "Global news search API with category and language filters",
        "enabled": True,
        "rate_limit_rpm": 30,
    },
    "guardian": {
        "name": "The Guardian Open Platform",
        "category": "News",
        "base_url": "https://content.guardianapis.com/search",
        "auth_type": "api_key_query",
        "environment_variable": "GUARDIAN_API_KEY",
        "description": "Official Guardian Content API for technology and AI coverage",
        "enabled": True,
        "rate_limit_rpm": 120,
    },

    # -------------------------------------------------------------
    # 3. NEWS ADAPTERS (PUBLIC / NO-KEY)
    # -------------------------------------------------------------
    "datacube_ai": {
        "name": "DataCube AI",
        "category": "News",
        "base_url": "https://datacube.ai/api/v1/news",
        "auth_type": "none",
        "environment_variable": None,
        "description": "Public AI technology feed and dataset updates",
        "enabled": True,
        "rate_limit_rpm": 60,
    },
    "noozra": {
        "name": "Noozra",
        "category": "News",
        "base_url": "https://noozra.com/api/articles",
        "auth_type": "none",
        "environment_variable": None,
        "description": "Public tech news aggregator with cursor-based pagination",
        "enabled": True,
        "rate_limit_rpm": 60,
    },

    # -------------------------------------------------------------
    # 4. JOBS ADAPTERS (KEY-BASED)
    # -------------------------------------------------------------
    "usajobs": {
        "name": "USAJOBS Search API",
        "category": "Jobs",
        "base_url": "https://data.usajobs.gov/api/search",
        "auth_type": "api_key_headers",
        "environment_variable": "USAJOBS_API_KEY",
        "extra_environment_variable": "USAJOBS_API_EMAIL",
        "description": "US Federal jobs API requiring Host, User-Agent, and Authorization-Key headers",
        "enabled": True,
        "rate_limit_rpm": 60,
    },

    "indeed_rapidapi": {
        "name": "Indeed (RapidAPI)",
        "category": "Jobs",
        "base_url": "https://indeed12.p.rapidapi.com",
        "auth_type": "api_key_header",
        "environment_variable": "RAPIDAPI_KEY",
        "description": "Indeed Job Search and Company Job Board API via RapidAPI",
        "enabled": True,
        "rate_limit_rpm": 60,
    },

    "active_jobs_db": {
        "name": "Active Jobs DB (RapidAPI)",
        "category": "Jobs",
        "base_url": "https://active-jobs-db.p.rapidapi.com",
        "auth_type": "api_key_header",
        "environment_variable": "RAPIDAPI_KEY",
        "description": "Real-time 24h active ATS job postings search via RapidAPI",
        "enabled": True,
        "rate_limit_rpm": 60,
    },

    # -------------------------------------------------------------
    # 5. JOBS ADAPTERS (PUBLIC / NO-KEY)
    # -------------------------------------------------------------
    "arbeitnow": {
        "name": "Arbeitnow",
        "category": "Jobs",
        "base_url": "https://www.arbeitnow.com/api/job-board-api",
        "auth_type": "none",
        "environment_variable": None,
        "description": "Public remote tech & AI job board API",
        "enabled": True,
        "rate_limit_rpm": 60,
    },
    "aidevjobs": {
        "name": "AI Dev Jobs",
        "category": "Jobs",
        "base_url": "https://aidevboard.com/api/v1/jobs",
        "auth_type": "none",
        "environment_variable": None,
        "description": "Public AI engineering and developer jobs board",
        "enabled": True,
        "rate_limit_rpm": 60,
    },
    "freehire": {
        "name": "Freehire",
        "category": "Jobs",
        "base_url": "https://freehire.me/api/v1/jobs",
        "auth_type": "none",
        "environment_variable": None,
        "description": "Public tech & AI jobs search with offset/limit pagination",
        "enabled": True,
        "rate_limit_rpm": 60,
    },
    "artificial_intelligence_jobs": {
        "name": "Artificial Intelligence Jobs",
        "category": "Jobs",
        "base_url": "https://artificialintelligencejobs.net/feed/",
        "auth_type": "none",
        "environment_variable": None,
        "description": "Public AI community job feed",
        "enabled": True,
        "rate_limit_rpm": 60,
    },
}
