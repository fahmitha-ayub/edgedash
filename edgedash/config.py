"""
config.py — loads and validates the EdgeDash Config dataclass from config.yaml.

Dependency: PyYAML (third-party).
Reason: config.yaml is human-edited; PyYAML saves non-trivial parsing work
compared to tomllib or a hand-rolled parser. One small, stable dependency.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # PyYAML

# Load .env if present
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with _env_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Config:
    target_role: str
    target_city: str
    keywords: list[str]
    my_skills: list[str]
    experience_years: int
    db_path: str
    min_fit_score: int
    sources: list[str]
    use_mock_fetcher: bool
    llm_provider: str
    llm_model: str
    llm_batch_size: int
    target_seniority: str
    weight_skill_match: float
    weight_seniority_fit: float
    weight_location_fit: float
    weight_recency: float
    skill_aliases: dict[str, str]
    min_score_spread: int
    min_score_stdev: int
    max_empty_extraction_pct: int
    max_skills_per_listing: int
    min_gap_sample: int
    max_data_age_days: int


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "target_role": "Software Engineer",
    "target_city": "Remote",
    "keywords": [],
    "my_skills": [],
    "experience_years": 0,
    "db_path": "edgedash.db",
    "min_fit_score": 50,
    "sources": ["arbeitnow"],
    "use_mock_fetcher": False,
    "llm_provider": "gemini",
    "llm_model": "gemini-3.6-flash",
    "llm_batch_size": 25,
    "target_seniority": "mid",
    "weight_skill_match": 0.45,
    "weight_seniority_fit": 0.25,
    "weight_location_fit": 0.15,
    "weight_recency": 0.15,
    "skill_aliases": {},
    "min_score_spread": 10,
    "min_score_stdev": 5,
    "max_empty_extraction_pct": 20,
    "max_skills_per_listing": 20,
    "min_gap_sample": 3,
    "max_data_age_days": 3,
    "fetch_interval_hours": 6,
    "max_fetch_pages": 5,
    "max_fetch_listings": 100,
    "max_score_seconds": 300,
    "max_analyze_seconds": 60,
}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(config_path: str | Path | None = None) -> Config:
    """Read config.yaml and return a validated Config instance.

    Raises FileNotFoundError if config.yaml is absent.
    Raises TypeError if a field has the wrong type.
    Falls back to _DEFAULTS for any field that is missing but optional.
    """
    path = Path(config_path) if config_path else _locate_config()

    if not path.exists():
        raise FileNotFoundError(
            f"config.yaml not found at '{path.resolve()}'. "
            "Copy config.yaml.example to config.yaml and fill in your details."
        )

    with path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    data = {**_DEFAULTS, **raw}

    _validate(data)

    return Config(
        target_role=data["target_role"],
        target_city=data["target_city"],
        keywords=data["keywords"],
        my_skills=data["my_skills"],
        experience_years=data["experience_years"],
        db_path=data["db_path"],
        min_fit_score=data["min_fit_score"],
        sources=data["sources"],
        use_mock_fetcher=data["use_mock_fetcher"],
        llm_provider=data["llm_provider"],
        llm_model=data["llm_model"],
        llm_batch_size=data["llm_batch_size"],
        target_seniority=data["target_seniority"],
        weight_skill_match=data["weight_skill_match"],
        weight_seniority_fit=data["weight_seniority_fit"],
        weight_location_fit=data["weight_location_fit"],
        weight_recency=data["weight_recency"],
        skill_aliases=data["skill_aliases"],
        min_score_spread=data["min_score_spread"],
        min_score_stdev=data["min_score_stdev"],
        max_empty_extraction_pct=data["max_empty_extraction_pct"],
        max_skills_per_listing=data["max_skills_per_listing"],
        min_gap_sample=data["min_gap_sample"],
        max_data_age_days=data["max_data_age_days"],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _locate_config() -> Path:
    """Walk up from the current working directory to find config.yaml."""
    candidates = [
        Path.cwd() / "config.yaml",
        Path(__file__).resolve().parent.parent / "config.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Return the repo-root candidate so FileNotFoundError has a useful path.
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _validate(data: dict[str, Any]) -> None:
    """Raise TypeError with a clear message if any field has the wrong type."""
    str_fields = ("target_role", "target_city", "db_path", "llm_provider", "llm_model", "target_seniority")
    list_fields = ("keywords", "my_skills", "sources")
    int_fields = (
        "experience_years", "min_fit_score", "llm_batch_size",
        "min_score_spread", "min_score_stdev", "max_empty_extraction_pct",
        "max_skills_per_listing", "min_gap_sample", "max_data_age_days",
    )
    float_fields = ("weight_skill_match", "weight_seniority_fit", "weight_location_fit", "weight_recency")

    for key in str_fields:
        if not isinstance(data[key], str):
            raise TypeError(f"config.yaml: '{key}' must be a string, got {type(data[key]).__name__}")

    for key in list_fields:
        if not isinstance(data[key], list):
            raise TypeError(f"config.yaml: '{key}' must be a list, got {type(data[key]).__name__}")

    for key in int_fields:
        if not isinstance(data[key], int):
            raise TypeError(f"config.yaml: '{key}' must be an integer, got {type(data[key]).__name__}")

    for key in float_fields:
        if not isinstance(data[key], (int, float)):
            raise TypeError(f"config.yaml: '{key}' must be a number, got {type(data[key]).__name__}")

    if not isinstance(data["use_mock_fetcher"], bool):
        raise TypeError(
            f"config.yaml: 'use_mock_fetcher' must be a boolean, "
            f"got {type(data['use_mock_fetcher']).__name__}"
        )
