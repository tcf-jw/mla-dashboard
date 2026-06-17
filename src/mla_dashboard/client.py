"""MLAClient: a thin, polite wrapper over the MLA Statistics API.

Handles the one real constraint of this API: responses are paginated at ~100 rows.
``get_all`` transparently walks every page so callers get the complete result set.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import config

DATA_KEY = "data"
TOTAL_KEY = "total number rows"


class MLAApiError(RuntimeError):
    """Raised when the API returns an error envelope instead of data."""


class MLAClient:
    def __init__(self, base_url: str = config.BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    @retry(
        retry=retry_if_exception_type((requests.RequestException, MLAApiError)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(config.MAX_RETRIES),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any]) -> dict:
        time.sleep(config.REQUEST_DELAY_S)
        resp = self.session.get(
            f"{self.base_url}{path}", params=params, timeout=config.REQUEST_TIMEOUT_S
        )
        # MLA returns 200 with a {"Message": ...} body on bad params / transient lambda
        # errors. Treat lambda/5xx as retryable; treat param errors as fatal.
        if resp.status_code >= 500 or resp.status_code == 429:
            raise MLAApiError(f"{resp.status_code} from {path}")
        resp.raise_for_status()
        body = resp.json()
        if DATA_KEY not in body:
            msg = body.get("Message") or body.get("message") or str(body)[:200]
            if "lambda" in msg.lower():  # transient backend hiccup -> retry
                raise MLAApiError(msg)
            raise MLAApiError(f"{path} {params}: {msg}")
        return body

    def get_reference(self, path: str) -> list[dict]:
        """Fetch a non-paginated reference list (/indicator, /saleyard, /report)."""
        return self._get(path, {}).get(DATA_KEY, [])

    def get_all(self, report_id: int, params: dict[str, Any]) -> list[dict]:
        """Return every row across all pages for /report/<report_id>."""
        return list(self.iter_all(report_id, params))

    def iter_all(self, report_id: int, params: dict[str, Any]) -> Iterator[dict]:
        path = f"/report/{report_id}"
        page = 1
        fetched = 0
        total = None
        while True:
            body = self._get(path, {**params, "page": page})
            rows = body.get(DATA_KEY, [])
            if total is None:
                total = body.get(TOTAL_KEY, len(rows))
            yield from rows
            fetched += len(rows)
            # Stop when we've seen every row, or the page came back short/empty.
            if not rows or fetched >= total or len(rows) < config.PAGE_SIZE:
                break
            page += 1
