"""
verifier.py — Verifier agent: judges output plausibility, never repairs (rule 34).

Reads current scores, extracted facts, gap snapshot, and latest fetch time,
runs run_all_checks, and returns an AgentResult carrying the Verdict.
The only write is the verdict row in cycle_log (rule 37).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from edgedash.agents.base import AgentResult
from edgedash.verification import Verdict, run_all_checks


class Verifier:
    name: str = "verifier"

    def run(
        self,
        config: Any,
        storage_mod: Any,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        now = datetime.now(timezone.utc)

        scored = storage_mod.get_scored_listings_with_facts()
        scores = [row["fit_score"] for row in scored]
        facts_list = [
            {"required_skills": row.get("required_skills") or []}
            for row in scored
        ]
        gaps = storage_mod.get_latest_gap_snapshot()
        latest_fetch_at = storage_mod.last_fetch_time()

        verdict = run_all_checks(
            scores, facts_list, gaps, latest_fetch_at, config, now,
        )
        notes = _verdict_notes(verdict)
        status = "ok" if verdict.passed else "failed"

        storage_mod.log_cycle(
            agent=self.name,
            started_at=storage_mod.utc_now(),
            finished_at=storage_mod.utc_now(),
            records_touched=0,
            status="pass" if verdict.passed else "fail",
            notes=notes,
            verdict="pass" if verdict.passed else "fail",
            failed_checks=",".join(c.name for c in verdict.failed_checks) or None,
            retry_count=0,
        )

        return AgentResult(
            agent=self.name,
            status=status,
            records_touched=0,
            notes=notes,
            payload=verdict,
        )


def _verdict_notes(verdict: Verdict) -> str:
    if verdict.passed:
        return "VERDICT: pass"

    parts: list[str] = []
    for check in verdict.failed_checks:
        observed = check.observed
        threshold = check.threshold
        if check.name == "score_spread" and "spread" in observed:
            parts.append(
                f"score_spread observed {observed['spread']} "
                f"(min {threshold.get('min_score_spread')})"
            )
        elif check.name == "score_spread" and "stdev" in observed:
            parts.append(
                f"score_spread observed stdev {observed['stdev']:.1f} "
                f"(min {threshold.get('min_score_stdev')})"
            )
        elif check.name == "extraction_sanity" and "empty_pct" in observed:
            parts.append(
                f"extraction_sanity observed {observed['empty_pct']:.1f}% empty "
                f"(max {threshold.get('max_empty_extraction_pct')})"
            )
        elif check.name == "gap_sample_size":
            parts.append(
                f"gap_sample_size observed {observed.get('sample_size')} "
                f"(min {threshold.get('min_gap_sample')})"
            )
        elif check.name == "freshness":
            age = observed.get("age_days")
            age_s = f"{age:.1f}" if isinstance(age, (int, float)) else "none"
            parts.append(
                f"freshness observed {age_s} days "
                f"(max {threshold.get('max_data_age_days')})"
            )
        else:
            parts.append(f"{check.name} {check.message}")

    return "VERDICT: fail — " + "; ".join(parts)
