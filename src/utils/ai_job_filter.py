"""AI Relevance Validator for Job Postings.

Strictly filters candidate job listings to ensure they belong to Artificial Intelligence,
Machine Learning, Deep Learning, NLP, Computer Vision, Data Science, LLM, or AI Engineering domains.
"""

import re
from typing import List, Optional

AI_KEYWORDS_REGEX = [
    r"\bai\b",
    r"\bartificial\s+intelligence\b",
    r"\bml\b",
    r"\bmachine\s+learning\b",
    r"\bdeep\s+learning\b",
    r"\bneural(?:\s+network)?\b",
    r"\bnlp\b",
    r"\bnatural\s+language\b",
    r"\bllm(?:s)?\b",
    r"\blarge\s+language\s+model(?:s)?\b",
    r"\bgenerative\s+ai\b",
    r"\bgenai\b",
    r"\bcomputer\s+vision\b",
    r"\bcv\s+engineer\b",
    r"\bdata\s+scien(?:ce|tist|tists)\b",
    r"\bdata\s+engineer(?:ing|s)?\b",
    r"\bdata\s+analyst(?:s)?\b",
    r"\bdata\s+analytics\b",
    r"\bdata\s+architect\b",
    r"\bdata\s+pipeline\b",
    r"\bbig\s+data\b",
    r"\bbusiness\s+intelligence\b",
    r"\bbi\s+developer\b",
    r"\bquantitative\s+analyst\b",
    r"\bquant\b",
    r"\bai\s+engineer(?:ing)?\b",
    r"\bmlops\b",
    r"\bllmops\b",
    r"\bprompt\s+engineer(?:ing)?\b",
    r"\bresearch\s+scientist\b",
    r"\bapplied\s+scientist\b",
    r"\bai\s+researcher\b",
    r"\bmachine\s+learning\s+scientist\b",
    r"\bpytorch\b",
    r"\btensorflow\b",
    r"\bkeras\b",
    r"\bjax\b",
    r"\btransformers?\b",
    r"\bdiffusion\b",
    r"\brag\b",
    r"\bretrieval\s+augmented\s+generation\b",
    r"\bembeddings?\b",
    r"\bvector\s+database\b",
    r"\bvector\s+search\b",
    r"\brobotics\b",
    r"\bautonomous\b",
    r"\breinforcement\s+learning\b",
    r"\brlhf\b",
    r"\blangchain\b",
    r"\bllamaindex\b",
    r"\bhugging\s*face\b",
    r"\bagent(?:ic)?\b",
    r"\bai\s+agent(?:s)?\b",
    r"\bmodel\s+evaluation\b",
    r"\bfine-tuning\b",
    r"\bpredictive\s+model(?:ing)?\b",
    r"\bstatistical\s+model(?:ing)?\b",
    r"\bstatistics\b",
    r"\bpyspark\b",
    r"\bdatabricks\b",
    r"\bsnowflake\b",
    r"\bpandas\b",
    r"\bnumpy\b",
    r"\bscikit-learn\b",
    r"\bsklearn\b",
    r"\bjupyter\b",
]

AI_COMPANIES = {
    "openai", "anthropic", "deepmind", "google deepmind", "mistral", "cohere",
    "meta ai", "xai", "stability ai", "perplexity", "hugging face", "scale ai",
    "runway", "elevenlabs", "character.ai", "jasper", "pinecone", "weaviate",
    "qdrant", "midjourney", "databricks", "snowflake", "langchain", "llamaindex",
    "cursor", "together ai", "replicate", "modal", "fireworks ai", "groq",
    "inflection ai", "glean", "harvey", "writer", "synthesia", "shield ai",
    "aidevboard", "artificial intelligence jobs", "remoteok ai", "datarobot",
    "anyscale", "coactive", "weights & biases", "wandb", "labelbox", "snorkle ai"
}


def is_ai_job(
    title: str,
    company: str = "",
    tags: Optional[List[str]] = None,
    description: str = "",
    source_name: str = "",
) -> bool:
    """Determine if a job listing is authentic AI/ML/Data intelligence."""
    title_lower = (title or "").lower().strip()
    company_lower = (company or "").lower().strip()
    source_lower = (source_name or "").lower().strip()

    # 1. Check if from an AI-dedicated source or company
    for ai_corp in AI_COMPANIES:
        if ai_corp in company_lower or ai_corp in source_lower:
            return True

    # 2. Check title keywords (Strongest Signal)
    for pattern in AI_KEYWORDS_REGEX:
        if re.search(pattern, title_lower):
            return True

    # 3. Check tags
    if tags:
        for tag in tags:
            tag_lower = str(tag).lower().strip()
            for pattern in AI_KEYWORDS_REGEX:
                if re.search(pattern, tag_lower):
                    return True

    # 4. Check description body
    if description:
        desc_lower = description.lower()
        match_count = 0
        for pattern in AI_KEYWORDS_REGEX:
            if re.search(pattern, desc_lower):
                match_count += 1
                if match_count >= 2:
                    return True

    return False
