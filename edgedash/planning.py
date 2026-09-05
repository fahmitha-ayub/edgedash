"""
planning.py — Execution planning (steering rule 28, 29, 31).

NO LLM. NO I/O. Pure function of (state, config).

Public API
----------
build_plan(state: SystemState, config: Any) -> Plan
  Build an execution plan from system state. Pure function, deterministic.

Task: A single agent invocation with goal, stop conditions, and reason.
Plan: An ordered list of Tasks with rendering support.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Task:
    """A single agent invocation (steering rule 29)."""
    agent_name: str
    goal: str
    stop_conditions: dict[str, Any]  # max_items, max_seconds, max_pages, etc.
    reason: str  # Human-readable state value that caused this decision
    skipped: bool = False


@dataclass
class Plan:
    """An ordered execution plan (steering rule 31)."""
    tasks: list[Task]
    
    def render(self) -> str:
        """Render the plan as a human-readable string."""
        lines = ["EXECUTION PLAN", "=" * 50, ""]
        
        has_work = any(not t.skipped for t in self.tasks)
        
        for task in self.tasks:
            status = "SKIP" if task.skipped else "RUN "
            lines.append(f"{task.agent_name:<14}: {status} · {task.goal}")
            
            if not task.skipped and task.stop_conditions:
                conds = ", ".join(f"{k}={v}" for k, v in task.stop_conditions.items())
                lines.append(f"                limits: {conds}")
            
            lines.append(f"                reason: {task.reason}")
            lines.append("")
        
        if not has_work:
            lines.append("All agents skipped. Cycle will complete immediately.")
        
        return "\n".join(lines)
    
    def runnable_tasks(self) -> list[Task]:
        """Return only the tasks that should actually run."""
        return [t for t in self.tasks if not t.skipped]


def build_plan(state: Any, config: Any) -> Plan:
    """Build an execution plan from system state (steering rule 28).
    
    Pure function. No I/O. Deterministic.
    
    Decision rules:
    - fetch: if hours_since_fetch >= fetch_interval_hours
    - score: if unscored_count > 0
    - analyse: if gaps_stale or gaps_computed_at is None
    
    Skipped agents appear in the plan with reason (rule 31).
    """
    tasks = []
    
    # Fetch decision
    fetch_interval = getattr(config, "fetch_interval_hours", 6)
    if state.hours_since_fetch >= fetch_interval or state.last_fetch_at is None:
        tasks.append(Task(
            agent_name="fetcher",
            goal="fetch new job listings",
            stop_conditions={
                "max_pages": getattr(config, "max_fetch_pages", 5),
                "max_listings": getattr(config, "max_fetch_listings", 100),
            },
            reason=f"hours_since_fetch={state.hours_since_fetch:.1f}",
            skipped=False,
        ))
    else:
        tasks.append(Task(
            agent_name="fetcher",
            goal="fetch new job listings",
            stop_conditions={},
            reason=f"skipped: hours_since_fetch={state.hours_since_fetch:.1f} < {fetch_interval}",
            skipped=True,
        ))
    
    # Score decision
    if state.unscored_count > 0:
        tasks.append(Task(
            agent_name="scorer",
            goal="score unscored listings",
            stop_conditions={
                "max_items": config.llm_batch_size,
                "max_seconds": getattr(config, "max_score_seconds", 300),
            },
            reason=f"unscored_count={state.unscored_count}",
            skipped=False,
        ))
    else:
        tasks.append(Task(
            agent_name="scorer",
            goal="score unscored listings",
            stop_conditions={},
            reason="skipped: unscored_count=0",
            skipped=True,
        ))
    
    # Gap analysis decision
    if state.gaps_stale or state.gaps_computed_at is None:
        stale_reason = "gaps_stale=true" if state.gaps_stale else "gaps_computed_at=null"
        tasks.append(Task(
            agent_name="gap_analyzer",
            goal="analyze skill gaps",
            stop_conditions={
                "max_seconds": getattr(config, "max_analyze_seconds", 60),
            },
            reason=stale_reason,
            skipped=False,
        ))
    else:
        tasks.append(Task(
            agent_name="gap_analyzer",
            goal="analyze skill gaps",
            stop_conditions={},
            reason="skipped: gaps up-to-date",
            skipped=True,
        ))
    
    return Plan(tasks=tasks)
