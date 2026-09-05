"""
orchestrator.py — State-driven cycle orchestration (steering rules 28-33, 36).

The Orchestrator reads system state, builds a plan, prints it, executes it,
verifies output, retries at most once, and logs the outcome. It never runs a
fixed sequence. Skipping work because there is nothing to do is a SUCCESS.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from edgedash.agents.base import AgentResult
from edgedash.planning import Plan, build_plan
from edgedash.state import read_state
from edgedash.verification import Verdict


# Failed check name -> agent that produced the data the check judged.
_CHECK_AGENT = {
    "score_spread": "scorer",
    "extraction_sanity": "scorer",
    "gap_sample_size": "gap_analyzer",
    "freshness": "fetcher",
}


def run_cycle(config: Any) -> int:
    """Run one orchestration cycle.

    Returns:
        Exit code: 0 for success (including nothing_to_do and degraded), 1 for failure.
    """
    import edgedash.storage as storage

    storage.init_db(config.db_path)

    start_time = time.time()
    started_at = storage.utc_now()

    now = datetime.now(timezone.utc)
    state = read_state(config, now)
    plan = build_plan(state, config)

    print(plan.render())
    print()

    runnable = plan.runnable_tasks()

    if not runnable:
        _log_cycle_summary(
            started_at=started_at,
            duration=time.time() - start_time,
            plan=plan,
            results={},
            outcome="nothing_to_do",
            verdict=None,
            failed_checks=None,
            retry_count=0,
        )
        print("Cycle complete: nothing_to_do")
        return 0

    registry = _build_registry(config)
    results, had_failure = _execute_tasks(runnable, registry, config, storage)

    retry_count = 0
    verdict: Verdict | None = None
    verify_result = _run_verifier(registry, config, storage)
    results["verifier"] = verify_result
    if isinstance(verify_result, AgentResult):
        verdict = verify_result.payload

    if isinstance(verdict, Verdict) and not verdict.passed:
        agent_name = _agent_for_failure(verdict)
        stop = _adjusted_stop_conditions(plan, agent_name, verdict.failed_checks, config)
        print(f"[RETRY] {agent_name} (one retry for this cycle)")
        retry_count = 1
        retry_result = _run_one_agent(registry, agent_name, config, storage, stop)
        results[agent_name] = retry_result
        if isinstance(retry_result, Exception):
            had_failure = True
        print()

        verify_result = _run_verifier(registry, config, storage)
        results["verifier"] = verify_result
        if isinstance(verify_result, AgentResult):
            verdict = verify_result.payload

        if isinstance(verdict, Verdict) and not verdict.passed:
            failed_names = ",".join(c.name for c in verdict.failed_checks)
            total_duration = time.time() - start_time
            print(f"Verification failed after retry: {verdict.summary}")
            print("Cycle marked degraded — stopping (no further retry).")
            _log_cycle_summary(
                started_at=started_at,
                duration=total_duration,
                plan=plan,
                results=results,
                outcome="degraded",
                verdict="fail",
                failed_checks=failed_names,
                retry_count=retry_count,
            )
            print(f"Cycle complete: degraded · {total_duration:.1f}s")
            return 0

    if had_failure:
        outcome = "partial"
    else:
        outcome = "complete"

    passed = isinstance(verdict, Verdict) and verdict.passed
    failed_names = None
    if isinstance(verdict, Verdict) and verdict.failed_checks:
        failed_names = ",".join(c.name for c in verdict.failed_checks)

    total_duration = time.time() - start_time
    _log_cycle_summary(
        started_at=started_at,
        duration=total_duration,
        plan=plan,
        results=results,
        outcome=outcome,
        verdict="pass" if passed else "fail",
        failed_checks=failed_names,
        retry_count=retry_count,
    )

    print(f"Cycle complete: {outcome} · {total_duration:.1f}s")
    return 0 if outcome in ("complete", "partial") else 1


def _execute_tasks(
    runnable: list[Any],
    registry: dict[str, Any],
    config: Any,
    storage: Any,
) -> tuple[dict[str, AgentResult | Exception], bool]:
    results: dict[str, AgentResult | Exception] = {}
    had_failure = False
    for task in runnable:
        if task.agent_name not in registry:
            print(f"[ERROR] Agent '{task.agent_name}' not in registry")
            had_failure = True
            continue
        print(f"[RUN] {task.agent_name}: {task.goal}")
        result = _run_one_agent(
            registry, task.agent_name, config, storage, task.stop_conditions,
        )
        results[task.agent_name] = result
        if isinstance(result, Exception):
            had_failure = True
        print()
    return results, had_failure


def _run_one_agent(
    registry: dict[str, Any],
    agent_name: str,
    config: Any,
    storage: Any,
    stop_conditions: dict[str, Any] | None,
) -> AgentResult | Exception:
    agent = registry[agent_name]
    task_start = time.time()
    try:
        result = agent.run(config, storage, stop_conditions=stop_conditions)
        print(f"  → {result.status} · {result.notes} · {time.time() - task_start:.1f}s")
        return result
    except Exception as exc:
        print(f"  → FAILED · {exc} · {time.time() - task_start:.1f}s")
        return exc


def _run_verifier(
    registry: dict[str, Any],
    config: Any,
    storage: Any,
) -> AgentResult | Exception:
    print("[RUN] verifier: judge output plausibility")
    return _run_one_agent(registry, "verifier", config, storage, None)


def _agent_for_failure(verdict: Verdict) -> str:
    """Map the first failed check to the agent that produced it."""
    return _CHECK_AGENT.get(verdict.failed_checks[0].name, "scorer")


def _adjusted_stop_conditions(
    plan: Plan,
    agent_name: str,
    failed_checks: list[Any],
    config: Any,
) -> dict[str, Any]:
    task = next((t for t in plan.tasks if t.agent_name == agent_name), None)
    stop = dict(task.stop_conditions) if task and task.stop_conditions else {}
    failed_names = {c.name for c in failed_checks}
    # Stricter scoring: Scorer re-scores with contrast stretch around 50.
    if "score_spread" in failed_names:
        stop["widen_spread"] = True
        stop.setdefault("max_items", getattr(config, "llm_batch_size", 25))
    return stop


def _log_cycle_summary(
    started_at: str,
    duration: float,
    plan: Any,
    results: dict[str, Any],
    outcome: str,
    verdict: str | None,
    failed_checks: str | None,
    retry_count: int,
) -> None:
    """Write exactly one cycle summary row (rule 33) including verification (rule 36)."""
    import edgedash.storage as storage

    parts = []
    for task in plan.tasks:
        if task.skipped:
            parts.append(f"{task.agent_name}: skip ({task.reason})")
        elif task.agent_name in results:
            result = results[task.agent_name]
            if isinstance(result, Exception):
                parts.append(f"{task.agent_name}: failed ({result})")
            else:
                parts.append(f"{task.agent_name}: {result.status} ({result.records_touched} records)")
        else:
            parts.append(f"{task.agent_name}: not executed")

    if "verifier" in results:
        vr = results["verifier"]
        if isinstance(vr, Exception):
            parts.append(f"verifier: failed ({vr})")
        else:
            parts.append(f"verifier: {vr.notes}")

    parts.append(f"retry_count={retry_count}")
    notes = " | ".join(parts)

    storage.log_cycle(
        agent="orchestrator",
        started_at=started_at,
        finished_at=storage.utc_now(),
        records_touched=sum(
            r.records_touched for r in results.values()
            if isinstance(r, AgentResult)
        ),
        status=outcome,
        notes=notes[:500],
        verdict=verdict,
        failed_checks=failed_checks,
        retry_count=retry_count,
    )


def _build_registry(config: Any) -> dict[str, Any]:
    """Build the agent registry. Adding a new agent is one line here."""
    if config.use_mock_fetcher:
        from edgedash.agents.mock_fetcher import MockFetcher
        fetcher = MockFetcher()
    else:
        from edgedash.agents.fetcher import Fetcher
        fetcher = Fetcher()

    from edgedash.agents.scorer import Scorer
    from edgedash.agents.gap_analyzer import GapAnalyzer
    from edgedash.agents.verifier import Verifier

    return {
        "fetcher": fetcher,
        "scorer": Scorer(),
        "gap_analyzer": GapAnalyzer(),
        "verifier": Verifier(),
    }
