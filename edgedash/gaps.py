"""
gaps.py — CLI viewer for the latest gap analysis snapshot.

Usage:
  python -m edgedash.gaps           Show latest snapshot
  python -m edgedash.gaps --trend   Show trend over time

Displays a readable table with rank, skill, listings blocked, opportunity
cost, mean score, and a visual bar chart.

Trend mode compares earliest and latest snapshots to show skill gap evolution.
"""
from __future__ import annotations

import sys

from edgedash.config import load_config
from edgedash.storage import init_db, get_latest_gap_snapshot


def main() -> None:
    """Entry point for gaps CLI."""
    if "--trend" in sys.argv:
        show_trend()
    else:
        show_latest()


def show_latest() -> None:
    """Display the latest gap analysis snapshot as a terminal table."""
    config = load_config()
    init_db(config.db_path)

    gaps = get_latest_gap_snapshot()

    if not gaps:
        print("No gap analysis snapshots found.")
        print("Run a cycle first: python run_cycle.py")
        return

    computed_at = gaps[0]["computed_at"] if gaps else "unknown"
    
    print("=" * 90)
    print(f"SKILL GAP ANALYSIS — {computed_at}")
    print("=" * 90)
    print()
    print(f"{'#':<4} {'Skill':<25} {'Blocked':<8} {'Cost':<7} {'Mean':<6} {'Top':<5} Bar")
    print("-" * 90)

    for rank, gap in enumerate(gaps[:20], start=1):  # Top 20
        skill = gap["skill"]
        blocked = gap["listings_blocked"]
        cost = gap["opportunity_cost"]
        mean = gap["mean_score"]
        top = gap["top_score"]

        # Visual bar (max 20 chars, scaled to max cost in top 20)
        max_cost = max(g["opportunity_cost"] for g in gaps[:20])
        bar_len = int((cost / max_cost) * 20) if max_cost > 0 else 0
        bar = "█" * bar_len

        # Low confidence marker (rule 27)
        confidence = "" if blocked >= 3 else " ⚠"

        print(
            f"{rank:<4} {skill:<25} {blocked:<8} {cost:<7.1f} {mean:<6.1f} {top:<5} {bar}{confidence}"
        )

    print()
    print("Legend:")
    print("  Blocked = number of listings requiring this skill")
    print("  Cost = opportunity cost (weighted by fit score)")
    print("  Mean = average fit score of blocked listings")
    print("  Top = highest fit score among blocked listings")
    print("  ⚠ = low confidence (fewer than 3 listings)")
    print()


def show_trend() -> None:
    """Display trend comparison between earliest and latest snapshots."""
    config = load_config()
    init_db(config.db_path)

    # Get earliest and latest snapshots
    snapshots = _get_all_snapshots()

    if not snapshots:
        print("No gap analysis snapshots found.")
        print("Run a cycle first: python run_cycle.py")
        return

    if len(snapshots) < 2:
        earliest_date = snapshots[0]["computed_at"][:10]  # YYYY-MM-DD
        print("=" * 80)
        print("SKILL GAP TREND ANALYSIS")
        print("=" * 80)
        print()
        print("Only one snapshot exists so far:")
        print(f"  Date: {earliest_date}")
        print()
        print("At least 2 snapshots are needed to show a trend.")
        print("Run the cycle on different days to track skill gap evolution over time.")
        print()
        return

    earliest = snapshots[0]
    latest = snapshots[-1]

    earliest_date = earliest["computed_at"][:10]
    latest_date = latest["computed_at"][:10]

    # Build skill -> cost mapping for both snapshots
    earliest_skills = {g["skill"]: g for g in earliest["gaps"]}
    latest_skills = {g["skill"]: g for g in latest["gaps"]}

    # Get top 10 from latest
    latest_top_10 = latest["gaps"][:10]

    print("=" * 90)
    print(f"SKILL GAP TREND ANALYSIS — {earliest_date} to {latest_date}")
    print("=" * 90)
    print()
    print(f"{'#':<4} {'Skill':<25} {'Was':<7} {'Now':<7} {'Change':<10} {'%':<8} Status")
    print("-" * 90)

    for rank, gap in enumerate(latest_top_10, start=1):
        skill = gap["skill"]
        now_cost = gap["opportunity_cost"]

        if skill in earliest_skills:
            was_cost = earliest_skills[skill]["opportunity_cost"]
            delta = now_cost - was_cost
            pct = (delta / was_cost * 100) if was_cost > 0 else 0
            status = ""
        else:
            was_cost = 0.0
            delta = now_cost
            pct = 0.0
            status = "NEW"

        # Format change
        delta_str = f"{delta:+.1f}" if delta != 0 else "—"
        pct_str = f"{pct:+.0f}%" if delta != 0 else ""

        print(
            f"{rank:<4} {skill:<25} {was_cost:<7.1f} {now_cost:<7.1f} "
            f"{delta_str:<10} {pct_str:<8} {status}"
        )

    # Find skills that dropped out
    earliest_top_10 = earliest["gaps"][:10]
    earliest_top_10_skills = {g["skill"] for g in earliest_top_10}
    latest_top_10_skills = {g["skill"] for g in latest_top_10}

    dropped_out = earliest_top_10_skills - latest_top_10_skills

    if dropped_out:
        print()
        print("Dropped out of top 10:")
        for skill in sorted(dropped_out):
            was_cost = earliest_skills[skill]["opportunity_cost"]
            now_cost = latest_skills.get(skill, {}).get("opportunity_cost", 0.0)
            print(f"  - {skill} (was {was_cost:.1f}, now {now_cost:.1f})")

    print()
    print(f"Snapshot window: {earliest_date} to {latest_date}")
    print(f"Total snapshots: {len(snapshots)}")
    print()


def _get_all_snapshots() -> list[dict]:
    """Get all snapshots ordered by computed_at."""
    import sqlite3
    import json

    config = load_config()
    conn = sqlite3.connect(config.db_path)
    conn.row_factory = sqlite3.Row

    # Get all unique run_ids ordered by time
    run_ids = conn.execute(
        """
        SELECT DISTINCT run_id, computed_at
        FROM gap_snapshots
        ORDER BY computed_at ASC
        """
    ).fetchall()

    snapshots = []
    for row in run_ids:
        run_id = row["run_id"]
        computed_at = row["computed_at"]

        # Get all gaps for this run
        gaps_rows = conn.execute(
            """
            SELECT skill, listings_blocked, opportunity_cost, mean_score,
                   top_score, example_ids, also_nice_to_have
            FROM gap_snapshots
            WHERE run_id = :run_id
            ORDER BY opportunity_cost DESC
            """,
            {"run_id": run_id},
        ).fetchall()

        gaps = [
            {
                "skill": r["skill"],
                "listings_blocked": r["listings_blocked"],
                "opportunity_cost": r["opportunity_cost"],
                "mean_score": r["mean_score"],
                "top_score": r["top_score"],
                "example_ids": json.loads(r["example_ids"]),
                "also_nice_to_have": r["also_nice_to_have"],
            }
            for r in gaps_rows
        ]

        snapshots.append({
            "run_id": run_id,
            "computed_at": computed_at,
            "gaps": gaps,
        })

    conn.close()
    return snapshots


if __name__ == "__main__":
    main()
