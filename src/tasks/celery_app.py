"""The project's single Celery application.

The worker and beat containers load this module as
``src.tasks.celery_app:celery_app``. Task modules are not imported here; they
register themselves through ``autodiscover_tasks``, which keeps this file free
of import cycles back into the service layer.

Nothing here touches the network: constructing the app and updating its config
performs no I/O, so the module imports cleanly with no broker running.
"""

from celery import Celery
from celery.schedules import crontab

from src.core.config import get_settings

__all__ = ["celery_app"]

settings = get_settings()

celery_app = Celery(
    "online_cinema",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
)

celery_app.autodiscover_tasks(["src.tasks"])

celery_app.conf.beat_schedule = {
    "purge-expired-activation-tokens": {
        "task": "src.tasks.tokens.purge_expired_activation_tokens",
        "schedule": crontab(minute=0),
    },
    "purge-expired-password-reset-tokens": {
        "task": "src.tasks.tokens.purge_expired_password_reset_tokens",
        # Half an hour after the activation sweep rather than alongside it: both
        # jobs open their own session and take table-wide delete locks, and there
        # is no reason for them to do that at the same instant.
        "schedule": crontab(minute=30),
    },
}
