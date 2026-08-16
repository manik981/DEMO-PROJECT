"""Semantic Content Cleaner, Token Budgeter, and Boundary Chunker.

Applies approximate token counting with configurable safety margins, splits text
on semantic boundaries (headings, sections, paragraphs), and prunes boilerplate.
"""

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None  # type: ignore


# Common noisy boilerplate regex patterns (navigation, footers, cookie banners)
BOILERPLATE_PATTERNS = [
    r"(?i)cookie\s+policy.*?(accept|agree|decline|manage)",
    r"(?i)privacy\s+policy.*?terms\s+of\s+service",
    r"(?i)all\s+rights\s+reserved.*?\d{4}",
    r"(?i)subscribe\s+to\s+our\s+newsletter",
    r"(?i)sign\s+up\s+for\s+free",
    r"(?i)advertisement|sponsored\s+content",
    r"\[(?:Home|About|Contact|Pricing|Login|Sign Up|Careers)\]\(.*?\)",
]


class SemanticChunker:
    """Budgets token capacity, strips boilerplate, and chunks text at semantic boundaries."""

    def __init__(
        self,
        max_input_tokens: int = 5000,
        output_reserve_tokens: int = 1500,
        safety_margin_tokens: int = 500,
    ):
        self.max_input_tokens = max_input_tokens
        self.output_reserve_tokens = output_reserve_tokens
        self.safety_margin_tokens = safety_margin_tokens
        self.effective_limit = max_input_tokens - output_reserve_tokens - safety_margin_tokens

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using tiktoken if available, with character-heuristic fallback."""
        if not text:
            return 0
        if _ENC is not None:
            try:
                return len(_ENC.encode(text, disallowed_special=()))
            except Exception:
                pass
        # Fallback approximation: ~4 characters per token
        return max(1, len(text) // 4)

    def clean_boilerplate(self, raw_text: str) -> str:
        """Remove navigation menus, cookie consent banners, and common footer boilerplate."""
        if not raw_text:
            return ""

        cleaned = raw_text
        for pattern in BOILERPLATE_PATTERNS:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.MULTILINE)

        # Collapse excess empty lines and spaces
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return cleaned.strip()

    def split_semantic_blocks(self, text: str) -> List[str]:
        """Split text along Markdown headings (#, ##, ###) or paragraph double-newlines."""
        if not text:
            return []

        # Split on Markdown headers while retaining delimiter
        heading_splits = re.split(r"(?=(?:\n|^)#{1,3}\s+)", text)
        blocks: List[str] = []

        for block in heading_splits:
            block = block.strip()
            if not block:
                continue
            # If a block is still very large, split on double newlines
            if self.estimate_tokens(block) > self.effective_limit:
                paragraphs = block.split("\n\n")
                blocks.extend([p.strip() for p in paragraphs if p.strip()])
            else:
                blocks.append(block)

        return blocks

    def score_density(self, block: str) -> float:
        """Score content density based on text length and semantic indicator keywords."""
        if not block:
            return 0.0

        score = float(len(block))
        keywords = [
            "founded", "employees", "pricing", "free", "tier", "api", "github",
            "paper", "abstract", "model", "features", "salary", "remote", "company",
            "published", "version", "launch", "product", "startup", "funding"
        ]
        lower = block.lower()
        for kw in keywords:
            if kw in lower:
                score += 150.0

        return score

    def chunk_and_budget(self, raw_text: str, max_tokens: Optional[int] = None) -> str:
        """Clean text, budget token capacity, and return optimal semantic content under limit."""
        cleaned = self.clean_boilerplate(raw_text)
        token_limit = max_tokens or self.effective_limit

        current_tokens = self.estimate_tokens(cleaned)
        if current_tokens <= token_limit:
            return cleaned

        logger.info(
            "Payload (%d tokens) exceeds budget (%d tokens). Splitting on semantic boundaries.",
            current_tokens,
            token_limit,
        )

        blocks = self.split_semantic_blocks(cleaned)
        if not blocks:
            # Hard character cut if no natural blocks
            char_limit = token_limit * 4
            return cleaned[:char_limit]

        # Sort blocks by density score and select highest-signal chunks that fit in budget
        scored_blocks = sorted(blocks, key=self.score_density, reverse=True)
        selected_blocks: List[str] = []
        accumulated_tokens = 0

        for block in scored_blocks:
            block_tokens = self.estimate_tokens(block)
            if accumulated_tokens + block_tokens <= token_limit:
                selected_blocks.append(block)
                accumulated_tokens += block_tokens
            if accumulated_tokens >= token_limit:
                break

        if not selected_blocks and blocks:
            # Ensure at least first block fits (truncated if necessary)
            first_block = blocks[0]
            char_limit = token_limit * 4
            return first_block[:char_limit]

        return "\n\n".join(selected_blocks)
