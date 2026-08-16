from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel


class JobContent(BaseModel):
    company: str
    title: Optional[str] = "AI Engineer"
    source_url: Optional[str] = ""
    source_name: Optional[str] = "Jobs Board"
    date: datetime
    is_remote: bool = True
    role_family: str = "Engineering"


class JobEntity(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["JOB"] = "JOB"
    content: JobContent
