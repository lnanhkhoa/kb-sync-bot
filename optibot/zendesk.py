"""Minimal client for the public Zendesk Help Center articles API."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import requests

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://support.optisigns.com"
PAGE_SIZE = 100  # Zendesk cursor-pagination maximum
MAX_RETRIES = 5


def iter_articles(
    base_url: str = DEFAULT_BASE_URL,
    locale: str = "en-us",
    session: requests.Session | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield published articles for `locale`, most recently updated first, fetching pages lazily."""
    http = session or requests.Session()
    url: str | None = f"{base_url}/api/v2/help_center/{locale}/articles.json"
    params: dict[str, Any] | None = {"page[size]": PAGE_SIZE, "sort_by": "updated_at", "sort_order": "desc"}
    while url:
        data = _get_json(http, url, params)
        params = None  # `links.next` already carries the cursor and page size
        for article in data["articles"]:
            if not article.get("draft"):
                yield article
        url = data["links"]["next"] if data["meta"]["has_more"] else None


def _get_json(http: requests.Session, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
    for attempt in range(1, MAX_RETRIES + 1):
        resp = http.get(url, params=params, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            delay = float(resp.headers.get("Retry-After", 2**attempt))
            log.warning("GET %s -> %s, retry %d in %.0fs", resp.url, resp.status_code, attempt, delay)
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"giving up on {url} after {MAX_RETRIES} attempts")
