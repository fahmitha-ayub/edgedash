"""
extractor.py — Extract structured facts from job descriptions via LLM.

This is the ONLY part of the Scorer that calls a model (steering rule 16).

Public API
----------
extract(listing: dict) -> dict

Returns a dict with these keys (and ONLY these keys):
  required_skills: list[str]
  nice_to_have: list[str]
  seniority: "junior" | "mid" | "senior" | "lead" | "unknown"
  years_required: int | None
  remote_ok: bool | None

The model never sees scoring weights, never sees the candidate profile,
and never assigns a score. It reads a document and extracts facts.

Caching (steering rule 18):
  - Hash the job description text.
  - Check the cache first. On a hit, return immediately with no model call.
  - On a miss, call llm.complete_json, store the result, and return it.
  - The same description text is never sent to the model twice.
"""
from __future__ import annotations

import hashlib
from typing import Any

from edgedash.llm import complete_json
from edgedash.storage import get_cached_extraction, cache_extraction


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

EXTRACTION_SCHEMA = {
    "type": "object",
    "required": [
        "required_skills",
        "nice_to_have",
        "seniority",
        "years_required",
        "remote_ok",
    ],
    "properties": {
        "required_skills": {
            "type": "array",
            "description": "Skills explicitly required for the role",
        },
        "nice_to_have": {
            "type": "array",
            "description": "Skills mentioned as preferred or nice-to-have",
        },
        "seniority": {
            "type": "string",
            "enum": ["junior", "mid", "senior", "lead", "unknown"],
            "description": "Seniority level if stated, else unknown",
        },
        "years_required": {
            "type": ["number", "null"],
            "description": "Minimum years of experience if stated, else null",
        },
        "remote_ok": {
            "type": ["boolean", "null"],
            "description": "True if remote work is mentioned, false if explicitly on-site only, null if not stated",
        },
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract(listing: dict) -> dict:
    """Extract structured facts from a job listing.
    
    Checks the cache first. On a cache miss, calls the LLM and caches the result.
    Returns a dict conforming to EXTRACTION_SCHEMA.
    """
    description = listing.get("description", "")
    description_hash = _hash_text(description)

    # Check cache first
    cached = get_cached_extraction(description_hash)
    if cached is not None:
        return cached

    # Cache miss — call LLM
    title = listing.get("title", "Untitled")
    company = listing.get("company", "Unknown")
    
    prompt = _build_prompt(title, company, description)
    
    raw_facts = complete_json(prompt, EXTRACTION_SCHEMA, max_retries=1)
    
    # Normalize skill names to lowercase
    facts = _normalize_facts(raw_facts)
    
    # Cache the result
    cache_extraction(description_hash, facts)
    
    return facts


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _build_prompt(title: str, company: str, description: str) -> str:
    return f"""You are reading a job listing to extract structured facts.

Title: {title}
Company: {company}
Description:
{description}

Extract ONLY what the listing explicitly states. Do not infer, guess, or evaluate anything.

Rules:
- required_skills: list the skills, technologies, or qualifications the listing says are REQUIRED or MUST-HAVE. Return lowercase names (e.g., "python", "react", "aws").
- nice_to_have: list skills mentioned as preferred, nice-to-have, or bonus. Return lowercase names.
- seniority: choose one of "junior", "mid", "senior", "lead", or "unknown". Use "unknown" if the listing doesn't specify a level.
- years_required: the minimum years of experience stated (e.g., "3+ years" → 3). Return null if not mentioned.
- remote_ok: true if the listing mentions remote work is allowed, false if it says on-site only, null if it doesn't specify.

If a field has no information in the listing, return an empty list (for arrays), null (for numbers/booleans), or "unknown" (for seniority).

Do NOT mention or consider any candidate. You are reading a document, nothing more."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_text(text: str) -> str:
    """Compute a stable SHA-256 hash of the text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_facts(facts: dict) -> dict:
    """Normalize skill names to lowercase and ensure schema compliance."""
    return {
        "required_skills": [s.lower() for s in facts.get("required_skills", [])],
        "nice_to_have": [s.lower() for s in facts.get("nice_to_have", [])],
        "seniority": facts.get("seniority", "unknown"),
        "years_required": facts.get("years_required"),
        "remote_ok": facts.get("remote_ok"),
    }
