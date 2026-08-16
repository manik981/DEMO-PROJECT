"""Deterministic Role-Family Classifier for Job Listings.

Uses exact regex/keyword matching to categorize job titles into:
- Engineering
- Research
- Product
- Other

Guarantees 100% determinism, zero LLM cost, and never alters the original title.
"""

import re
from typing import Literal

RoleFamily = Literal["Engineering", "Research", "Product", "Other"]

# Ordered evaluation patterns: Research checked first to avoid classifying "Research Engineer" as generic Engineering
RESEARCH_PATTERNS = [
    r"\bresearch\s*engineer\b",
    r"\bresearch(?:er|ers)?\b",
    r"\bscientist(?:s)?\b",
    r"\br&d\b",
    r"\bpost[\s-]?doc(?:toral)?\b",
    r"\bfellow(?:ship)?\b",
    r"\bphd\b",
]

PRODUCT_PATTERNS = [
    r"\bproduct manager(?:s)?\b",
    r"\btechnical product\b",
    r"\bproduct lead\b",
    r"\bhead of product\b",
    r"\bvp of product\b",
    r"\bproduct director\b",
    r"\bproduct designer(?:s)?\b",
    r"\bui/ux\b",
    r"\bux designer\b",
    r"\bpm\b",
]

ENGINEERING_PATTERNS = [
    r"\bengineer(?:s|ing)?\b",
    r"\bdeveloper(?:s)?\b",
    r"\bdev\b",
    r"\bmlops\b",
    r"\bdevops\b",
    r"\bbackend\b",
    r"\bfrontend\b",
    r"\bfull[\s-]?stack\b",
    r"\bdata engineer(?:s)?\b",
    r"\bplatform\b",
    r"\binfrastructure\b",
    r"\bsystems\b",
    r"\barchitect\b",
    r"\bsoftware\b",
    r"\bcoder\b",
    r"\bprogrammer\b",
]


def classify_role_family(job_title: str) -> RoleFamily:
    """Classify raw job title deterministically without mutating the original text."""
    if not job_title:
        return "Other"

    title_lower = job_title.lower().strip()

    # 1. Research takes precedence (e.g. "Research Engineer", "AI Scientist")
    for pattern in RESEARCH_PATTERNS:
        if re.search(pattern, title_lower):
            return "Research"

    # 2. Product
    for pattern in PRODUCT_PATTERNS:
        if re.search(pattern, title_lower):
            return "Product"

    # 3. Engineering
    for pattern in ENGINEERING_PATTERNS:
        if re.search(pattern, title_lower):
            return "Engineering"

    # 4. Fallback
    return "Other"
