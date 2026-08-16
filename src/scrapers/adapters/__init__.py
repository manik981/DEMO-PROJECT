"""Source adapters package."""

from src.scrapers.adapters.base import BaseSourceAdapter
from src.scrapers.adapters.jobs_adapters import (
    ActiveJobsDbAdapter,
    AIDevJobsAdapter,
    ArtificialIntelligenceJobsAdapter,
    FreehireJobsAdapter,
    IndeedJobsAdapter,
    USAJobsAdapter,
)
from src.scrapers.adapters.news_adapters import (
    DataCubeNewsAdapter,
    GNewsAdapter,
    GuardianNewsAdapter,
    NewsflashNewsAdapter,
    NoozraNewsAdapter,
)
from src.scrapers.adapters.zenserp_adapter import ZenserpDiscoveryAdapter

__all__ = [
    "BaseSourceAdapter",
    "DataCubeNewsAdapter",
    "NoozraNewsAdapter",
    "NewsflashNewsAdapter",
    "GNewsAdapter",
    "GuardianNewsAdapter",
    "ActiveJobsDbAdapter",
    "AIDevJobsAdapter",
    "FreehireJobsAdapter",
    "ArtificialIntelligenceJobsAdapter",
    "IndeedJobsAdapter",
    "USAJobsAdapter",
    "ZenserpDiscoveryAdapter",
]
