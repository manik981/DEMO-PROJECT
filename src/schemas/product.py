from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from src.schemas.shared import SourceInfo


class ProductContent(BaseModel):
    startupName: str
    pricingModel: Literal["FREE", "FREEMIUM", "PAID", "ENTERPRISE"]


class ProductEntity(BaseModel):
    schemaVersion: str = "1.0"
    recordType: Literal["PRODUCT"] = "PRODUCT"
    source: SourceInfo
    content: ProductContent
    collectedAt: datetime
