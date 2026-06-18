"""MLAClient: a thin, polite wrapper over the MLA Statistics API.

Handles the one real constraint of this API: responses are paginated at ~100 rows.
``get_all`` transparently walks every page so callers get the complete result set.
"""

from __future__ import annotations

import datetime as dt
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

    def _request(self, path: str, params: dict[str, Any]) -> dict:
        """Single HTTP attempt. Raises MLAApiError on 5xx/429 or an error envelope."""
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

    @retry(
        retry=retry_if_exception_type((requests.RequestException, MLAApiError)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(config.MAX_RETRIES),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any]) -> dict:
        return self._request(path, params)

    def last_good_to(
        self, report_id: int, params: dict[str, Any], from_date: str, to_date: str
    ) -> str | None:
        """Largest end date in [from_date, to_date] the API accepts for this query.

        The API returns HTTP 500 whenever ``toDate`` runs past the latest published date
        (even by a single empty day), which fails the whole chunk. Acceptance is monotonic
        in ``toDate`` (ok up to the last available date, then 500s), so binary-search the
        boundary with single-attempt probes — no retry/backoff, since these 500s are
        deterministic, not transient. Returns an ISO date, or None if even ``from_date``
        has no data (the whole window is past the available range).
        """
        lo = dt.date.fromisoformat(from_date)
        hi = dt.date.fromisoformat(to_date)

        def ok(end: dt.date) -> bool:
            try:
                self._request(
                    f"/report/{report_id}",
                    {**params, "fromDate": from_date, "toDate": end.isoformat(), "page": 1},
                )
                return True
            except (MLAApiError, requests.RequestException):
                return False

        if ok(hi):
            return hi.isoformat()
        if not ok(lo):
            return None
        while (hi - lo).days > 1:  # invariant: ok(lo), not ok(hi)
            mid = lo + (hi - lo) // 2
            if ok(mid):
                lo = mid
            else:
                hi = mid
        return lo.isoformat()

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
