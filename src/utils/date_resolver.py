"""Multi-tier Date Resolver with Provenance and Observation Timestamp Cache."""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple
from email.utils import parsedate_to_datetime

try:
    import dateparser
except ImportError:
    dateparser = None  # type: ignore

logger = logging.getLogger(__name__)


class DateResolver:
    """Multi-tier date parser and observation timestamp tracker with zero-fabrication guarantees."""

    def __init__(self, cache_file: str = "data/cache/observed_urls.json"):
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.observed_cache = self._load_cache()

    def _load_cache(self) -> dict:
        """Load persistent url observation timestamps."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to load observation cache: %s", e)
        return {}

    def _save_cache(self) -> None:
        """Persist observation cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.observed_cache, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save observation cache: %s", e)

    def parse_rfc822_or_iso(self, date_str: str) -> Optional[datetime]:
        """Attempt fast standard parsing for RFC822 (RSS) and ISO8601 strings."""
        if not date_str:
            return None
        date_str = date_str.strip()

        # 1. RFC 822 / 1123 (standard RSS pubDate)
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # 2. ISO 8601 / RFC 3339
        try:
            clean_iso = date_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        return None

    def resolve_date(
        self,
        rss_date: Optional[str] = None,
        html_meta_date: Optional[str] = None,
        visible_date_text: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Tuple[datetime, str, bool, bool]:
        """Resolve publication date using multi-tier hierarchy.

        Returns: (resolved_datetime, date_source, is_heuristic_date, freshness_verified)
        """
        now = datetime.now(timezone.utc)

        # Tier 1: RSS timestamp
        if rss_date:
            dt = self.parse_rfc822_or_iso(rss_date)
            if dt:
                return dt, "rss", False, True

        # Tier 2: HTML metadata tags (article:published_time, datePublished, etc.)
        if html_meta_date:
            dt = self.parse_rfc822_or_iso(html_meta_date)
            if dt:
                return dt, "html_meta", False, True

        # Tier 3: dateparser on visible relative/locale strings
        if visible_date_text and dateparser is not None:
            try:
                dt = dateparser.parse(
                    visible_date_text,
                    settings={"RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DATES_FROM": "past"},
                )
                if dt:
                    return dt.astimezone(timezone.utc), "dateparser", False, True
            except Exception:
                pass

        # Tier 4: Heuristic fallback - first observed timestamp for this URL
        if url:
            if url in self.observed_cache:
                stored_iso = self.observed_cache[url]
                try:
                    dt = datetime.fromisoformat(stored_iso)
                    return dt, "first_observed", True, False
                except Exception:
                    pass
            # Register newly observed URL
            self.observed_cache[url] = now.isoformat()
            self._save_cache()
            return now, "first_observed", True, False

        # Fallback if no URL given
        return now, "fallback_now", True, False

    def is_within_freshness_window(
        self,
        dt: datetime,
        hours: float = 24.0,
        clock_skew_tolerance_minutes: float = 10.0,
    ) -> bool:
        """Verify date satisfies: now - hours <= dt <= now + clock_skew_tolerance."""
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_utc = dt.astimezone(timezone.utc)

        min_bound = now.timestamp() - (hours * 3600)
        max_bound = now.timestamp() + (clock_skew_tolerance_minutes * 60)

        return min_bound <= dt_utc.timestamp() <= max_bound
