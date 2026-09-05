"""
sources/base.py — Source protocol and global registry.

Every source class must:
  - set a class-level `name: str`
  - implement `fetch(config) -> list[dict]`

Each returned dict must contain EXACTLY these keys (missing values are None,
never empty string, never "N/A"):
  source, external_id, title, company, location, url,
  description, posted_at, raw

Usage
-----
Register a source by decorating its class with @register:

    @register
    class MySource:
        name = "my_source"
        def fetch(self, config): ...

Retrieve all registered classes:

    from edgedash.sources.base import SOURCES
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Normalised row keys (steering rule 10)
# ---------------------------------------------------------------------------

REQUIRED_KEYS: tuple[str, ...] = (
    "source",
    "external_id",
    "title",
    "company",
    "location",
    "url",
    "description",
    "posted_at",
    "raw",
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Source(Protocol):
    name: str

    def fetch(self, config: Any) -> list[dict]:
        """Fetch listings and return them normalised to REQUIRED_KEYS."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SOURCES: dict[str, type] = {}


def register(cls: type) -> type:
    """Class decorator that adds cls to the SOURCES registry by cls.name."""
    SOURCES[cls.name] = cls
    return cls
