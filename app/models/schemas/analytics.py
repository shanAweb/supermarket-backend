import uuid
from datetime import datetime

from pydantic import BaseModel


class ZoneGridResponse(BaseModel):
    grid: list[list[float]]


class ZoneRanking(BaseModel):
    row: int
    col: int
    avg_heat: float
    label: str


class ZoneRankingsResponse(BaseModel):
    rankings: list[ZoneRanking]


class CustomerCountData(BaseModel):
    session_id: uuid.UUID
    created_at: datetime
    customer_count: int


class CustomerCountsResponse(BaseModel):
    data: list[CustomerCountData]


class PeakZonesResponse(BaseModel):
    rankings: list[ZoneRanking]


class SessionComparisonGrid(BaseModel):
    id: uuid.UUID
    grid: list[list[float]]


class ComparisonResponse(BaseModel):
    session_a: SessionComparisonGrid
    session_b: SessionComparisonGrid
    delta: list[list[float]]
