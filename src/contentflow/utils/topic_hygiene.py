"""Helpers for rejecting low-signal or obviously invalid content topics."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def normalize_topic_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _project_blacklist(project) -> set[str]:
    values: set[str] = set()
    for raw in (
        getattr(project, "slug", ""),
        getattr(project, "name", ""),
        getattr(project, "brand_name", ""),
    ):
        normalized = normalize_topic_text(raw).casefold()
        if normalized:
            values.add(normalized)

    brand_url = normalize_topic_text(getattr(project, "brand_url", ""))
    if brand_url:
        hostname = (urlparse(brand_url).hostname or brand_url).casefold()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        if hostname:
            values.add(hostname)
            first_label = hostname.split(".", 1)[0]
            if first_label:
                values.add(first_label)
    return values


def is_viable_topic(title: str | None, keyword: str | None = None, project=None) -> tuple[bool, str | None]:
    candidate = normalize_topic_text(title or keyword)
    keyword_text = normalize_topic_text(keyword or title)
    if not candidate:
        return False, "empty"

    token_count = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", candidate))
    if token_count < 2:
        return False, "too_short"

    if project is not None:
        blacklist = _project_blacklist(project)
        lowered = candidate.casefold()
        lowered_kw = keyword_text.casefold()
        if lowered in blacklist or lowered_kw in blacklist:
            return False, "brand_term"

    return True, None