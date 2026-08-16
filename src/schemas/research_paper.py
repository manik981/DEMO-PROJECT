from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel


class ResearchPaperContent(BaseModel):
    title: str
    authors: List[str]
    paper_url: str
    github_url: Optional[str] = None
    github_stars: Optional[int] = None
    published_date: datetime


class ResearchPaperEntity(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["RESEARCH_PAPER"] = "RESEARCH_PAPER"
    content: ResearchPaperContent
