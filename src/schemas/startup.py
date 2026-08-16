from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel

from src.schemas.shared import SourceInfo


class StartupData(BaseModel):
    employeeCount: Optional[int] = None
    category: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None


class StartupContent(BaseModel):
    entityName: str
    data: StartupData


class StartupEntity(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["STARTUP"] = "STARTUP"
    source: SourceInfo
    content: StartupContent
    collectedAt: datetime
