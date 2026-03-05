import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db.base import Base, TimestampMixin, UUIDMixin


class SessionStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Session(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cv_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status"),
        default=SessionStatus.QUEUED,
    )
    video_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    heatmap_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    initial_grid_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    store_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    camera_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    zone_analytics: Mapped[list["ZoneAnalytics"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    customer_counts: Mapped[list["CustomerCount"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
