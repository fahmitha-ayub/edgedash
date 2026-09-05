"""
fetcher.py — real Fetcher agent.

Reads `config.sources` to decide which sources to run, instantiates each
from the SOURCES registry, calls fetch(config), and writes results via
storage.upsert_listings.

Per-source fault isolation (steering rule 12):
  A source failure is caught, logged to cycle_log, and printed as a warning.
  The remaining sources are unaffected.

The listing id is computed by storage.make_listing_id (source + url hash)
so this module contains no second implementation of that logic.
"""
from __future__ import annotations

import traceback
from typing import Any

from edgedash.agents.base import AgentResult
from edgedash.sources.base import SOURCES
from edgedash.sources.http import SourceError

# Trigger registration of all known sources so SOURCES is populated.
import edgedash.sources.arbeitnow  # noqa: F401


class Fetcher:
    name: str = "fetcher"

    def run(self, config: Any, storage_mod: Any, stop_conditions: dict[str, Any] | None = None) -> AgentResult:
        """Run each enabled source, combine rows, write to storage.
        
        Args:
            config: Configuration object
            storage_mod: Storage module
            stop_conditions: Optional limits from orchestrator (max_pages, max_listings)
        """
        # Note: stop_conditions not currently enforced in fetcher
        # Future: pass max_listings to source.fetch() when sources support it
        
        from edgedash.storage import utc_now, log_cycle, make_listing_id

        enabled: list[str] = config.sources
        fetched_at = utc_now()

        source_summaries: list[str] = []
        all_rows: list[dict] = []

        for source_name in enabled:
            if source_name not in SOURCES:
                msg = f"Source '{source_name}' not found in registry."
                print(f"  ⚠ [fetcher] {msg}")
                source_summaries.append(f"{source_name}: FAILED ({msg})")
                log_cycle(
                    agent=f"fetcher.{source_name}",
                    started_at=fetched_at,
                    finished_at=utc_now(),
                    records_touched=0,
                    status="failed",
                    notes=msg,
                )
                continue

            source_start = utc_now()
            source_cls = SOURCES[source_name]
            source_instance = source_cls()

            try:
                rows = source_instance.fetch(config)
            except (SourceError, Exception) as exc:
                short = _short_exc(exc)
                print(f"  ⚠ [fetcher] source '{source_name}' failed: {short}")
                source_summaries.append(f"{source_name}: FAILED ({short})")
                log_cycle(
                    agent=f"fetcher.{source_name}",
                    started_at=source_start,
                    finished_at=utc_now(),
                    records_touched=0,
                    status="failed",
                    notes=f"{type(exc).__name__}: {short}",
                )
                continue

            # Attach fetched_at and compute stable id before upsert
            prepared = _prepare_rows(rows, fetched_at, make_listing_id)
            new_count = storage_mod.upsert_listings(prepared)

            summary = f"{source_name}: {len(prepared)} rows ({new_count} new)"
            source_summaries.append(summary)
            all_rows.extend(prepared)

            log_cycle(
                agent=f"fetcher.{source_name}",
                started_at=source_start,
                finished_at=utc_now(),
                records_touched=new_count,
                status="ok",
                notes=summary,
            )

        total_new = sum(
            1 for s in source_summaries
            if "FAILED" not in s
            # exact new count already logged per source; sum from upsert
        )
        # Recompute total_new cleanly from the prepared rows we actually wrote.
        # We can't easily re-count after the fact, so extract from summaries.
        total_new = _sum_new_from_summaries(source_summaries)

        notes = " | ".join(source_summaries) if source_summaries else "no sources configured"

        return AgentResult(
            agent=self.name,
            status="ok" if all_rows or not enabled else "ok",
            records_touched=total_new,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prepare_rows(
    rows: list[dict],
    fetched_at: str,
    make_listing_id: Any,
) -> list[dict]:
    """Add fetched_at and stable id; map source-layer keys to storage keys."""
    prepared = []
    for r in rows:
        row: dict = {
            "source":      r.get("source"),
            "url":         r.get("url"),
            "title":       r.get("title") or "Untitled",
            "company":     r.get("company") or "Unknown",
            "location":    r.get("location") or "Unknown",
            "description": r.get("description") or "",
            "posted_at":   r.get("posted_at"),
            "fetched_at":  fetched_at,
            "fit_score":   None,
            "fit_reason":  None,
        }
        row["id"] = make_listing_id(row["source"] or "", row["url"] or "")
        prepared.append(row)
    return prepared


def _short_exc(exc: Exception) -> str:
    """Return a one-line description of an exception."""
    return str(exc).split("\n")[0][:200]


def _sum_new_from_summaries(summaries: list[str]) -> int:
    """Extract and sum the '(N new)' counts from summary strings."""
    import re
    total = 0
    for s in summaries:
        m = re.search(r"\((\d+) new\)", s)
        if m:
            total += int(m.group(1))
    return total
