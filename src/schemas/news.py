from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from src.schemas.shared import SourceInfo


class NewsContent(BaseModel):
    title: str
    url: str
    published_date: datetime
    summary: str


class NewsEntity(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["NEWS"] = "NEWS"
    source: SourceInfo
    content: NewsContent
    collectedAt: datetime
