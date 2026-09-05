"""
scorer.py — Scorer agent: extract facts, score deterministically, write results.

Per steering rule 21: batch size is capped at config.llm_batch_size (default 25).
Per steering rule 17: one listing failure is logged and skipped; the rest continue.
Per steering rule 20: log score distribution; flag runs where spread < 10 as suspect.

Flow:
  1. Select unscored listings (WHERE fit_score IS NULL), limit by batch size.
  2. For each listing:
     a. Extract facts via extractor.extract (may hit cache, may call LLM).
     b. Score via scoring.score_listing (pure function, no model call).
     c. Write score + reason + components via storage.update_score.
  3. After the batch, compute distribution (min, max, mean, spread).
  4. Return AgentResult with summary.
"""
from __future__ import annotations

import traceback
from typing import Any

from edgedash.agents.base import AgentResult
from edgedash.agents.extractor import extract
from edgedash.llm import LLMError
from edgedash.scoring import score_listing


class Scorer:
    name: str = "scorer"

    def run(self, config: Any, storage_mod: Any, stop_conditions: dict[str, Any] | None = None) -> AgentResult:
        """Score unscored listings up to the configured batch size.
        
        Args:
            config: Configuration object
            storage_mod: Storage module
            stop_conditions: Optional limits from orchestrator (max_items, max_seconds)
        """
        from edgedash.storage import (
            get_unscored_listings,
            get_scored_listings,
            update_score,
        )

        # Respect stop_conditions if provided (rule 29)
        if stop_conditions:
            batch_size = stop_conditions.get("max_items", config.llm_batch_size)
        else:
            batch_size = config.llm_batch_size

        # Verifier retry: re-score existing rows with contrast stretch so
        # the distribution the verifier reads actually changes (rule 36).
        widen_spread = bool(stop_conditions and stop_conditions.get("widen_spread"))
        if widen_spread:
            listings = get_scored_listings(limit=None)
        else:
            listings = get_unscored_listings(limit=batch_size)

        if not listings:
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="no unscored listings",
            )

        scores: list[int] = []
        failed_count = 0

        for listing in listings:
            try:
                facts = extract(listing)
                result = score_listing(
                    listing, facts, config, widen_spread=widen_spread,
                )
                
                update_score(
                    listing_id=listing["id"],
                    score=result["score"],
                    reason=result["reason"],
                    components=result["components"],
                )
                
                scores.append(result["score"])

            except LLMError as exc:
                failed_count += 1
                print(f"  ⚠ [scorer] listing {listing['id'][:8]} extraction failed: {exc}")
                continue

            except Exception as exc:
                failed_count += 1
                print(f"  ⚠ [scorer] listing {listing['id'][:8]} scoring failed: {exc}")
                traceback.print_exc()
                continue

        # Compute distribution
        if scores:
            min_score = min(scores)
            max_score = max(scores)
            mean_score = int(sum(scores) / len(scores))
            spread = max_score - min_score
        else:
            min_score = max_score = mean_score = spread = 0

        # Flag suspect runs (steering rule 20)
        status = "ok"
        if scores and spread < 10:
            status = "suspect"
            print(f"  ⚠ [scorer] suspect run: all scores within {spread} points")

        notes = (
            f"scored {len(scores)} · range {min_score}-{max_score} · "
            f"mean {mean_score} · {failed_count} failed · "
            f"spread {'OK' if spread >= 10 or not scores else 'SUSPECT'}"
        )
        if widen_spread:
            notes += " · widen_spread"

        return AgentResult(
            agent=self.name,
            status=status,
            records_touched=len(scores),
            notes=notes,
        )


# ---------------------------------------------------------------------------
# CLI for manual testing
# ---------------------------------------------------------------------------

def _main() -> None:
    """CLI: python -m edgedash.agents.scorer --limit N"""
    import sys
    from edgedash.config import load_config
    import edgedash.storage as storage

    config = load_config()
    storage.init_db(config.db_path)

    # Parse --limit flag
    limit = config.llm_batch_size
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    # Override batch size for CLI
    config.llm_batch_size = limit

    scorer = Scorer()
    result = scorer.run(config, storage)

    print(f"\n[OK] {result.agent}: {result.notes}")
    print(f"  Status: {result.status}")
    print(f"  Records touched: {result.records_touched}")


if __name__ == "__main__":
    _main()
