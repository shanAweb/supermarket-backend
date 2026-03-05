import uuid

from pydantic import BaseModel, Field


class InsightQueryRequest(BaseModel):
    question: str = Field(min_length=1)
    session_ids: list[uuid.UUID] | None = None
    store_id: str | None = None


class AutoInsightResponse(BaseModel):
    session_id: uuid.UUID
    summary: str
    hot_zones: list[str]
    cold_zones: list[str]
    recommendations: list[str]
