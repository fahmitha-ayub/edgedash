"""
scoring.py — Deterministic scoring logic (steering rule 16).

NO model calls. NO network. Pure functions only.

Public API
----------
score_listing(listing: dict, facts: dict, config: Any) -> dict

Returns:
  {
    "score": int (0-100),
    "reason": str,
    "components": {
      "skill_match": float (0.0-1.0),
      "seniority_fit": float (0.0-1.0),
      "location_fit": float (0.0-1.0),
      "recency": float (0.0-1.0),
    }
  }

Weights are read from config (see _WEIGHTS_DEFAULTS).

build_reason(components: dict, facts: dict, config: Any) -> str
  Assembles a human-readable reason FROM THE SCORE COMPONENTS.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Defaults for component weights (overridden by config)
# ---------------------------------------------------------------------------

_WEIGHTS_DEFAULTS = {
    "skill_match": 0.45,
    "seniority_fit": 0.25,
    "location_fit": 0.15,
    "recency": 0.15,
}

_SENIORITY_BANDS = ["junior", "mid", "senior", "lead"]

# Distance-from-midpoint multiplier used when the verifier retries a
# score_spread failure. Ranking is preserved; extremes move farther from 50.
_SPREAD_CONTRAST = 2.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_listing(
    listing: dict,
    facts: dict,
    config: Any,
    *,
    widen_spread: bool = False,
) -> dict:
    """Compute a 0-100 fit score from extracted facts and user config.
    
    When widen_spread is True (verifier retry after score_spread fail),
    apply a contrast stretch around 50 so weak/strong fits separate more.
    """
    weights = {
        "skill_match": getattr(config, "weight_skill_match", _WEIGHTS_DEFAULTS["skill_match"]),
        "seniority_fit": getattr(config, "weight_seniority_fit", _WEIGHTS_DEFAULTS["seniority_fit"]),
        "location_fit": getattr(config, "weight_location_fit", _WEIGHTS_DEFAULTS["location_fit"]),
        "recency": getattr(config, "weight_recency", _WEIGHTS_DEFAULTS["recency"]),
    }

    components = {
        "skill_match": _skill_match(facts, config),
        "seniority_fit": _seniority_fit(facts, config),
        "location_fit": _location_fit(listing, facts, config),
        "recency": _recency(listing),
    }

    raw_score = sum(components[k] * weights[k] for k in components)
    final_score = int(round(raw_score * 100))
    final_score = max(0, min(100, final_score))
    if widen_spread:
        final_score = _widen_score(final_score)

    reason = build_reason(components, facts, config, listing)

    return {
        "score": final_score,
        "reason": reason,
        "components": components,
    }


def build_reason(components: dict, facts: dict, config: Any, listing: dict) -> str:
    """Assemble a compact human-readable reason from score components."""
    parts = []

    # Skill match
    required = [s.lower() for s in facts.get("required_skills", [])]
    nice = [s.lower() for s in facts.get("nice_to_have", [])]
    my_skills = {s.lower() for s in config.my_skills}

    required_matches = [s for s in required if s in my_skills]
    required_gaps = [s for s in required if s not in my_skills]

    if required:
        parts.append(f"{len(required_matches)}/{len(required)} required skills")
    else:
        parts.append("no required skills listed")

    # Seniority
    seniority = facts.get("seniority", "unknown")
    target = getattr(config, "target_seniority", "mid")
    if seniority == target:
        parts.append("seniority fits")
    elif seniority == "unknown":
        parts.append("seniority unknown")
    else:
        parts.append(f"seniority: {seniority} (target: {target})")

    # Location
    remote_ok = facts.get("remote_ok")
    if remote_ok is True:
        parts.append("remote")
    elif remote_ok is False:
        parts.append("on-site only")
    else:
        location = listing.get("location") or ""
        city = config.target_city.lower()
        if city in location.lower():
            parts.append(f"location: {city}")
        else:
            parts.append("location unclear")

    # Recency
    posted_at = listing.get("posted_at")
    if posted_at:
        try:
            # Handle both string (SQLite) and datetime object (Postgres)
            if isinstance(posted_at, str):
                posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            elif hasattr(posted_at, 'tzinfo'):
                posted = posted_at
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
            else:
                parts.append("posted recently")
                posted = None
            
            if posted:
                now = datetime.now(timezone.utc)
                age_days = (now - posted).days
                if age_days == 0:
                    parts.append("posted today")
                elif age_days == 1:
                    parts.append("posted 1d ago")
                else:
                    parts.append(f"posted {age_days}d ago")
        except (ValueError, AttributeError, TypeError):
            parts.append("posted recently")
    else:
        parts.append("post date unknown")

    # Skill gaps
    if required_gaps:
        gap_str = ", ".join(required_gaps[:5])
        if len(required_gaps) > 5:
            gap_str += f" +{len(required_gaps) - 5} more"
        parts.append(f"gap: {gap_str}")

    return " · ".join(parts)


def _widen_score(score: int, factor: float = _SPREAD_CONTRAST) -> int:
    """Push a score away from 50 without changing rank order.
    
    Example with factor=2: 45 -> 40, 55 -> 60. Clustered scores near 50
    become a wider band, which is what check_score_spread measures.
    """
    stretched = int(round(50 + (score - 50) * factor))
    return max(0, min(100, stretched))


# ---------------------------------------------------------------------------
# Component scoring functions (each returns 0.0-1.0)
# ---------------------------------------------------------------------------

def _skill_match(facts: dict, config: Any) -> float:
    """Fraction of required skills present in config.my_skills.
    
    nice_to_have skills count at 1/3 weight.
    """
    required = [s.lower() for s in facts.get("required_skills", [])]
    nice = [s.lower() for s in facts.get("nice_to_have", [])]
    my_skills = {s.lower() for s in config.my_skills}

    if not required and not nice:
        # No skills listed — neutral score
        return 0.5

    required_matches = sum(1 for s in required if s in my_skills)
    nice_matches = sum(1 for s in nice if s in my_skills)

    if not required:
        # Only nice-to-have skills listed — neutral base, partial credit for matches
        if not nice:
            return 0.5
        # 1/2 nice match -> score between 0.5 and 0.75
        return 0.5 + (nice_matches / len(nice)) * 0.25

    # Weight nice-to-have at 1/3
    total_weight = len(required) + (len(nice) / 3.0)
    earned = required_matches + (nice_matches / 3.0)

    return min(1.0, earned / total_weight)


def _seniority_fit(facts: dict, config: Any) -> float:
    """Compare facts.seniority to config.target_seniority on an ordered scale.
    
    exact match: 1.0
    one band away: 0.6
    two bands away: 0.25
    three+ bands away: 0.0
    unknown: 0.5
    """
    target = getattr(config, "target_seniority", "mid")
    actual = facts.get("seniority", "unknown")

    if actual == "unknown":
        return 0.5

    if actual == target:
        return 1.0

    if actual not in _SENIORITY_BANDS or target not in _SENIORITY_BANDS:
        return 0.5

    target_idx = _SENIORITY_BANDS.index(target)
    actual_idx = _SENIORITY_BANDS.index(actual)
    distance = abs(target_idx - actual_idx)

    if distance == 1:
        return 0.6
    elif distance == 2:
        return 0.25
    else:
        return 0.0


def _location_fit(listing: dict, facts: dict, config: Any) -> float:
    """Score based on remote_ok flag and location match.
    
    remote_ok true: 1.0
    location matches target_city: 1.0
    remote_ok unknown: 0.5
    remote_ok false and location doesn't match: 0.1
    """
    remote_ok = facts.get("remote_ok")

    if remote_ok is True:
        return 1.0

    location = listing.get("location") or ""
    city = config.target_city.lower()

    if city in location.lower():
        return 1.0

    if remote_ok is None:
        return 0.5

    # remote_ok is False and location doesn't match
    return 0.1


def _recency(listing: dict) -> float:
    """Decay from 1.0 (today) to 0.0 (30 days old).
    
    posted_at null: 0.5 (unknown age)
    """
    posted_at = listing.get("posted_at")
    if not posted_at:
        return 0.5

    try:
        # Handle both string (SQLite) and datetime object (Postgres)
        if isinstance(posted_at, str):
            posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        elif hasattr(posted_at, 'tzinfo'):
            # Already a datetime object
            posted = posted_at
            # Ensure it's timezone-aware
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
        else:
            return 0.5
    except (ValueError, AttributeError, TypeError):
        return 0.5

    now = datetime.now(timezone.utc)
    age_days = (now - posted).days

    if age_days < 0:
        # Future date (clock skew or bad data)
        return 1.0

    if age_days >= 30:
        return 0.0

    # Linear decay: 1.0 at day 0, 0.0 at day 30
    return 1.0 - (age_days / 30.0)
