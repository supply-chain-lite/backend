"""Celery application package.

Exposes the configured Celery ``app`` instance so the worker can be started
from the project root with ``celery -A celery_app worker``.
"""

from celery_app.celery import app

__all__ = ["app"]
