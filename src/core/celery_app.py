"""Celery application instance.

Task modules are registered here by later phases; the worker and beat containers
import this module as ``src.core.celery_app:celery_app``.
"""

from celery import Celery

from src.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "online_cinema",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
