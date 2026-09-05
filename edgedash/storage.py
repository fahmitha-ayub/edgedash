"""
storage.py — the ONLY module allowed to import database drivers.

All other modules interact with the database exclusively through the functions
defined here. Supports both SQLite (local dev) and Postgres (production) with
automatic fallback. Per rule 47, DATABASE_URL from environment is required for
hosted deployment.

Backend selection (rule 47):
- If DATABASE_URL is set → Postgres
- Otherwise → SQLite at db_path

Use `python -m edgedash.storage --migrate` to initialize tables.
Use `python -m edgedash.storage --check` to verify connection and row counts.
"""
from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


# Load .env file if it exists
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with _env_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


# ---------------------------------------------------------------------------
# Backend detection and connection
# ---------------------------------------------------------------------------

_db_url: str = ""
_db_path: str = ""
_backend: str = ""  # "postgres" or "sqlite"


def _detect_backend() -> str:
    """Detect which backend to use based on environment."""
    if os.environ.get("DATABASE_URL"):
        return "postgres"
    return "sqlite"


def configure(path: str) -> None:
    """Set the database path for SQLite or use DATABASE_URL for Postgres.
    
    Call this once at startup. Logs which backend is active.
    """
    global _db_path, _db_url, _backend
    
    _db_path = path
    _db_url = os.environ.get("DATABASE_URL", "")
    _backend = _detect_backend()
    
    if _backend == "postgres":
        print(f"[storage] Using Postgres: {_db_url.split('@')[-1] if '@' in _db_url else 'configured'}")
    else:
        print(f"[storage] Using SQLite: {_db_path}")


@contextmanager
def _connection() -> Generator[Any, None, None]:
    """Return a database connection (SQLite or Postgres based on config)."""
    if not _db_path and not _db_url:
        raise RuntimeError("storage.configure(path) must be called before using storage.")
    
    if _backend == "postgres":
        import psycopg2
        import psycopg2.extras
        
        conn = psycopg2.connect(_db_url)
        conn.set_session(autocommit=False)
        
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        import sqlite3
        
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _fetchone(conn: Any, query: str, params: dict | tuple = None) -> dict[str, Any] | None:
    """Execute query and return one row as dict, handling both backends."""
    if _backend == "postgres":
        import psycopg2.extras
        
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Convert :name style to %s style for postgres
            pg_query = query.replace("?", "%s")
            for key in sorted((params or {}).keys(), key=len, reverse=True):
                pg_query = pg_query.replace(f":{key}", "%s")
            
            if isinstance(params, dict):
                cur.execute(pg_query, list(params.values()))
            else:
                cur.execute(pg_query, params or ())
            
            row = cur.fetchone()
            return dict(row) if row else None
    else:
        cur = conn.execute(query, params or ())
        row = cur.fetchone()
        return dict(row) if row else None


def _fetchall(conn: Any, query: str, params: dict | tuple = None) -> list[dict[str, Any]]:
    """Execute query and return all rows as list of dicts, handling both backends."""
    if _backend == "postgres":
        import psycopg2.extras
        
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Convert :name style to %s style for postgres
            pg_query = query.replace("?", "%s")
            for key in sorted((params or {}).keys(), key=len, reverse=True):
                pg_query = pg_query.replace(f":{key}", "%s")
            
            if isinstance(params, dict):
                cur.execute(pg_query, list(params.values()))
            else:
                cur.execute(pg_query, params or ())
            
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    else:
        cur = conn.execute(query, params or ())
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def _execute(conn: Any, query: str, params: dict | tuple = None) -> int:
    """Execute query and return rowcount, handling both backends."""
    if _backend == "postgres":
        with conn.cursor() as cur:
            # Convert :name style to %s style for postgres
            pg_query = query.replace("?", "%s")
            for key in sorted((params or {}).keys(), key=len, reverse=True):
                pg_query = pg_query.replace(f":{key}", "%s")
            
            if isinstance(params, dict):
                cur.execute(pg_query, list(params.values()))
            else:
                cur.execute(pg_query, params or ())
            
            return cur.rowcount
    else:
        cur = conn.execute(query, params or ())
        return cur.rowcount


def _executemany(conn: Any, query: str, params_list: list[dict]) -> None:
    """Execute query with multiple parameter sets, handling both backends."""
    if _backend == "postgres":
        with conn.cursor() as cur:
            # Convert :name style to %s style for postgres
            pg_query = query
            if params_list:
                keys = list(params_list[0].keys())
                for key in sorted(keys, key=len, reverse=True):
                    pg_query = pg_query.replace(f":{key}", "%s")
                
                values_list = [list(p.values()) for p in params_list]
                for values in values_list:
                    cur.execute(pg_query, values)
    else:
        conn.executemany(query, params_list)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def init_db(path: str) -> None:
    """Create all tables if they do not already exist, then configure the module."""
    configure(path)
    
    if _backend == "postgres":
        _create_postgres_schema()
    else:
        _create_sqlite_schema()


def _create_sqlite_schema() -> None:
    """Create SQLite schema."""
    with _connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                company     TEXT NOT NULL,
                location    TEXT NOT NULL,
                url         TEXT NOT NULL,
                description TEXT NOT NULL,
                source      TEXT NOT NULL,
                posted_at   TEXT,
                fetched_at  TEXT NOT NULL,
                fit_score   INTEGER,
                fit_reason  TEXT,
                scored_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS extraction_cache (
                description_hash TEXT PRIMARY KEY,
                required_skills  TEXT NOT NULL,
                nice_to_have     TEXT NOT NULL,
                seniority        TEXT NOT NULL,
                years_required   INTEGER,
                remote_ok        INTEGER,
                extracted_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skill_gaps (
                skill       TEXT PRIMARY KEY,
                frequency   INTEGER NOT NULL DEFAULT 1,
                last_seen   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gap_snapshots (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id              TEXT NOT NULL,
                computed_at         TEXT NOT NULL,
                skill               TEXT NOT NULL,
                listings_blocked    INTEGER NOT NULL,
                opportunity_cost    REAL NOT NULL,
                mean_score          REAL NOT NULL,
                top_score           INTEGER NOT NULL,
                example_ids         TEXT NOT NULL,
                also_nice_to_have   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS cycle_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent           TEXT NOT NULL,
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                records_touched INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL,
                notes           TEXT,
                verdict         TEXT,
                failed_checks   TEXT,
                retry_count     INTEGER NOT NULL DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS query_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                asked_at    TEXT NOT NULL,
                question    TEXT NOT NULL,
                tool        TEXT,
                params      TEXT,
                answerable  INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                error       TEXT
            );
        """)


def _create_postgres_schema() -> None:
    """Create Postgres schema."""
    with _connection() as conn:
        # Postgres uses SERIAL instead of AUTOINCREMENT
        if _backend == "postgres":
            import psycopg2
            
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS listings (
                        id          TEXT PRIMARY KEY,
                        title       TEXT NOT NULL,
                        company     TEXT NOT NULL,
                        location    TEXT NOT NULL,
                        url         TEXT NOT NULL,
                        description TEXT NOT NULL,
                        source      TEXT NOT NULL,
                        posted_at   TIMESTAMP,
                        fetched_at  TIMESTAMP NOT NULL,
                        fit_score   INTEGER,
                        fit_reason  TEXT,
                        scored_at   TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS extraction_cache (
                        description_hash TEXT PRIMARY KEY,
                        required_skills  TEXT NOT NULL,
                        nice_to_have     TEXT NOT NULL,
                        seniority        TEXT NOT NULL,
                        years_required   INTEGER,
                        remote_ok        BOOLEAN,
                        extracted_at     TIMESTAMP NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS skill_gaps (
                        skill       TEXT PRIMARY KEY,
                        frequency   INTEGER NOT NULL DEFAULT 1,
                        last_seen   TIMESTAMP NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS gap_snapshots (
                        id                  SERIAL PRIMARY KEY,
                        run_id              TEXT NOT NULL,
                        computed_at         TIMESTAMP NOT NULL,
                        skill               TEXT NOT NULL,
                        listings_blocked    INTEGER NOT NULL,
                        opportunity_cost    REAL NOT NULL,
                        mean_score          REAL NOT NULL,
                        top_score           INTEGER NOT NULL,
                        example_ids         TEXT NOT NULL,
                        also_nice_to_have   INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS cycle_log (
                        id              SERIAL PRIMARY KEY,
                        agent           TEXT NOT NULL,
                        started_at      TIMESTAMP NOT NULL,
                        finished_at     TIMESTAMP,
                        records_touched INTEGER NOT NULL DEFAULT 0,
                        status          TEXT NOT NULL,
                        notes           TEXT,
                        verdict         TEXT,
                        failed_checks   TEXT,
                        retry_count     INTEGER NOT NULL DEFAULT 0
                    );
                    
                    CREATE TABLE IF NOT EXISTS query_log (
                        id          SERIAL PRIMARY KEY,
                        asked_at    TIMESTAMP NOT NULL,
                        question    TEXT NOT NULL,
                        tool        TEXT,
                        params      TEXT,
                        answerable  BOOLEAN NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        error       TEXT
                    );
                """)


# ---------------------------------------------------------------------------
# Stable listing ID
# ---------------------------------------------------------------------------

def make_listing_id(source: str, url: str) -> str:
    """Return a stable SHA-256 hex digest for (source, url).

    Using a hash instead of an auto-increment means the same job posting
    always gets the same id regardless of insertion order or re-fetch.
    """
    payload = f"{source}::{url}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

def upsert_listings(rows: list[dict[str, Any]]) -> int:
    """Insert new listings, ignoring duplicates. Returns count of new rows only.

    Each row dict must contain: title, company, location, url, description,
    source, posted_at (nullable), fetched_at.
    The 'id' field is computed here from source + url if not already present.
    """
    if not rows:
        return 0

    # Dialect-specific upsert
    if _backend == "postgres":
        sql = """
            INSERT INTO listings
                (id, title, company, location, url, description,
                 source, posted_at, fetched_at, fit_score, fit_reason)
            VALUES
                (:id, :title, :company, :location, :url, :description,
                 :source, :posted_at, :fetched_at, :fit_score, :fit_reason)
            ON CONFLICT (id) DO NOTHING
        """
    else:
        sql = """
            INSERT OR IGNORE INTO listings
                (id, title, company, location, url, description,
                 source, posted_at, fetched_at, fit_score, fit_reason)
            VALUES
                (:id, :title, :company, :location, :url, :description,
                 :source, :posted_at, :fetched_at, :fit_score, :fit_reason)
        """

    prepared: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        r.setdefault("id", make_listing_id(r["source"], r["url"]))
        r.setdefault("fit_score", None)
        r.setdefault("fit_reason", None)
        r.setdefault("posted_at", None)
        prepared.append(r)

    with _connection() as conn:
        before_row = _fetchone(conn, "SELECT COUNT(*) as count FROM listings")
        before = before_row["count"] if before_row else 0
        _executemany(conn, sql, prepared)
        after_row = _fetchone(conn, "SELECT COUNT(*) as count FROM listings")
        after = after_row["count"] if after_row else 0

    return after - before


def count_unscored() -> int:
    """Return the number of listings that have not yet been scored."""
    with _connection() as conn:
        row = _fetchone(conn, "SELECT COUNT(*) as count FROM listings WHERE fit_score IS NULL")
    return row["count"] if row else 0


def last_fetch_time() -> str | None:
    """Return the most recent fetched_at timestamp, or None if no listings exist."""
    with _connection() as conn:
        row = _fetchone(conn, "SELECT MAX(fetched_at) as max_time FROM listings")
    
    if not row or not row["max_time"]:
        return None
    
    # Ensure it's always a string (Postgres might return datetime object)
    max_time = row["max_time"]
    if isinstance(max_time, str):
        return max_time
    else:
        # Convert datetime object to ISO string
        return max_time.isoformat() if hasattr(max_time, 'isoformat') else str(max_time)


def get_listings(limit: int = 100, min_score: int = 0) -> list[dict[str, Any]]:
    """Return listings with fit_score >= min_score, newest first, up to limit rows."""
    with _connection() as conn:
        return _fetchall(
            conn,
            """
            SELECT id, title, company, location, url, description,
                   source, posted_at, fetched_at, fit_score, fit_reason
            FROM   listings
            WHERE  fit_score >= :min_score
            ORDER  BY fetched_at DESC
            LIMIT  :limit
            """,
            {"min_score": min_score, "limit": limit},
        )


# ---------------------------------------------------------------------------
# Cycle log
# ---------------------------------------------------------------------------

def log_cycle(
    agent: str,
    started_at: str,
    finished_at: str,
    records_touched: int,
    status: str,
    notes: str | None = None,
    verdict: str | None = None,
    failed_checks: str | None = None,
    retry_count: int = 0,
) -> None:
    """Write one row to cycle_log. status should be 'pass' or 'fail'."""
    with _connection() as conn:
        _execute(
            conn,
            """
            INSERT INTO cycle_log
                (agent, started_at, finished_at, records_touched, status,
                 notes, verdict, failed_checks, retry_count)
            VALUES
                (:agent, :started_at, :finished_at, :records_touched, :status,
                 :notes, :verdict, :failed_checks, :retry_count)
            """,
            {
                "agent": agent,
                "started_at": started_at,
                "finished_at": finished_at,
                "records_touched": records_touched,
                "status": status,
                "notes": notes,
                "verdict": verdict,
                "failed_checks": failed_checks,
                "retry_count": retry_count,
            },
        )


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Extraction cache
# ---------------------------------------------------------------------------

def get_cached_extraction(description_hash: str) -> dict[str, Any] | None:
    """Return cached extraction facts for a description hash, or None if not cached."""
    with _connection() as conn:
        row = _fetchone(
            conn,
            """
            SELECT required_skills, nice_to_have, seniority, years_required, remote_ok
            FROM   extraction_cache
            WHERE  description_hash = :hash
            """,
            {"hash": description_hash},
        )
    
    if not row:
        return None
    
    import json
    return {
        "required_skills": json.loads(row["required_skills"]),
        "nice_to_have": json.loads(row["nice_to_have"]),
        "seniority": row["seniority"],
        "years_required": row["years_required"],
        "remote_ok": None if row["remote_ok"] is None else bool(row["remote_ok"]),
    }


def cache_extraction(description_hash: str, facts: dict[str, Any]) -> None:
    """Store extraction facts in the cache keyed by description hash."""
    import json
    
    # Handle dialect-specific upsert
    if _backend == "postgres":
        sql = """
            INSERT INTO extraction_cache
                (description_hash, required_skills, nice_to_have, seniority,
                 years_required, remote_ok, extracted_at)
            VALUES
                (:hash, :required_skills, :nice_to_have, :seniority,
                 :years_required, :remote_ok, :extracted_at)
            ON CONFLICT (description_hash) DO UPDATE SET
                required_skills = EXCLUDED.required_skills,
                nice_to_have = EXCLUDED.nice_to_have,
                seniority = EXCLUDED.seniority,
                years_required = EXCLUDED.years_required,
                remote_ok = EXCLUDED.remote_ok,
                extracted_at = EXCLUDED.extracted_at
        """
    else:
        sql = """
            INSERT OR REPLACE INTO extraction_cache
                (description_hash, required_skills, nice_to_have, seniority,
                 years_required, remote_ok, extracted_at)
            VALUES
                (:hash, :required_skills, :nice_to_have, :seniority,
                 :years_required, :remote_ok, :extracted_at)
        """
    
    with _connection() as conn:
        _execute(
            conn,
            sql,
            {
                "hash": description_hash,
                "required_skills": json.dumps(facts["required_skills"]),
                "nice_to_have": json.dumps(facts["nice_to_have"]),
                "seniority": facts["seniority"],
                "years_required": facts.get("years_required"),
                "remote_ok": facts.get("remote_ok"),
                "extracted_at": utc_now(),
            },
        )


def get_unscored_listings(limit: int) -> list[dict[str, Any]]:
    """Return up to `limit` listings that have not been scored yet."""
    with _connection() as conn:
        return _fetchall(
            conn,
            """
            SELECT id, title, company, location, url, description,
                   source, posted_at, fetched_at
            FROM   listings
            WHERE  fit_score IS NULL
            ORDER  BY fetched_at DESC
            LIMIT  :limit
            """,
            {"limit": limit},
        )


def update_score(listing_id: str, score: int, reason: str, components: dict) -> None:
    """Update a listing's fit_score, fit_reason, and scored_at timestamp."""
    import json
    
    # Store components as JSON in fit_reason for now (can add separate column later)
    reason_with_components = reason + " | " + json.dumps(components)
    
    with _connection() as conn:
        _execute(
            conn,
            """
            UPDATE listings
            SET    fit_score = :score,
                   fit_reason = :reason,
                   scored_at = :scored_at
            WHERE  id = :id
            """,
            {
                "id": listing_id,
                "score": score,
                "reason": reason_with_components,
                "scored_at": utc_now(),
            },
        )


# ---------------------------------------------------------------------------
# Re-scoring support
# ---------------------------------------------------------------------------

def clear_score(listing_id: str) -> bool:
    """Clear the score for a single listing. Returns True if a row was updated."""
    with _connection() as conn:
        rowcount = _execute(
            conn,
            """
            UPDATE listings
            SET    fit_score = NULL,
                   fit_reason = NULL,
                   scored_at = NULL
            WHERE  id = :id
            """,
            {"id": listing_id},
        )
    return rowcount > 0


def clear_all_scores() -> int:
    """Clear all scores. Returns the number of listings affected."""
    with _connection() as conn:
        return _execute(
            conn,
            """
            UPDATE listings
            SET    fit_score = NULL,
                   fit_reason = NULL,
                   scored_at = NULL
            WHERE  fit_score IS NOT NULL
            """
        )


def count_scored() -> int:
    """Return the number of listings that have been scored."""
    with _connection() as conn:
        row = _fetchone(conn, "SELECT COUNT(*) as count FROM listings WHERE fit_score IS NOT NULL")
    return row["count"] if row else 0


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def get_scored_listings_with_facts() -> list[dict[str, Any]]:
    """Return all scored listings with their extracted facts.
    
    Joins listings with extraction_cache on description hash.
    Returns only listings that have been scored.
    """
    import json
    import hashlib
    
    with _connection() as conn:
        rows = _fetchall(
            conn,
            """
            SELECT 
                l.id,
                l.title,
                l.company,
                l.description,
                l.fit_score
            FROM listings l
            WHERE l.fit_score IS NOT NULL
            ORDER BY l.fit_score DESC
            """
        )
    
    result = []
    for row in rows:
        # Compute description hash
        desc_hash = hashlib.sha256(row["description"].encode("utf-8")).hexdigest()
        
        # Get cached extraction
        cached = get_cached_extraction(desc_hash)
        
        if cached:
            result.append({
                "id": row["id"],
                "title": row["title"],
                "company": row["company"],
                "fit_score": row["fit_score"],
                "required_skills": cached["required_skills"],
                "nice_to_have": cached["nice_to_have"],
            })
    
    return result


def write_gap_snapshot(run_id: str, gaps: list[dict[str, Any]]) -> None:
    """Write a timestamped gap analysis snapshot (steering rule 25)."""
    import json
    
    computed_at = utc_now()
    
    with _connection() as conn:
        for gap in gaps:
            _execute(
                conn,
                """
                INSERT INTO gap_snapshots
                    (run_id, computed_at, skill, listings_blocked,
                     opportunity_cost, mean_score, top_score,
                     example_ids, also_nice_to_have)
                VALUES
                    (:run_id, :computed_at, :skill, :listings_blocked,
                     :opportunity_cost, :mean_score, :top_score,
                     :example_ids, :also_nice_to_have)
                """,
                {
                    "run_id": run_id,
                    "computed_at": computed_at,
                    "skill": gap["skill"],
                    "listings_blocked": gap["listings_blocked"],
                    "opportunity_cost": gap["opportunity_cost"],
                    "mean_score": gap["mean_score"],
                    "top_score": gap["top_score"],
                    "example_ids": json.dumps(gap["example_ids"]),
                    "also_nice_to_have": gap.get("also_nice_to_have", 0),
                },
            )


def get_latest_gap_snapshot() -> list[dict[str, Any]]:
    """Return the most recent gap analysis snapshot."""
    import json
    
    with _connection() as conn:
        # Get the latest run_id
        latest_run = _fetchone(
            conn,
            "SELECT run_id FROM gap_snapshots ORDER BY computed_at DESC LIMIT 1"
        )
        
        if not latest_run:
            return []
        
        run_id = latest_run["run_id"]
        
        # Get all gaps from that run
        rows = _fetchall(
            conn,
            """
            SELECT skill, listings_blocked, opportunity_cost, mean_score,
                   top_score, example_ids, also_nice_to_have, computed_at
            FROM gap_snapshots
            WHERE run_id = :run_id
            ORDER BY opportunity_cost DESC
            """,
            {"run_id": run_id},
        )
    
    return [
        {
            "skill": r["skill"],
            "listings_blocked": r["listings_blocked"],
            "opportunity_cost": r["opportunity_cost"],
            "mean_score": r["mean_score"],
            "top_score": r["top_score"],
            "example_ids": json.loads(r["example_ids"]),
            "also_nice_to_have": r["also_nice_to_have"],
            "computed_at": r["computed_at"],
        }
        for r in rows
    ]


def get_scored_listings(limit: int | None = None) -> list[dict[str, Any]]:
    """Return scored listings with fields needed to re-score (widen_spread retry)."""
    sql = """
        SELECT id, title, company, location, url, description,
               source, posted_at, fetched_at, fit_score, fit_reason
        FROM   listings
        WHERE  fit_score IS NOT NULL
        ORDER  BY scored_at DESC
    """
    params: dict[str, Any] = {}
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = limit

    with _connection() as conn:
        return _fetchall(conn, sql, params)


def get_latest_passing_cycle() -> dict[str, Any] | None:
    """Return the most recent orchestrator cycle with a passing verdict (rule 38).

    The dashboard must read only this row's era of data: stale verified
    results beat a newer failed or degraded cycle.
    """
    with _connection() as conn:
        return _fetchone(
            conn,
            """
            SELECT id, agent, started_at, finished_at, records_touched,
                   status, notes, verdict, failed_checks, retry_count
            FROM   cycle_log
            WHERE  agent = 'orchestrator' AND verdict = 'pass'
            ORDER  BY finished_at DESC
            LIMIT  1
            """
        )


def get_recent_cycles(limit: int = 30) -> list[dict[str, Any]]:
    """Return the most recent orchestrator cycles, most recent first.

    Used by the activity dashboard to show all cycles including failed/degraded.
    """
    with _connection() as conn:
        return _fetchall(
            conn,
            """
            SELECT id, agent, started_at, finished_at, records_touched,
                   status, notes, verdict, failed_checks, retry_count
            FROM   cycle_log
            WHERE  agent = 'orchestrator'
            ORDER  BY started_at DESC
            LIMIT  :limit
            """,
            {"limit": limit},
        )



# ---------------------------------------------------------------------------
# CLI commands (per deployment rules)
# ---------------------------------------------------------------------------

def _cli_migrate() -> None:
    """Create all tables on an empty database. Safe to run repeatedly."""
    print("Running migrations...")
    
    # Configure based on DATABASE_URL or default to SQLite
    if os.environ.get("DATABASE_URL"):
        # Postgres mode - configure will detect DATABASE_URL
        configure("unused_path_for_postgres")
    else:
        # SQLite mode
        db_path = "edgedash.db"
        configure(db_path)
    
    # Now run the appropriate schema creation
    if _backend == "postgres":
        _create_postgres_schema()
    else:
        _create_sqlite_schema()
    
    print(f"✓ Migrations complete ({_backend} backend)")


def _cli_check() -> None:
    """Print backend status, connection test, and row counts."""
    # Configure storage
    db_path = os.environ.get("DATABASE_URL", "edgedash.db")
    configure(db_path)
    
    print(f"Backend: {_backend}")
    if _backend == "postgres":
        print(f"Database URL: {_db_url.split('@')[-1] if '@' in _db_url else 'configured'}")
    else:
        print(f"Database path: {_db_path}")
    
    # Test connection
    try:
        with _connection() as conn:
            print("✓ Connection successful")
            
            # Get row counts for each table
            tables = ["listings", "extraction_cache", "gap_snapshots", "cycle_log", "query_log"]
            print("\nRow counts:")
            for table in tables:
                try:
                    row = _fetchone(conn, f"SELECT COUNT(*) as count FROM {table}")
                    count = row["count"] if row else 0
                    print(f"  {table}: {count}")
                except Exception as e:
                    print(f"  {table}: ERROR ({e})")
    
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if "--migrate" in sys.argv:
        _cli_migrate()
    elif "--check" in sys.argv:
        _cli_check()
    else:
        print("Usage:")
        print("  python -m edgedash.storage --migrate  # Create tables")
        print("  python -m edgedash.storage --check    # Check connection and counts")
