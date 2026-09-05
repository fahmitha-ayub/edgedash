"""
base.py — Agent protocol and AgentResult dataclass.

Every agent in EdgeDash must satisfy the Agent protocol:
  - a `name` class attribute (str)
  - a `run(config, storage_module) -> AgentResult` method

Using typing.Protocol keeps this structural (no forced inheritance) while
still being checkable with a type checker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class AgentResult:
    agent: str
    status: str          # "ok" | "failed"
    records_touched: int
    notes: str = ""
    payload: Any = None  # optional structured result (e.g. Verdict)


@runtime_checkable
class Agent(Protocol):
    name: str

    def run(self, config: Any, storage: Any) -> AgentResult:
        ...
