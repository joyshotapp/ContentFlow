"""Build metadata helpers for deployment traceability."""

from __future__ import annotations

from contentflow import __version__
from contentflow.config import settings


def get_build_info() -> dict[str, str]:
    return {
        "app_version": __version__,
        "build_commit": settings.contentflow_build_commit,
        "build_time": settings.contentflow_build_time,
        "build_source": settings.contentflow_build_source,
    }