"""
rescore.py — Manual re-scoring escape hatch (steering rule 18).

Usage:
  python -m edgedash.rescore --all       Clear all scores (with confirmation)
  python -m edgedash.rescore --id <id>   Clear one listing's score

Clears fit_score, fit_reason, scored_at but NEVER the extraction cache.
Re-scoring costs zero API calls because the facts are already cached.
"""
from __future__ import annotations

import sys

from edgedash.config import load_config
from edgedash.storage import (
    init_db,
    clear_score,
    clear_all_scores,
    count_scored,
)


def main() -> None:
    """CLI entry point for manual re-scoring."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m edgedash.rescore --all")
        print("  python -m edgedash.rescore --id <listing_id>")
        sys.exit(1)

    config = load_config()
    init_db(config.db_path)

    if "--all" in sys.argv:
        _rescore_all()
    elif "--id" in sys.argv:
        idx = sys.argv.index("--id")
        if idx + 1 >= len(sys.argv):
            print("Error: --id requires a listing ID argument")
            sys.exit(1)
        listing_id = sys.argv[idx + 1]
        _rescore_one(listing_id)
    else:
        print("Error: use --all or --id <listing_id>")
        sys.exit(1)


def _rescore_all() -> None:
    """Clear all scores with confirmation prompt."""
    scored_count = count_scored()
    
    if scored_count == 0:
        print("No scored listings to clear.")
        return

    print(f"This will clear {scored_count} scored listing(s).")
    print("The extraction cache will be preserved (zero API cost to re-score).")
    
    try:
        confirm = input("Type 'yes' to confirm: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)

    if confirm != "yes":
        print("Aborted.")
        sys.exit(0)

    cleared = clear_all_scores()
    print(f"✓ Cleared {cleared} score(s).")
    print(f"  Run 'python run_cycle.py' to re-score them.")


def _rescore_one(listing_id: str) -> None:
    """Clear the score for a single listing."""
    success = clear_score(listing_id)
    
    if success:
        print(f"✓ Cleared score for listing {listing_id[:16]}...")
        print(f"  Run 'python run_cycle.py' or 'python -m edgedash.agents.scorer' to re-score it.")
    else:
        print(f"✗ Listing {listing_id[:16]}... not found or already unscored.")
        sys.exit(1)


if __name__ == "__main__":
    main()
