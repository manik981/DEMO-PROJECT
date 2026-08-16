"""Deterministic Entity Resolution Engine.

Hallucination-proof canonicalization of startup and product names using:
1. Legal suffix and noise normalization
2. Exact normalized match bypass
3. RapidFuzz WRatio thresholded matching (>=90 Auto-merge, 75-89 Review, <75 New entity)
4. Comprehensive audit logging to CSV (Entity Mapping Log)

Zero LLM Participation: 100% deterministic, auditable, and reproducible.
"""

import csv
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz, process
except ImportError:
    fuzz = None  # type: ignore
    process = None  # type: ignore


@dataclass
class ResolutionResult:
    """Encapsulates the deterministic entity resolution decision."""
    raw_name: str
    canonical_name: str
    match_score: float
    method: str  # exact_seed_match, exact_cross_run, fuzzy_seed_match, fuzzy_cross_run, manual_review, new_entity
    requires_review: bool
    source_url: str = ""
    entity_type: str = "STARTUP"
    timestamp: str = ""


class EntityResolver:
    """Deterministic, hallucination-proof entity canonicalization engine."""

    # Suffixes and legal descriptors stripped during normalization
    LEGAL_SUFFIXES = [
        r"\bprivate\s+limited\b",
        r"\bpvt\.?\s+ltd\.?\b",
        r"\bpublic\s+benefit\s+corporation\b",
        r"\bpbc\b",
        r"\bincorporated\b",
        r"\bcorporation\b",
        r"\btechnologies\b",
        r"\btechnology\b",
        r"\bsoftware\b",
        r"\bsolutions\b",
        r"\bsystems\b",
        r"\bplatform\b",
        r"\bgmbh\b",
        r"\bcorp\.?\b",
        r"\binc\.?\b",
        r"\bllc\.?\b",
        r"\bltd\.?\b",
        r"\blabs\b",
        r"\blab\b",
        r"\bco\.?\b",
    ]

    def __init__(
        self,
        seed_path: Optional[str] = "data/seed/canonical_startups.json",
        output_csv_path: Optional[str] = "data/output/entity_mapping_log.csv",
        review_csv_path: Optional[str] = "data/output/manual_review_entities.csv",
        auto_merge_threshold: float = 90.0,
        manual_review_threshold: float = 75.0,
    ):
        self.auto_merge_threshold = auto_merge_threshold
        self.manual_review_threshold = manual_review_threshold
        self.output_csv_path = Path(output_csv_path) if output_csv_path else None
        self.review_csv_path = Path(review_csv_path) if review_csv_path else None

        # Normalized lookup tables: normalized_name -> canonical_name
        self.seed_lookup: Dict[str, str] = {}
        self.cross_run_lookup: Dict[str, str] = {}

        # Logged resolutions set to prevent duplicate CSV rows: raw_name -> canonical
        self.logged_resolutions: Dict[str, ResolutionResult] = {}

        if self.output_csv_path:
            self.output_csv_path.parent.mkdir(parents=True, exist_ok=True)
        if self.review_csv_path:
            self.review_csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_csv_headers()

        if seed_path:
            self.load_seed_catalog(seed_path)

    def _init_csv_headers(self) -> None:
        """Initialize CSV output log file with required and diagnostic headers."""
        if self.output_csv_path and not self.output_csv_path.exists():
            with open(self.output_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["raw_name", "canonical_name", "match_score", "method", "source_url", "entity_type", "timestamp"])

        if self.review_csv_path and not self.review_csv_path.exists():
            with open(self.review_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["raw_name", "tentative_canonical", "match_score", "method", "source_url", "timestamp"])

    def load_seed_catalog(self, seed_path: str) -> None:
        """Load 50+ canonical seed AI companies from JSON file."""
        seed_file = Path(seed_path)
        if not seed_file.exists():
            logger.warning("Seed file %s not found.", seed_path)
            return

        try:
            with open(seed_file, "r", encoding="utf-8") as f:
                seed_list = json.load(f)
                for canonical in seed_list:
                    norm = self.normalize_name(canonical)
                    if norm:
                        self.seed_lookup[norm] = canonical
            logger.info("Loaded %d seed canonical companies.", len(self.seed_lookup))
        except Exception as e:
            logger.error("Failed to load seed catalog: %s", e)

    def normalize_name(self, name: str) -> str:
        """Normalize company/product name by lowercasing, stripping noise suffixes, and punctuation."""
        if not name:
            return ""

        cleaned = name.lower().strip()

        # Strip legal / corporate noise suffixes
        for suffix in self.LEGAL_SUFFIXES:
            cleaned = re.sub(suffix, "", cleaned, flags=re.IGNORECASE)

        # Remove punctuation and special characters
        cleaned = re.sub(r"[^\w\s]", "", cleaned)

        # Remove all intra-word whitespace to unify variants like "Open AI" -> "openai"
        no_space = re.sub(r"\s+", "", cleaned)
        if no_space:
            return no_space

        # Fallback if aggressive stripping eliminated everything (e.g. "AI")
        fallback = re.sub(r"[^\w]", "", name.lower().strip())
        return fallback or name.lower().strip()

    def resolve(
        self,
        raw_name: str,
        source_url: str = "",
        entity_type: str = "STARTUP",
    ) -> ResolutionResult:
        """Resolve a raw company or product name to its canonical representation.

        Hierarchy:
        1. Exact match against Seed Catalog (score 100.0)
        2. Exact match against Cross-Run Registry (score 100.0)
        3. RapidFuzz WRatio match against Seed (>=90 Auto-merge, 75-89 Review)
        4. RapidFuzz WRatio match against Cross-Run (>=90 Auto-merge, 75-89 Review)
        5. New Entity (<75)
        """
        if not raw_name or not raw_name.strip():
            return ResolutionResult(
                raw_name=raw_name,
                canonical_name=raw_name,
                match_score=0.0,
                method="empty_name",
                requires_review=False,
                source_url=source_url,
                entity_type=entity_type,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        clean_raw = raw_name.strip()
        normalized = self.normalize_name(clean_raw)
        now_ts = datetime.now(timezone.utc).isoformat()

        # Step 1: Exact match against Seed Catalog
        if normalized in self.seed_lookup:
            canonical = self.seed_lookup[normalized]
            res = ResolutionResult(
                raw_name=clean_raw,
                canonical_name=canonical,
                match_score=100.0,
                method="seed_match",
                requires_review=False,
                source_url=source_url,
                entity_type=entity_type,
                timestamp=now_ts,
            )
            self._log_resolution(res)
            return res

        # Step 2: Exact match against Cross-Run Registry
        if normalized in self.cross_run_lookup:
            canonical = self.cross_run_lookup[normalized]
            res = ResolutionResult(
                raw_name=clean_raw,
                canonical_name=canonical,
                match_score=100.0,
                method="cross_run_match",
                requires_review=False,
                source_url=source_url,
                entity_type=entity_type,
                timestamp=now_ts,
            )
            self._log_resolution(res)
            return res

        # Step 3: Fuzzy Match against Seed Catalog with RapidFuzz WRatio
        if fuzz is not None and process is not None and self.seed_lookup:
            seed_norm_keys = list(self.seed_lookup.keys())
            best_seed_match = process.extractOne(
                normalized,
                seed_norm_keys,
                scorer=fuzz.WRatio,
            )
            if best_seed_match:
                best_norm, score, _ = best_seed_match
                if score >= self.auto_merge_threshold:
                    canonical = self.seed_lookup[best_norm]
                    # Register normalized alias for fast subsequent lookups
                    self.cross_run_lookup[normalized] = canonical
                    res = ResolutionResult(
                        raw_name=clean_raw,
                        canonical_name=canonical,
                        match_score=float(score),
                        method="seed_match",
                        requires_review=False,
                        source_url=source_url,
                        entity_type=entity_type,
                        timestamp=now_ts,
                    )
                    self._log_resolution(res)
                    return res
                elif score >= self.manual_review_threshold:
                    canonical = self.seed_lookup[best_norm]
                    res = ResolutionResult(
                        raw_name=clean_raw,
                        canonical_name=clean_raw,  # Retain raw until reviewed
                        match_score=float(score),
                        method="manual_review",
                        requires_review=True,
                        source_url=source_url,
                        entity_type=entity_type,
                        timestamp=now_ts,
                    )
                    self._log_resolution(res)
                    self._log_review(res, tentative_canonical=canonical)
                    return res

        # Step 4: Fuzzy Match against Cross-Run Registry
        if fuzz is not None and process is not None and self.cross_run_lookup:
            cross_keys = list(self.cross_run_lookup.keys())
            best_cross_match = process.extractOne(
                normalized,
                cross_keys,
                scorer=fuzz.WRatio,
            )
            if best_cross_match:
                best_norm, score, _ = best_cross_match
                if score >= self.auto_merge_threshold:
                    canonical = self.cross_run_lookup[best_norm]
                    self.cross_run_lookup[normalized] = canonical
                    res = ResolutionResult(
                        raw_name=clean_raw,
                        canonical_name=canonical,
                        match_score=float(score),
                        method="cross_run_match",
                        requires_review=False,
                        source_url=source_url,
                        entity_type=entity_type,
                        timestamp=now_ts,
                    )
                    self._log_resolution(res)
                    return res
                elif score >= self.manual_review_threshold:
                    canonical = self.cross_run_lookup[best_norm]
                    res = ResolutionResult(
                        raw_name=clean_raw,
                        canonical_name=clean_raw,
                        match_score=float(score),
                        method="manual_review",
                        requires_review=True,
                        source_url=source_url,
                        entity_type=entity_type,
                        timestamp=now_ts,
                    )
                    self._log_resolution(res)
                    self._log_review(res, tentative_canonical=canonical)
                    return res

        # Step 5: New Canonical Entity (< 75 score)
        # Register new entity in cross_run registry
        self.cross_run_lookup[normalized] = clean_raw
        res = ResolutionResult(
            raw_name=clean_raw,
            canonical_name=clean_raw,
            match_score=0.0,
            method="new_entity",
            requires_review=False,
            source_url=source_url,
            entity_type=entity_type,
            timestamp=now_ts,
        )
        self._log_resolution(res)
        return res

    def _log_resolution(self, res: ResolutionResult) -> None:
        """Write resolved entity to mapping CSV log."""
        if res.raw_name in self.logged_resolutions:
            return
        self.logged_resolutions[res.raw_name] = res

        if self.output_csv_path:
            try:
                with open(self.output_csv_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    method_str = (res.method or ("new_entity" if res.match_score == 0.0 else "seed_match")).strip()
                    if not method_str or method_str.lower() in ("none", "null"):
                        method_str = "new_entity" if res.match_score == 0.0 else "seed_match"
                    writer.writerow([
                        res.raw_name or "",
                        res.canonical_name or res.raw_name or "",
                        f"{res.match_score:.1f}",
                        method_str,
                        res.source_url or "",
                        res.entity_type or "STARTUP",
                        res.timestamp or datetime.now(timezone.utc).isoformat(),
                    ])
            except Exception as e:
                logger.error("Failed to write to entity mapping log: %s", e)

    def _log_review(self, res: ResolutionResult, tentative_canonical: str) -> None:
        """Write tentative match to manual review CSV log."""
        if self.review_csv_path:
            try:
                with open(self.review_csv_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        res.raw_name,
                        tentative_canonical,
                        f"{res.match_score:.1f}",
                        res.method,
                        res.source_url,
                        res.timestamp,
                    ])
            except Exception as e:
                logger.error("Failed to write to manual review log: %s", e)
