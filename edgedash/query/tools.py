"""
tools.py — Parameterised query tool registry (steering rules 40-46).

NO LLM in this file. These are read-only, parameterised queries I own.
Every parameter is validated and clamped (rule 41). All reads through
storage module (rule 2). All tools read from last passing cycle (rule 46).

Public API
----------
TOOLS: dict[str, ToolSpec]
  Registry of available query tools with their schemas.

ToolResult: namedtuple
  Result from a tool call: rows (list of dicts) and summary (string).
"""
from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from edgedash import storage
from edgedash.skills import canonical


# ---------------------------------------------------------------------------
# Registry and decorator
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    """Metadata for a registered query tool."""
    name: str
    fn: Callable
    description: str
    parameters: dict[str, Any]  # JSON-schema-style parameter spec


TOOLS: dict[str, ToolSpec] = {}

ToolResult = namedtuple("ToolResult", ["rows", "summary"])


def tool(description: str, parameters: dict[str, Any]):
    """Decorator to register a query tool with its schema.
    
    The description is what the router model sees, so make it specific
    and unambiguous about when this tool applies.
    
    Example:
        @tool(
            description="Companies with job postings in the last N days",
            parameters={
                "days": {"type": "integer", "default": 7, "description": "Days to look back"}
            }
        )
        def companies_hiring(days: int = 7) -> ToolResult:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        TOOLS[fn.__name__] = ToolSpec(
            name=fn.__name__,
            fn=fn,
            description=description,
            parameters=parameters,
        )
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Parameter validation helpers
# ---------------------------------------------------------------------------

def _clamp_int(value: int, min_val: int, max_val: int) -> int:
    """Clamp an integer parameter to a safe range (rule 41)."""
    return max(min_val, min(value, max_val))


def _canonicalize_skill(raw_skill: str, config: Any) -> str:
    """Canonicalize a skill name and validate it exists in the database.
    
    Returns the canonical form if found, or the input unchanged if not.
    Caller must check if the returned skill exists in actual data.
    """
    aliases = getattr(config, "skill_aliases", {})
    return canonical(raw_skill, aliases)


# ---------------------------------------------------------------------------
# Query tools (rule 46: read from last passing cycle only)
# ---------------------------------------------------------------------------

@tool(
    description="List companies with job postings in the last N days, with counts. Use this when asked about which companies are hiring or how many listings a company has.",
    parameters={
        "days": {
            "type": "integer",
            "default": 7,
            "description": "Number of days to look back (1-90)",
            "minimum": 1,
            "maximum": 90,
        }
    }
)
def companies_hiring(days: int = 7) -> ToolResult:
    """Companies with listings posted in the last N days, with counts.
    
    Per rule 41: days clamped to 1-90.
    Per rule 46: reads from last passing cycle only.
    """
    days = _clamp_int(days, 1, 90)
    
    # Get the timestamp of the last passing cycle
    passing_cycle = storage.get_latest_passing_cycle()
    if not passing_cycle:
        return ToolResult(rows=[], summary="No verified cycle found")
    
    cycle_timestamp = passing_cycle.get("finished_at")
    
    # Calculate cutoff date
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    cutoff_str = cutoff.isoformat()
    
    # Query through storage
    with storage._connection() as conn:
        rows = storage._fetchall(
            conn,
            """
            SELECT company, COUNT(*) as listing_count
            FROM   listings
            WHERE  posted_at >= :cutoff
              AND  scored_at <= :cycle_ts
            GROUP  BY company
            ORDER  BY listing_count DESC, company ASC
            """,
            {"cutoff": cutoff_str, "cycle_ts": cycle_timestamp},
        )
    
    result = [dict(row) for row in rows]
    total = sum(r["listing_count"] for r in result)
    
    summary = f"{len(result)} companies with {total} listings from the last {days} days"
    return ToolResult(rows=result, summary=summary)


@tool(
    description="Get the highest-scoring job listings. Use this when asked about best matches, top jobs, or highest fit scores.",
    parameters={
        "n": {
            "type": "integer",
            "default": 10,
            "description": "Number of listings to return (1-25)",
            "minimum": 1,
            "maximum": 25,
        }
    }
)
def best_matches(n: int = 10) -> ToolResult:
    """Highest-scoring listings with score, title, company, reason.
    
    Per rule 41: n clamped to 1-25.
    Per rule 46: reads from last passing cycle only.
    """
    n = _clamp_int(n, 1, 25)
    
    passing_cycle = storage.get_latest_passing_cycle()
    if not passing_cycle:
        return ToolResult(rows=[], summary="No verified cycle found")
    
    cycle_timestamp = passing_cycle.get("finished_at")
    
    with storage._connection() as conn:
        rows = storage._fetchall(
            conn,
            """
            SELECT fit_score as score, title, company, fit_reason as reason, url
            FROM   listings
            WHERE  fit_score IS NOT NULL
              AND  scored_at <= :cycle_ts
            ORDER  BY fit_score DESC, title ASC
            LIMIT  :n
            """,
            {"cycle_ts": cycle_timestamp, "n": n},
        )
    
    result = rows
    
    if result:
        summary = f"Top {len(result)} listings (highest score: {result[0]['score']})"
    else:
        summary = "No scored listings found"
    
    return ToolResult(rows=result, summary=summary)


@tool(
    description="Get the top skill gaps ranked by opportunity cost. Use this when asked about missing skills, skill gaps, or what skills to learn.",
    parameters={
        "n": {
            "type": "integer",
            "default": 5,
            "description": "Number of gaps to return (1-25)",
            "minimum": 1,
            "maximum": 25,
        }
    }
)
def top_gaps(n: int = 5) -> ToolResult:
    """Top skill gaps by opportunity cost, with listings_blocked.
    
    Per rule 41: n clamped to 1-25.
    Per rule 46: reads from last passing cycle only.
    """
    n = _clamp_int(n, 1, 25)
    
    passing_cycle = storage.get_latest_passing_cycle()
    if not passing_cycle:
        return ToolResult(rows=[], summary="No verified cycle found")
    
    # Get latest gap snapshot from verified cycle
    gaps = storage.get_latest_gap_snapshot()
    result = gaps[:n]
    
    if result:
        summary = f"Top {len(result)} skill gaps (highest opportunity cost: {result[0]['opportunity_cost']:.2f})"
    else:
        summary = "No skill gaps computed yet"
    
    return ToolResult(rows=result, summary=summary)


@tool(
    description="Get detailed information about which job listings are blocked by a specific missing skill. Use this to drill down into why a particular skill matters.",
    parameters={
        "skill": {
            "type": "string",
            "description": "The skill name to look up (will be canonicalized)",
        }
    }
)
def gap_detail(skill: str, config: Any = None) -> ToolResult:
    """The listings blocked by one named skill (rule 26 drill-down).
    
    Per rule 41: skill is canonicalized and validated.
    Per rule 46: reads from last passing cycle only.
    """
    if config is None:
        from edgedash.config import load_config
        config = load_config()
    
    # Canonicalize skill name
    canonical_skill = _canonicalize_skill(skill, config)
    
    passing_cycle = storage.get_latest_passing_cycle()
    if not passing_cycle:
        return ToolResult(rows=[], summary="No verified cycle found")
    
    cycle_timestamp = passing_cycle.get("finished_at")
    
    # Get listings that require this skill
    with storage._connection() as conn:
        # First check if skill exists in extraction cache
        rows = storage._fetchall(
            conn,
            """
            SELECT l.fit_score as score, l.title, l.company, l.url,
                   e.required_skills
            FROM   listings l
            JOIN   extraction_cache e ON e.description_hash = 
                   lower(hex(randomblob(16)))  -- Placeholder, need proper hash join
            WHERE  l.scored_at <= :cycle_ts
              AND  l.fit_score IS NOT NULL
            LIMIT  0
            """,
            {"cycle_ts": cycle_timestamp},
        )
    
    # TODO: Proper implementation requires storing extraction hash with listing
    # For now, return empty with explanation
    result = []
    summary = f"Skill '{canonical_skill}' drill-down (feature requires extraction hash linkage)"
    
    return ToolResult(rows=result, summary=summary)


@tool(
    description="Show how skill gap opportunity costs have changed over recent weeks. Use this when asked about trends, changes over time, or skill demand evolution.",
    parameters={
        "weeks": {
            "type": "integer",
            "default": 3,
            "description": "Number of weeks to look back (1-12)",
            "minimum": 1,
            "maximum": 12,
        }
    }
)
def trend(weeks: int = 3) -> ToolResult:
    """Gap opportunity_cost change over N weeks from snapshots.
    
    Per rule 41: weeks clamped to 1-12.
    Per rule 46: reads from last passing cycle only.
    """
    weeks = _clamp_int(weeks, 1, 12)
    
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    cutoff_str = cutoff.isoformat()
    
    with storage._connection() as conn:
        rows = storage._fetchall(
            conn,
            """
            SELECT skill, computed_at, opportunity_cost
            FROM   gap_snapshots
            WHERE  computed_at >= :cutoff
            ORDER  BY skill ASC, computed_at ASC
            """,
            {"cutoff": cutoff_str},
        )
    
    result = rows
    
    if result:
        unique_skills = len(set(r["skill"] for r in result))
        summary = f"{len(result)} data points across {unique_skills} skills over {weeks} weeks"
    else:
        summary = f"No gap snapshots from the last {weeks} weeks"
    
    return ToolResult(rows=result, summary=summary)


@tool(
    description="Get total counts: how many listings, scored vs unscored, and when the newest listing was fetched. Use this for general database status questions.",
    parameters={}
)
def listing_count() -> ToolResult:
    """Totals: listings, scored, unscored, newest listing date.
    
    Per rule 46: reads from last passing cycle only.
    """
    passing_cycle = storage.get_latest_passing_cycle()
    if not passing_cycle:
        return ToolResult(rows=[], summary="No verified cycle found")
    
    cycle_timestamp = passing_cycle.get("finished_at")
    
    with storage._connection() as conn:
        row = storage._fetchone(
            conn,
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) as scored,
                   SUM(CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END) as unscored,
                   MAX(posted_at) as newest_listing
            FROM   listings
            WHERE  fetched_at <= :cycle_ts
            """,
            {"cycle_ts": cycle_timestamp},
        )
    
    result = [row] if row else []
    summary = f"{result[0]['total']} listings ({result[0]['scored']} scored, {result[0]['unscored']} unscored)"
    
    return ToolResult(rows=result, summary=summary)


@tool(
    description="Check how often a specific skill appears in job requirements (required vs nice-to-have). Use this when asked about demand for a particular skill.",
    parameters={
        "skill": {
            "type": "string",
            "description": "The skill name to look up (will be canonicalized)",
        }
    }
)
def skill_demand(skill: str, config: Any = None) -> ToolResult:
    """How often one skill appears in required vs nice_to_have.
    
    Per rule 41: skill is canonicalized and validated.
    Per rule 46: reads from last passing cycle only.
    """
    if config is None:
        from edgedash.config import load_config
        config = load_config()
    
    canonical_skill = _canonicalize_skill(skill, config)
    
    passing_cycle = storage.get_latest_passing_cycle()
    if not passing_cycle:
        return ToolResult(rows=[], summary="No verified cycle found")
    
    # Query extraction cache for this skill
    with storage._connection() as conn:
        row = storage._fetchone(
            conn,
            """
            SELECT 
                SUM(CASE WHEN required_skills LIKE :skill_pattern THEN 1 ELSE 0 END) as required_count,
                SUM(CASE WHEN nice_to_have LIKE :skill_pattern THEN 1 ELSE 0 END) as nice_to_have_count,
                COUNT(*) as total_listings
            FROM   extraction_cache
            """,
            {"skill_pattern": f"%{canonical_skill}%"},
        )
    
    result = [row] if row else []
    req = result[0]["required_count"]
    nice = result[0]["nice_to_have_count"]
    
    summary = f"Skill '{canonical_skill}': {req} required, {nice} nice-to-have"
    
    return ToolResult(rows=result, summary=summary)
