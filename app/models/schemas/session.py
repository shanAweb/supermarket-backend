import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    video_path: str | None = None
    store_id: str | None = Field(default=None, max_length=100)
    camera_id: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class SessionResponse(BaseModel):
    id: uuid.UUID
    cv_job_id: str | None
    status: str
    video_filename: str | None
    customer_count: int | None
    grid_data: list[list[float]] | None = None
    heatmap_image_url: str | None = None
    initial_grid_url: str | None = None
    store_id: str | None
    camera_id: str | None
    notes: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    total: int
    items: list[SessionResponse]
