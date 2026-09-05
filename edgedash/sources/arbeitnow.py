"""
arbeitnow.py — ArbeitnowSource: free public job board, no API key required.

API docs: https://www.arbeitnow.com/api/job-board-api
  GET https://www.arbeitnow.com/api/job-board-api?page=N
  Returns 175 listings per page.
  Pagination via links.next / meta.current_page.

Fields from the API:
  slug, company_name, title, description, remote, url,
  tags, job_types, location, created_at

Normalisation:
  external_id  <- slug          (stable identifier per the API docs)
  company      <- company_name
  posted_at    <- created_at (unix timestamp -> ISO-8601 string)
  description  <- HTML stripped to plain text
  raw          <- original API dict

Filtering (steering rule 11 / config):
  - Keep listings whose title OR description mentions at least one keyword
    from config.keywords (case-insensitive substring match).
  - Then filter by config.target_city (case-insensitive substring match
    in the `location` field).
  - If city filtering would leave fewer than 5 results, the city filter
    is relaxed and this is logged (steering rule 12 / fail-loud design).

Rate limiting:
  - 1 request per second per source (steering rule 14).
  - Page cap: 5 pages maximum.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from edgedash.sources.base import REQUIRED_KEYS, register
from edgedash.sources.http import SourceError, get_json

_API_BASE = "https://www.arbeitnow.com/api/job-board-api"
_MAX_PAGES = 5
_MIN_RESULTS_AFTER_CITY_FILTER = 5
_REQUEST_INTERVAL = 1.0  # seconds between pages


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(html: str) -> str:
    parser = _HTMLStripper()
    parser.feed(html)
    return re.sub(r"\s+", " ", parser.get_text()).strip()


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

@register
class ArbeitnowSource:
    name: str = "arbeitnow"

    def fetch(self, config: Any) -> list[dict]:
        """Fetch listings from Arbeitnow and return normalised dicts.

        Paginates up to _MAX_PAGES, stopping early when a page returns
        zero keyword-matching rows (signals we've scrolled past relevance).
        """
        keywords = [kw.lower() for kw in config.keywords]
        city = config.target_city.lower()

        raw_rows: list[dict] = []
        page = 1

        while page <= _MAX_PAGES:
            if page > 1:
                time.sleep(_REQUEST_INTERVAL)

            data = get_json(_API_BASE, params={"page": page})
            listings = data.get("data", [])

            if not listings:
                break

            keyword_matches = [r for r in listings if _matches_keywords(r, keywords)]
            raw_rows.extend(keyword_matches)
            print(
                f"  [arbeitnow] page {page}: {len(listings)} listings, "
                f"{len(keyword_matches)} keyword-matched"
            )

            if not keyword_matches:
                # No relevant results on this page — stop paging
                break

            next_url = data.get("links", {}).get("next")
            if not next_url:
                break

            page += 1

        print(f"  [arbeitnow] total keyword-matched across all pages: {len(raw_rows)}")

        # City filter
        city_filtered = [r for r in raw_rows if _matches_city(r, city)]

        if len(city_filtered) < _MIN_RESULTS_AFTER_CITY_FILTER:
            print(
                f"  [arbeitnow] city filter '{config.target_city}' left only "
                f"{len(city_filtered)} results (threshold: {_MIN_RESULTS_AFTER_CITY_FILTER}). "
                f"Relaxing city filter — returning all {len(raw_rows)} keyword-matched results."
            )
            final_rows = raw_rows
        else:
            final_rows = city_filtered

        print(
            f"  [arbeitnow] {len(raw_rows)} raw → "
            f"{len(city_filtered)} city-filtered → "
            f"{len(final_rows)} returned"
        )

        return [_normalise(r) for r in final_rows]


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def _matches_keywords(listing: dict, keywords: list[str]) -> bool:
    """Return True if any keyword appears in title or description."""
    haystack = (
        listing.get("title", "") + " " + listing.get("description", "")
    ).lower()
    return any(kw in haystack for kw in keywords)


def _matches_city(listing: dict, city: str) -> bool:
    location = listing.get("location", "") or ""
    return city in location.lower()


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normalise(listing: dict) -> dict:
    """Map Arbeitnow fields onto the canonical REQUIRED_KEYS schema."""
    created_at = listing.get("created_at")
    posted_at: str | None = None
    if isinstance(created_at, int):
        posted_at = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()
    elif isinstance(created_at, str) and created_at:
        posted_at = created_at

    description_html = listing.get("description") or ""
    description_text = _strip_html(description_html) or None

    row = {
        "source": ArbeitnowSource.name,
        "external_id": listing.get("slug") or None,
        "title": listing.get("title") or None,
        "company": listing.get("company_name") or None,
        "location": listing.get("location") or None,
        "url": listing.get("url") or None,
        "description": description_text,
        "posted_at": posted_at,
        "raw": listing,
    }

    # Guarantee all required keys are present, missing values -> None
    for key in REQUIRED_KEYS:
        row.setdefault(key, None)

    return row
