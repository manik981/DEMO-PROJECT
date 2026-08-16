"""Robust Async HTTP Client with Exponential Backoff, Jitter, Circuit-Breaker, and Telemetry Counters.

Handles:
- Fast bounded connection (2.5s) and read (3.5s) timeouts
- 429 (Rate Limits) with backoff + jitter
- Fast exit on permanent 4xx client errors (400, 401, 403, 404, 422)
- Zero-retry immediate skip on SSL certificate verification errors (preserving strict TLS security)
- Domain Circuit Breaker (skips repeatedly dead/failing domains during the run)
- Monotonic telemetry counters: api_requests, retries, failures
"""

import asyncio
import logging
import random
import time
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse
import aiohttp

logger = logging.getLogger(__name__)


class ResilientHttpClient:
    """Shared HTTP client with standardized retry, backoff, circuit-breaker, and error metrics."""

    # Global/Class-level domain circuit breaker cache: {domain: cooldown_until_timestamp}
    _cooldown_domains: Dict[str, float] = {}
    _failed_ssl_domains: Set[str] = set()

    def __init__(
        self,
        max_retries: int = 1,
        base_delay: float = 0.3,
        max_delay: float = 2.0,
        default_timeout: float = 5.0,
        connect_timeout: float = 2.5,
        read_timeout: float = 3.5,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.default_timeout = default_timeout
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

        # Metrics for observability
        self.api_requests_count: int = 0
        self.retries_count: int = 0
        self.failures_count: int = 0

    def _extract_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    def is_domain_in_cooldown(self, domain: str) -> bool:
        """Check if domain is temporarily tripped by circuit breaker."""
        if not domain:
            return False
        if domain in self._failed_ssl_domains:
            return True
        cooldown_until = self._cooldown_domains.get(domain, 0.0)
        return time.perf_counter() < cooldown_until

    def trip_domain_cooldown(self, domain: str, duration: float = 30.0) -> None:
        """Trip circuit breaker for a failing domain."""
        if domain:
            self._cooldown_domains[domain] = time.perf_counter() + duration

    async def get_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[Any]:
        """Perform GET request and parse JSON with retry logic."""
        res = await self.request(
            session=session,
            method="GET",
            url=url,
            headers=headers,
            params=params,
            timeout=timeout,
        )
        if res and res.get("status") == 200:
            return res.get("data")
        return None

    async def get_text(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Perform GET request and return raw text/XML with retry logic."""
        res = await self.request(
            session=session,
            method="GET",
            url=url,
            headers=headers,
            params=params,
            timeout=timeout,
            return_text=True,
        )
        if res and res.get("status") == 200:
            return res.get("text")
        return None

    async def request(
        self,
        session: aiohttp.ClientSession,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        return_text: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Execute HTTP request with bounded timeouts, circuit breaker, and backoff."""
        domain = self._extract_domain(url)
        if self.is_domain_in_cooldown(domain):
            logger.debug("Circuit breaker ACTIVE: skipping %s (%s in cooldown)", url, domain)
            self.failures_count += 1
            return {"status": 0, "error": f"Domain {domain} is in circuit-breaker cooldown"}

        tot_timeout = timeout or self.default_timeout
        conn_timeout = min(self.connect_timeout, tot_timeout)
        read_timeout = min(self.read_timeout, tot_timeout)
        req_timeout = aiohttp.ClientTimeout(total=tot_timeout, connect=conn_timeout, sock_read=read_timeout)
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            self.api_requests_count += 1
            try:
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=req_timeout,
                ) as resp:
                    status = resp.status

                    # Success (200 OK)
                    if 200 <= status < 300:
                        if return_text:
                            text = await resp.text()
                            return {"status": status, "text": text, "headers": resp.headers}
                        else:
                            try:
                                data = await resp.json(content_type=None)
                                return {"status": status, "data": data, "headers": resp.headers}
                            except Exception:
                                text = await resp.text()
                                return {"status": status, "text": text, "headers": resp.headers}

                    # Permanent client errors: do not retry
                    if status in (400, 401, 403, 404, 422):
                        logger.warning("HTTP %d (Client Error) for %s - skipping retries.", status, url)
                        self.failures_count += 1
                        return {"status": status, "error": f"Client error {status}"}

                    # Rate Limit (429) or Server Errors (5xx): Retry with backoff
                    if status == 429 or status >= 500:
                        logger.warning("HTTP %d on attempt %d for %s", status, attempt, url)
                        if attempt < self.max_retries:
                            self.retries_count += 1
                        else:
                            self.failures_count += 1
                            self.trip_domain_cooldown(domain, duration=20.0)
                            return {"status": status, "error": f"Failed with status {status}"}

            except aiohttp.ClientSSLError as e:
                # Strictly preserve SSL verification: do NOT retry, immediately mark domain
                logger.warning("SSL certificate verification failed for %s: %s (Skipping unverified endpoint for security)", url, e)
                self._failed_ssl_domains.add(domain)
                self.failures_count += 1
                return {"status": 0, "error": f"SSL verification failed: {e}"}

            except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, asyncio.TimeoutError) as e:
                last_error = e
                logger.warning("Network/Timeout error on attempt %d for %s: %s", attempt, url, e)
                if attempt < self.max_retries:
                    self.retries_count += 1
                else:
                    self.failures_count += 1
                    self.trip_domain_cooldown(domain, duration=20.0)
                    return {"status": 0, "error": str(last_error)}

            except Exception as e:
                logger.error("Unexpected request failure for %s: %s", url, e)
                self.failures_count += 1
                return {"status": 0, "error": str(e)}

            # Compute small backoff with jitter
            delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0.05, 0.2)
            await asyncio.sleep(delay + jitter)

        return {"status": 0, "error": str(last_error)}

