from celery import Celery
from kombu import Queue

from lumen.config import get_settings

settings = get_settings()
ingestion_queues = [Queue(f"ingest-{shard:02d}") for shard in range(16)]

celery_app = Celery(
    "lumen",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["lumen.tasks"],
)
celery_app.conf.update(
    task_default_queue="ingest-00",
    task_queues=ingestion_queues + [Queue("dead-letter")],
    task_routes={
        "lumen.ingest_document": {"queue": "ingest-00"},
        "lumen.record_dead_letter": {"queue": "dead-letter"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    broker_transport_options={"visibility_timeout": 3600},
)
