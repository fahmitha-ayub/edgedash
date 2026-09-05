"""
state.py — System state inspection (steering rule 28).

NO LLM. Deterministic. Pure queries: counts and max(timestamp).

Public API
----------
read_state(config: Any, now: datetime) -> SystemState
  Read system state at a given point in time. `now` is a parameter for testability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class SystemState:
    """Current system state snapshot."""
    last_fetch_at: str | None  # ISO timestamp
    hours_since_fetch: float  # hours since last fetch (or infinity if never)
    unscored_count: int
    gaps_computed_at: str | None  # ISO timestamp
    gaps_stale: bool  # true if any score is newer than gap snapshot
    last_cycle_verdict: str | None
    last_cycle_at: str | None  # ISO timestamp


def read_state(config: Any, now: datetime) -> SystemState:
    """Read system state at a given point in time.
    
    Cheap queries only: counts and max(timestamp). No full table loads.
    All storage access goes through the storage module (rule 2).
    
    Args:
        config: Configuration object
        now: Current time (parameter for testability, never datetime.now() inside)
    
    Returns:
        SystemState snapshot
    """
    from edgedash import storage
    
    storage.configure(config.db_path)
    
    # Last fetch time
    last_fetch_at = storage.last_fetch_time()
    if last_fetch_at:
        try:
            # Handle both ISO format strings and Postgres timestamps
            last_fetch_str = str(last_fetch_at)
            last_fetch_dt = datetime.fromisoformat(last_fetch_str.replace("Z", "+00:00"))
            hours_since_fetch = (now - last_fetch_dt).total_seconds() / 3600.0
        except (ValueError, AttributeError, TypeError):
            hours_since_fetch = float("inf")
    else:
        hours_since_fetch = float("inf")
    
    # Unscored count
    unscored_count = storage.count_unscored()
    
    # Gap analysis state
    gaps_computed_at = _last_gap_analysis_time()
    gaps_stale = _gaps_are_stale(gaps_computed_at)
    
    # Last cycle
    last_cycle_verdict, last_cycle_at = _last_cycle_info()
    
    return SystemState(
        last_fetch_at=last_fetch_at,
        hours_since_fetch=hours_since_fetch,
        unscored_count=unscored_count,
        gaps_computed_at=gaps_computed_at,
        gaps_stale=gaps_stale,
        last_cycle_verdict=last_cycle_verdict,
        last_cycle_at=last_cycle_at,
    )


def _last_gap_analysis_time() -> str | None:
    """Return the timestamp of the most recent gap analysis, or None."""
    from edgedash import storage
    
    with storage._connection() as conn:
        row = storage._fetchone(conn, "SELECT MAX(computed_at) as latest FROM gap_snapshots")
    
    return row["latest"] if row else None


def _gaps_are_stale(gaps_computed_at: str | None) -> bool:
    """Return True if any score is newer than the gap snapshot."""
    if gaps_computed_at is None:
        return True  # Never computed
    
    from edgedash import storage
    
    with storage._connection() as conn:
        row = storage._fetchone(
            conn,
            """
            SELECT COUNT(*) as count
            FROM listings
            WHERE scored_at IS NOT NULL AND scored_at > :gaps_at
            """,
            {"gaps_at": gaps_computed_at},
        )
    
    return row["count"] > 0 if row else False


def _last_cycle_info() -> tuple[str | None, str | None]:
    """Return (verdict, timestamp) of the most recent orchestrator cycle."""
    from edgedash import storage
    
    with storage._connection() as conn:
        row = storage._fetchone(
            conn,
            """
            SELECT verdict, finished_at 
            FROM cycle_log 
            WHERE agent = 'orchestrator' 
            ORDER BY finished_at DESC 
            LIMIT 1
            """
        )
    
    if row:
        return row["verdict"], row["finished_at"]
    return None, None
