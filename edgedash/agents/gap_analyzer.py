"""
gap_analyzer.py — Gap Analyzer agent: deterministic skill gap analysis.

NO LLM. NO network. Pure deterministic analysis.

Steering rule 24: Gap ranking is weighted by fit score, not raw frequency.
Steering rule 25: Write timestamped snapshots, never overwrite.
Steering rule 26: Every aggregate is traceable to source rows.
Steering rule 27: Report sample size alongside every aggregate.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from edgedash.agents.base import AgentResult
from edgedash.skills import canonical


class GapAnalyzer:
    name: str = "gap_analyzer"

    def run(self, config: Any, storage_mod: Any, stop_conditions: dict[str, Any] | None = None) -> AgentResult:
        """Analyze skill gaps across all scored listings.
        
        Args:
            config: Configuration object
            storage_mod: Storage module
            stop_conditions: Optional limits from orchestrator (max_seconds)
        """
        from edgedash.storage import (
            get_scored_listings_with_facts,
            write_gap_snapshot,
            utc_now,
        )

        listings = get_scored_listings_with_facts()

        if not listings:
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="no scored listings to analyze",
            )

        # Canonicalize my skills
        aliases = config.skill_aliases
        my_skills_canonical = {canonical(s, aliases) for s in config.my_skills}

        # Track gaps per canonical skill
        gap_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "listings": [],
                "nice_to_have_count": 0,
            }
        )

        # Analyze each listing
        for listing in listings:
            required = listing.get("required_skills", [])
            nice = listing.get("nice_to_have", [])

            # Required skills I don't have
            for skill in required:
                skill_canon = canonical(skill, aliases)
                if skill_canon and skill_canon not in my_skills_canonical:
                    gap_data[skill_canon]["listings"].append(listing)

            # Track nice-to-have separately
            for skill in nice:
                skill_canon = canonical(skill, aliases)
                if skill_canon and skill_canon not in my_skills_canonical:
                    gap_data[skill_canon]["nice_to_have_count"] += 1

        # Compute metrics for each gap
        gaps = []
        for skill, data in gap_data.items():
            blocked_listings = data["listings"]

            if not blocked_listings:
                # Only appeared as nice-to-have, skip
                continue

            listings_blocked = len(blocked_listings)
            opportunity_cost = _compute_opportunity_cost(blocked_listings)
            mean_score = sum(l["fit_score"] for l in blocked_listings) / listings_blocked
            top_score = max(l["fit_score"] for l in blocked_listings)

            # Sort by score descending, take top 5 IDs
            blocked_sorted = sorted(
                blocked_listings, key=lambda l: l["fit_score"], reverse=True
            )
            example_ids = [l["id"] for l in blocked_sorted[:5]]

            gaps.append({
                "skill": skill,
                "listings_blocked": listings_blocked,
                "opportunity_cost": opportunity_cost,
                "mean_score": mean_score,
                "top_score": top_score,
                "example_ids": example_ids,
                "also_nice_to_have": data["nice_to_have_count"],
            })

        # Sort by opportunity cost descending
        gaps.sort(key=lambda g: g["opportunity_cost"], reverse=True)

        # Write snapshot (rule 25)
        run_id = str(uuid.uuid4())
        write_gap_snapshot(run_id, gaps)

        # Build notes
        top_10 = gaps[:10]
        if top_10:
            top_gap = top_10[0]
            top_desc = (
                f"{top_gap['skill']} "
                f"({top_gap['listings_blocked']} listings, "
                f"cost {top_gap['opportunity_cost']:.1f})"
            )
            notes = (
                f"{len(top_10)} gaps · top: {top_desc} · "
                f"{len(listings)} listings analysed"
            )
        else:
            notes = f"no gaps found · {len(listings)} listings analysed"

        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=len(gaps),
            notes=notes,
        )


# ---------------------------------------------------------------------------
# Core arithmetic (steering rule 24)
# ---------------------------------------------------------------------------

def _compute_opportunity_cost(listings_requiring_skill: list[dict]) -> float:
    """Compute the weighted opportunity cost of missing a skill.
    
    Steering rule 24: Gap ranking is weighted by the fit score of the
    listing the gap came from. A gap in a listing I score 20 on is worth
    far less than a gap in a listing I score 85 on.
    
    Formula:
        opportunity_cost = sum(listing.fit_score / 100 for listing in listings)
    
    This gives us a 0-N scale where:
    - 1 perfect-match listing (score 100) = cost 1.0
    - 3 mediocre listings (score 33 each) = cost 1.0
    - 10 poor-fit listings (score 10 each) = cost 1.0
    
    The skill blocking the most high-value opportunities ranks first.
    """
    return sum(listing["fit_score"] / 100.0 for listing in listings_requiring_skill)
