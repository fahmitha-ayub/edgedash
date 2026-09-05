"""
sources/http.py — The ONLY place in the project that performs HTTP requests.

Public API
----------
get_json(url, params=None, headers=None, timeout=10) -> dict | list

Enforces:
  - 10-second timeout (configurable)
  - 2 retries with exponential back-off (1s, 2s)
  - A descriptive User-Agent header
  - Raises SourceError with a clear message on failure

Dependency: requests (third-party, justified: robust retry semantics,
connection pooling, and clean header management are non-trivial with
urllib alone, and requests is the de-facto standard for this work).
"""
from __future__ import annotations

import time
from typing import Any

import requests


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class SourceError(Exception):
    """Raised when an HTTP request fails after all retries are exhausted."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "EdgeDash/0.1 (career intelligence agent; "
    "github.com/edgedash) Python-requests"
)
_MAX_RETRIES = 2
_BASE_BACKOFF = 1.0   # seconds; doubles on each retry


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
) -> dict | list:
    """GET `url` and return the parsed JSON body.

    Retries up to _MAX_RETRIES times with exponential back-off.
    Raises SourceError if all attempts fail.
    """
    merged_headers = {"User-Agent": _USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_exc: Exception | None = None

    for attempt in range(1 + _MAX_RETRIES):
        try:
            response = requests.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout as exc:
            last_exc = exc
            _maybe_backoff(attempt, url, reason=f"timeout after {timeout}s")

        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else "?"
            if status == 429 or (isinstance(status, int) and status >= 500):
                _maybe_backoff(attempt, url, reason=f"HTTP {status}")
            else:
                # 4xx (other than 429) — retrying won't help
                raise SourceError(
                    f"HTTP {status} fetching {url}: {exc}"
                ) from exc

        except requests.exceptions.RequestException as exc:
            last_exc = exc
            _maybe_backoff(attempt, url, reason=str(exc))

    raise SourceError(
        f"All {1 + _MAX_RETRIES} attempts failed for {url}: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _maybe_backoff(attempt: int, url: str, reason: str) -> None:
    """Sleep before the next retry; do nothing after the last attempt."""
    if attempt < _MAX_RETRIES:
        delay = _BASE_BACKOFF * (2 ** attempt)
        time.sleep(delay)
