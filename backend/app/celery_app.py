from celery import Celery

from app.core.config import settings


celery_app = Celery(
    "digital_scientist",
    broker=settings.celery_broker_url,
    include=["app.tasks.pdf_processing"],
)

celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    result_backend=None,
    task_acks_late=True,
    task_ignore_result=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    timezone="UTC",
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
)
