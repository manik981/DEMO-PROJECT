"""Lightweight Source Connectivity Verification.

Safely verifies connectivity to all 10 key-based and public sources with minimal probe requests.
CRITICAL SAFETY RULE: Never prints or exposes secret values.

Usage:
    python src/test_connectivity.py
"""

import asyncio
import os
import sys
from pathlib import Path
import aiohttp
from dotenv import load_dotenv

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scrapers.arbeitnow import ArbeitnowJobsAdapter
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


async def check_adapter_connectivity(session: aiohttp.ClientSession, adapter) -> tuple:
    """Probe single adapter with limit=1 without logging secrets."""
    auth_label = "API KEY" if adapter.auth_type != "none" else "NONE"

    if not adapter.is_configured:
        return (adapter.name, auth_label, "MISSING_KEY")

    try:
        candidates = await adapter.fetch_candidates(session, limit=1)
        status = "OK" if isinstance(candidates, list) else "FAIL"
        return (adapter.name, auth_label, status)
    except Exception:
        return (adapter.name, auth_label, "FAIL")


async def run_connectivity_checks():
    load_dotenv()
    adapters = [
        ZenserpDiscoveryAdapter(),
        DataCubeNewsAdapter(),
        NoozraNewsAdapter(),
        NewsflashNewsAdapter(),
        GNewsAdapter(),
        GuardianNewsAdapter(),
        AIDevJobsAdapter(),
        FreehireJobsAdapter(),
        ArtificialIntelligenceJobsAdapter(),
        USAJobsAdapter(),
        ArbeitnowJobsAdapter(),
        IndeedJobsAdapter(),
        ActiveJobsDbAdapter(),
    ]

    print("\n" + "=" * 65)
    print(f"{'SOURCE':<32} | {'AUTH':<10} | {'STATUS'}")
    print("-" * 65)

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [check_adapter_connectivity(session, ad) for ad in adapters]
        results = await asyncio.gather(*tasks)

        for name, auth_type, status in results:
            print(f"{name:<32} | {auth_type:<10} | {status}")

    print("=" * 65 + "\n")


def main():
    asyncio.run(run_connectivity_checks())


if __name__ == "__main__":
    main()
