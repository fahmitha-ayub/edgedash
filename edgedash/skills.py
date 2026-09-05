"""
skills.py — Deterministic skill name canonicalisation (steering rule 23).

NO LLM. NO network. Pure functions only.

Public API
----------
canonical(raw: str, aliases: dict[str, str]) -> str
  Normalize a raw skill string to its canonical form.
"""
from __future__ import annotations

import re
from typing import Any


def canonical(raw: str, aliases: dict[str, str]) -> str:
    """Normalize a raw skill string to its canonical form.
    
    Steps:
    1. Lowercase
    2. Strip leading/trailing whitespace
    3. Strip wrapping punctuation (quotes, parens around the whole string)
    4. Drop parenthetical qualifiers: "kubernetes (eks)" -> "kubernetes"
    5. Collapse internal whitespace to single spaces
    6. Apply alias map
    
    Pure function. Same input, same output. No network, no model.
    
    Examples:
        canonical("  Python  ", {}) -> "python"
        canonical("Kubernetes (EKS)", {}) -> "kubernetes"
        canonical("K8s", {"k8s": "kubernetes"}) -> "kubernetes"
        canonical("CI/CD", {}) -> "ci/cd"
        canonical("", {}) -> ""
    """
    if not raw:
        return ""
    
    # Step 1: Lowercase
    s = raw.lower()
    
    # Step 2: Strip leading/trailing whitespace
    s = s.strip()
    
    # Step 3: Drop parenthetical qualifiers FIRST (before stripping parens)
    #         Matches " (eks)" or " (version 2)" etc.
    s = re.sub(r"\s+\([^)]*\)", "", s)
    
    # Step 4: Strip wrapping punctuation (but NOT dots, slashes, or hyphens)
    # These are NOT stripped: . / - + # (part of skill names like .net, c++, c#, ci/cd)
    s = s.strip(",;:!?()[]{}\"'`")
    
    # Step 5: Collapse internal whitespace
    s = re.sub(r"\s+", " ", s).strip()
    
    # Step 6: Apply alias map
    return aliases.get(s, s)


# ---------------------------------------------------------------------------
# Audit command
# ---------------------------------------------------------------------------

def _audit() -> None:
    """CLI: python -m edgedash.skills --audit
    
    Read all extracted required_skills from the database and show:
    - Top 40 most common raw skill strings with counts
    - Their canonical forms
    - Raw strings that appear only once (likely typos/junk)
    """
    from edgedash.config import load_config
    from edgedash.storage import init_db
    import sqlite3
    from collections import Counter

    config = load_config()
    init_db(config.db_path)
    
    aliases = config.skill_aliases

    # Read all required_skills from extraction_cache
    conn = sqlite3.connect(config.db_path)
    conn.row_factory = sqlite3.Row
    
    rows = conn.execute(
        "SELECT required_skills FROM extraction_cache"
    ).fetchall()
    
    conn.close()

    if not rows:
        print("No extracted skills in the database yet.")
        return

    # Parse JSON arrays and count raw skill occurrences
    import json
    raw_skills: list[str] = []
    
    for row in rows:
        skills_json = row["required_skills"]
        skills = json.loads(skills_json)
        raw_skills.extend(skills)

    if not raw_skills:
        print("No required skills extracted yet.")
        return

    counter = Counter(raw_skills)
    
    # Top 40 most common
    top_40 = counter.most_common(40)
    
    print("=" * 70)
    print("SKILL CANONICALISATION AUDIT")
    print("=" * 70)
    print(f"\nTotal raw skill mentions: {len(raw_skills)}")
    print(f"Unique raw skill strings: {len(counter)}")
    print(f"\nTop 40 most common skills:\n")
    print(f"{'Count':<8} {'Raw Skill':<30} {'Canonical Form':<30}")
    print("-" * 70)
    
    for skill, count in top_40:
        canon = canonical(skill, aliases)
        marker = "" if canon == skill else " *"
        print(f"{count:<8} {skill:<30} {canon:<30}{marker}")
    
    print("\n(* = aliased to different canonical form)")
    
    # Singles (likely typos or junk)
    singles = [skill for skill, count in counter.items() if count == 1]
    
    if singles:
        print(f"\n{'=' * 70}")
        print(f"SKILLS SEEN ONLY ONCE ({len(singles)} total)")
        print("These are often typos, junk, or full sentences:")
        print("=" * 70)
        
        for skill in sorted(singles)[:50]:  # Show first 50
            print(f"  - {skill}")
        
        if len(singles) > 50:
            print(f"\n  ... and {len(singles) - 50} more")
    
    print()


if __name__ == "__main__":
    import sys
    
    if "--audit" in sys.argv:
        _audit()
    else:
        print("Usage: python -m edgedash.skills --audit")
