"""Base Source Adapter Abstract Interface."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import aiohttp

from src.utils.http_client import ResilientHttpClient

logger = logging.getLogger(__name__)


class BaseSourceAdapter(ABC):
    """Abstract base class for all news, jobs, and discovery adapters."""

    def __init__(
        self,
        name: str,
        category: str,
        base_url: str,
        auth_type: str = "none",
        http_client: Optional[ResilientHttpClient] = None,
    ):
        self.name = name
        self.category = category
        self.base_url = base_url
        self.auth_type = auth_type
        self.http_client = http_client or ResilientHttpClient()

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials exist or no auth is required."""
        pass

    @abstractmethod
    async def fetch_candidates(
        self,
        session: aiohttp.ClientSession,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch raw candidate records from source.

        Each candidate dict must contain:
        - source_name
        - source_url (or canonical article/job link)
        - title
        - published_date (or raw date string)
        - raw_content (or summary)
        - is_resolved (True if valid canonical URL present)
        - raw_metadata
        """
        pass
