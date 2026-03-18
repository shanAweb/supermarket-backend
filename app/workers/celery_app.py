"""Celery application configuration with Redis broker."""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "supermarket",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task settings
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Result expiration (24 hours)
    result_expires=86400,
)

# Auto-discover tasks from app.workers.tasks
celery_app.autodiscover_tasks(["app.workers"])

# Celery Beat periodic schedule
celery_app.conf.beat_schedule = {
    "nightly-aggregation": {
        "task": "app.workers.tasks.nightly_aggregation",
        "schedule": crontab(hour=0, minute=0),  # midnight UTC
    },
}
