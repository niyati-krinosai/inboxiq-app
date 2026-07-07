from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "inboxiq",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks", "app.workers.stream_pipeline"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "hourly-gmail-sync": {
            "task": "app.workers.tasks.sync_all_users",
            "schedule": float(settings.sync_interval_seconds),
        },
        "daily-digest": {
            "task": "app.workers.tasks.generate_all_digests",
            "schedule": 86400.0,
        },
        "freshness-refresh": {
            "task": "app.workers.tasks.refresh_all_freshness",
            "schedule": 43200.0,  # every 12 hours
        },
    },
)
