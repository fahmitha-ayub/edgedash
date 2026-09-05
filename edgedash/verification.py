"""
verification.py — Deterministic verification checks (steering rules 34-39).

NO LLM. A model cannot be the judge of a model's output.

Every check is a pure function: same inputs, same result, no clock, no network,
no database reads. Thresholds come from config (rule 39).

Public API
----------
run_all_checks(...) -> Verdict
  Run all verification checks and return an aggregate verdict.

CheckResult: Individual check result with name, passed, observed, threshold, message.
Verdict: Aggregate result with passed flag, failed_checks list, and summary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class CheckResult:
    """Result of a single verification check."""
    name: str
    passed: bool
    observed: dict[str, Any]  # Actual values observed
    threshold: dict[str, Any]  # Threshold values from config
    message: str  # Human-readable explanation


@dataclass
class Verdict:
    """Aggregate verification verdict."""
    passed: bool
    failed_checks: list[CheckResult]
    summary: str


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_score_spread(scores: list[int], config: Any) -> CheckResult:
    """Verify score distribution has adequate spread (catches inflation).
    
    Steering rule 35: Plausibility check on distribution shape.
    
    FAILS if:
    - spread (max - min) < min_score_spread, OR
    - standard deviation < min_score_stdev
    
    Passes trivially if fewer than 5 scores (insufficient sample).
    """
    min_spread = getattr(config, "min_score_spread", 10)
    min_stdev = getattr(config, "min_score_stdev", 5)
    
    if len(scores) < 5:
        return CheckResult(
            name="score_spread",
            passed=True,
            observed={"count": len(scores)},
            threshold={"min_score_spread": min_spread, "min_score_stdev": min_stdev},
            message=f"Trivial pass: only {len(scores)} scores (need 5+ for spread check)",
        )
    
    spread = max(scores) - min(scores)
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    stdev = variance ** 0.5
    
    if spread < min_spread:
        return CheckResult(
            name="score_spread",
            passed=False,
            observed={"spread": spread, "stdev": stdev, "count": len(scores)},
            threshold={"min_score_spread": min_spread, "min_score_stdev": min_stdev},
            message=f"Score spread too narrow: {spread} < {min_spread} (inflation suspected)",
        )
    
    if stdev < min_stdev:
        return CheckResult(
            name="score_spread",
            passed=False,
            observed={"spread": spread, "stdev": stdev, "count": len(scores)},
            threshold={"min_score_spread": min_spread, "min_score_stdev": min_stdev},
            message=f"Score stdev too low: {stdev:.1f} < {min_stdev} (all scores clustered)",
        )
    
    return CheckResult(
        name="score_spread",
        passed=True,
        observed={"spread": spread, "stdev": stdev, "count": len(scores)},
        threshold={"min_score_spread": min_spread, "min_score_stdev": min_stdev},
        message=f"Score distribution healthy: spread={spread}, stdev={stdev:.1f}",
    )


def check_extraction_sanity(facts_list: list[dict], config: Any) -> CheckResult:
    """Verify extraction results look reasonable (catches broken extractor).
    
    Steering rule 35: Plausibility check on extraction output.
    
    FAILS if:
    - More than max_empty_extraction_pct have empty required_skills, OR
    - Any listing has more than max_skills_per_listing (likely a sentence)
    """
    max_empty_pct = getattr(config, "max_empty_extraction_pct", 20)
    max_skills_per = getattr(config, "max_skills_per_listing", 20)
    
    if not facts_list:
        return CheckResult(
            name="extraction_sanity",
            passed=True,
            observed={"count": 0},
            threshold={"max_empty_extraction_pct": max_empty_pct, "max_skills_per_listing": max_skills_per},
            message="No extractions to check",
        )
    
    empty_count = sum(1 for f in facts_list if not f.get("required_skills", []))
    empty_pct = (empty_count / len(facts_list)) * 100
    
    if empty_pct > max_empty_pct:
        return CheckResult(
            name="extraction_sanity",
            passed=False,
            observed={"empty_pct": empty_pct, "empty_count": empty_count, "total": len(facts_list)},
            threshold={"max_empty_extraction_pct": max_empty_pct},
            message=f"Too many empty extractions: {empty_pct:.1f}% > {max_empty_pct}% (extractor broken?)",
        )
    
    # Check for any listing with excessive skills (sentence extraction failure)
    max_observed = max(len(f.get("required_skills", [])) for f in facts_list)
    
    if max_observed > max_skills_per:
        return CheckResult(
            name="extraction_sanity",
            passed=False,
            observed={"max_skills_in_one": max_observed, "total": len(facts_list)},
            threshold={"max_skills_per_listing": max_skills_per},
            message=f"One listing has {max_observed} skills > {max_skills_per} (extracted a sentence?)",
        )
    
    return CheckResult(
        name="extraction_sanity",
        passed=True,
        observed={"empty_pct": empty_pct, "max_skills_in_one": max_observed, "total": len(facts_list)},
        threshold={"max_empty_extraction_pct": max_empty_pct, "max_skills_per_listing": max_skills_per},
        message=f"Extractions look reasonable: {empty_pct:.1f}% empty, max {max_observed} skills/listing",
    )


def check_gap_sample_size(gaps: list[dict], config: Any) -> CheckResult:
    """Verify top gap has sufficient sample (catches ranking a rumour).
    
    Steering rule 35: Plausibility check on aggregate confidence.
    
    FAILS if the top-ranked gap was computed from fewer than min_gap_sample listings.
    """
    min_sample = getattr(config, "min_gap_sample", 3)
    
    if not gaps:
        return CheckResult(
            name="gap_sample_size",
            passed=True,
            observed={"gap_count": 0},
            threshold={"min_gap_sample": min_sample},
            message="No gaps to check",
        )
    
    top_gap = gaps[0]
    sample_size = top_gap.get("listings_blocked", 0)
    
    if sample_size < min_sample:
        return CheckResult(
            name="gap_sample_size",
            passed=False,
            observed={"top_skill": top_gap["skill"], "sample_size": sample_size},
            threshold={"min_gap_sample": min_sample},
            message=f"Top gap '{top_gap['skill']}' based on only {sample_size} listings < {min_sample} (rumour?)",
        )
    
    return CheckResult(
        name="gap_sample_size",
        passed=True,
        observed={"top_skill": top_gap["skill"], "sample_size": sample_size},
        threshold={"min_gap_sample": min_sample},
        message=f"Top gap '{top_gap['skill']}' based on {sample_size} listings (sufficient)",
    )


def check_freshness(latest_fetch_at: str | None, config: Any, now: datetime) -> CheckResult:
    """Verify data is not stale (catches dead fetcher).
    
    Steering rule 35: Plausibility check on data age.
    
    FAILS if the newest listing is older than max_data_age_days.
    `now` is a PARAMETER for testability (never datetime.now() inside).
    """
    max_age_days = getattr(config, "max_data_age_days", 3)
    
    if latest_fetch_at is None:
        return CheckResult(
            name="freshness",
            passed=False,
            observed={"latest_fetch_at": None},
            threshold={"max_data_age_days": max_age_days},
            message="No listings in database (fetcher never ran?)",
        )
    
    try:
        latest_dt = datetime.fromisoformat(latest_fetch_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return CheckResult(
            name="freshness",
            passed=False,
            observed={"latest_fetch_at": latest_fetch_at, "parse_error": True},
            threshold={"max_data_age_days": max_age_days},
            message=f"Cannot parse latest_fetch_at: {latest_fetch_at}",
        )
    
    age_days = (now - latest_dt).total_seconds() / 86400.0
    
    if age_days > max_age_days:
        return CheckResult(
            name="freshness",
            passed=False,
            observed={"age_days": age_days, "latest_fetch_at": latest_fetch_at},
            threshold={"max_data_age_days": max_age_days},
            message=f"Data is {age_days:.1f} days old > {max_age_days} (fetcher dead?)",
        )
    
    return CheckResult(
        name="freshness",
        passed=True,
        observed={"age_days": age_days, "latest_fetch_at": latest_fetch_at},
        threshold={"max_data_age_days": max_age_days},
        message=f"Data is fresh: {age_days:.1f} days old",
    )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def run_all_checks(
    scores: list[int],
    facts_list: list[dict],
    gaps: list[dict],
    latest_fetch_at: str | None,
    config: Any,
    now: datetime,
) -> Verdict:
    """Run all verification checks and return aggregate verdict.
    
    Passes only if ALL checks pass (steering rule 34).
    """
    results = [
        check_score_spread(scores, config),
        check_extraction_sanity(facts_list, config),
        check_gap_sample_size(gaps, config),
        check_freshness(latest_fetch_at, config, now),
    ]
    
    failed = [r for r in results if not r.passed]
    passed = all(r.passed for r in results)
    
    if passed:
        summary = f"All {len(results)} checks passed"
    else:
        summary = f"{len(failed)}/{len(results)} checks failed: " + ", ".join(f.name for f in failed)
    
    return Verdict(
        passed=passed,
        failed_checks=failed,
        summary=summary,
    )
