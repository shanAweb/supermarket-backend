import uuid

from sqlalchemy import Float, ForeignKey, SmallInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db.base import Base, UUIDMixin


class ZoneAnalytics(UUIDMixin, Base):
    __tablename__ = "zone_analytics"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    col: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    heat_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Relationship
    session: Mapped["Session"] = relationship(back_populates="zone_analytics")
