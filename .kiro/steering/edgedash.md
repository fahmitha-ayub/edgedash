# EdgeDash — Project Steering Rules

## Project Overview

EdgeDash is an autonomous AI career intelligence agent. It runs on a schedule,
fetches live job listings, scores them for fit against a user profile, surfaces
skill gaps, verifies its own output, and publishes a Streamlit dashboard.

## Architecture

```
Trigger (scheduled)
  -> Orchestrator
       -> Fetcher        (fetches live job listings)
       -> Scorer         (scores listings for fit)
       -> GapAnalyzer    (identifies skill gaps)
  -> Verifier            (verifies output correctness)
  -> Storage             (persists all results)
  -> Dashboard           (read-only Streamlit view)
```

**Do not deviate from this architecture without informing the user first.**

- The Orchestrator reads state and delegates work. It never fetches or scores directly.
- Each sub-agent has exactly one goal and one stop condition.
- The Dashboard is strictly read-only — it never writes to storage.

## Hard Rules

### 1. Python Version and Dependencies
- Python 3.11+ only.
- Prefer the standard library. Add a third-party dependency only when it
  genuinely saves real work. Before adding any dependency, state what it is,
  why it is needed, and what the alternative would cost.

### 2. Storage Access
- ALL storage access must go through a single `storage` module with a thin interface.
- No other module may import `sqlite3` directly.
- The storage module must be designed so that swapping SQLite for hosted Postgres
  in week 4 is a one-file change — nothing outside `storage` should know which
  backend is in use.

### 3. No Hardcoded User Data
- Never hardcode role, city, keywords, skills profile, or any other user-specific
  value in code.
- Everything user-specific lives in `config` (a config file or config module loaded
  at startup).

### 4. No Secrets in Code
- No API keys, tokens, passwords, or credentials in source files.
- Secrets are loaded from environment variables only, in one place (e.g., a
  dedicated `env.py` or the top of `config.py`).

### 5. Cycle Logging
- Every agent run must write a row to a `cycle_log` table.
- Required columns: what ran, when it ran, how many records were touched,
  pass/fail status, and any retry reason.

### 6. Fail Loudly
- No bare `except: pass` or silent error suppression.
- If something goes wrong, raise or re-raise with context so it is visible.
- Use specific exception types. Catch only what you intend to handle.

### 7. Type Hints and Docstrings
- Every function signature must have type hints (parameters and return type).
- Docstrings are required only where the intent is not obvious from the name.
  Do not add docstrings that merely restate the function name.

### 8. File Length
- Keep individual files under approximately 150 lines.
- Split a module before it approaches that limit — do not wait until after.

## Network & Sources

### 9. Source Interface
- Every external job source lives behind a `Source` class with a uniform interface.
- The Fetcher never contains source-specific parsing logic.
- Adding a new source must never require editing the Fetcher — only registering
  a new Source class.

### 10. Normalised Output Contract
- Every Source returns a list of dicts with EXACTLY these keys:
  `source`, `external_id`, `title`, `company`, `location`, `url`,
  `description`, `posted_at`, `raw`.
- Missing values are `None`. Never use empty string or `"N/A"` as a sentinel.

### 11. Network Helper
- All network calls go through one shared helper that enforces:
  a 10-second timeout (default), 2 retry attempts with exponential backoff,
  and a `User-Agent` header.
- No bare `requests.get()` anywhere else in the codebase.

### 12. Per-Source Fault Isolation
- A source failing must never kill the cycle.
- Catch failures per-source, log to `cycle_log` with `status="failed"`,
  and continue to the next source.
- One dead job board must not stop the other sources from running.

### 13. Secrets via .env
- API keys and tokens come from environment variables loaded from a `.env`
  file that is gitignored.
- Never a literal key in code; never a key in `config.yaml`.
- If a required key is missing at runtime, that source skips itself and logs
  a clear message — it does not raise an unhandled exception or crash the cycle.

### 14. Rate Limiting and Etiquette
- Rate-limit to at most 1 request per second per source.
- Always set a real, descriptive `User-Agent` header.
- Honour any documented page limits or crawl restrictions for the source.

## Intelligence & Scoring

### 15. LLM Module
- All LLM calls go through one module, `edgedash/llm.py`, exposing one function.
- The provider and model name come from config, never hardcoded.
- Rate limit to stay inside a free tier (default 1 request per second, max 15 per minute).
- No other file imports an LLM SDK.

### 16. Models Extract Facts, Code Computes Scores
- NEVER ask a model for a final score, ranking, or numeric rating.
- The model extracts structured facts only.
- All scoring arithmetic is deterministic Python in ONE function.
- The model never sees the scoring weights.

### 17. Response Validation
- Every model response is validated against an explicit schema before use.
- A response that fails validation is retried once, then logged as a failure for THAT listing only.
- A failed listing must not crash the cycle or stop the remaining listings.
- Never `json.loads` raw model text without a validation and repair path.

### 18. Idempotent Scoring
- Scoring is idempotent. Never re-score a listing that already has a score.
- Select only listings `WHERE score IS NULL`.
- Cache extraction results keyed on a hash of the job description so the same text is never sent to the model twice.

### 19. Human-Readable Reasons
- Every score carries a human-readable reason GENERATED FROM THE SCORE COMPONENTS by our code.
- Never free text written by the model.

### 20. Score Distribution Logging
- Log the score distribution (count, min, max, mean, spread) to `cycle_log` on every scoring run.
- A run where all scores fall within 10 points is a suspect run and must be logged as such.

### 21. Batch Size Cap
- Cap listings scored per cycle at a configurable batch size (default 25).
- A cost or rate-limit blowup is structurally impossible.

## Aggregate Analysis

### 22. Deterministic Aggregates
- Aggregate analysis is deterministic SQL and Python.
- No LLM call may produce, adjust, or rank an aggregate number.
- A model may only SUGGEST canonical groupings for a human to approve.

### 23. Skill Name Canonicalisation
- Skill names are canonicalised through an explicit alias map in `config.yaml` that I own and can read.
- Never auto-merge skill names by model judgement or string similarity alone.

### 24. Gap Ranking by Fit Score
- Gap ranking is weighted by the fit score of the listing the gap came from.
- A gap in a listing I score 20 on is worth far less than a gap in a listing I score 85 on.
- Never rank gaps by raw frequency alone.

### 25. Timestamped Snapshots
- Every gap report run writes a timestamped SNAPSHOT.
- Never overwrite the previous report.
- Trend over time is a first-class output, not an afterthought.

### 26. Traceability
- Every aggregate number must be traceable to the rows that produced it.
- Any reported gap must be able to list the specific listing IDs it was computed from.
- No number appears in the dashboard that I cannot drill into.

### 27. Sample Size Reporting
- Report the sample size alongside every aggregate.
- A gap computed from 3 listings and a gap computed from 90 listings must never be presented as equally reliable.

## Orchestration

### 28. State-Driven Execution
- The Orchestrator reads system state and decides which agents to run.
- It never runs a fixed sequence. Skipping an agent because there is no work for it is a SUCCESSFUL outcome, not a failure.

### 29. Explicit Delegation Contracts
- Every delegation carries an explicit goal and an explicit stop condition (max items, max duration).
- A sub-agent never decides its own limits — the Orchestrator sets them.

### 30. Separation of Concerns
- The Orchestrator never does an agent's work.
- It reads state, delegates, collects results, logs. No fetching, scoring, or analysis logic in the Orchestrator.

### 31. Plan Visibility
- The Orchestrator prints and logs its PLAN before executing it — which agents will run, which are skipped, and the state value that caused each decision.

### 32. Fault Isolation
- One sub-agent failing does not stop the cycle.
- Log the failure, continue with the remaining plan, and mark the cycle partial.

### 33. Cycle Summary
- Every cycle writes exactly one summary row: what ran, what was skipped, why, duration per agent, and the outcome.

## Verification

### 34. Verdict Only, No Repair
- The Verifier judges output plausibility and NEVER repairs, rewrites, or adjusts data.
- It returns a verdict and a reason. The Orchestrator decides what to do about a failure.

### 35. Plausibility, Not Correctness
- Verification checks plausibility, never correctness.
- There is no ground truth for a fit score. Checks assert properties of the output distribution and shape, not the accuracy of any single value.

### 36. Bounded Retries
- A failed verification triggers at most ONE retry of the failing agent with adjusted context.
- After that the cycle is marked "degraded" and stops. Never retry in an unbounded loop.

### 37. Detailed Failure Logging
- Every verdict is logged to cycle_log with the check that failed and the observed value that failed it — never just "failed".

### 38. Known-Good Data Protection
- Only cycles with a passing verdict may be read by the dashboard.
- A failed cycle must never overwrite the last known-good data.
- Stale verified data always beats fresh unverified data.

### 39. Thresholds in Config
- Verification thresholds live in config.yaml, not in code.
- Every threshold has a comment saying what failure it is designed to catch.

## Natural Language Queries

### 40. No Text-to-SQL
- NEVER generate SQL from a model. No text-to-SQL, ever, in any form.
- The model selects from a fixed registry of parameterised query functions that I wrote.
- It never composes a query.

### 41. Read-Only Parameterised Tools
- Every query tool is read-only, parameterised, and takes typed parameters that are validated and clamped to a safe range before execution.
- A model-supplied parameter is untrusted input.

### 42. Two-Call Pattern
- The model appears exactly twice per question: once to ROUTE (pick a tool and its parameters) and once to PHRASE (turn returned rows into prose).
- It never touches the database in either call.

### 43. No Fabrication in Phrasing
- The phrasing call may use ONLY the numbers present in the rows it was given.
- It must not estimate, extrapolate, add outside context, or infer a value that is not in the data.
- If the rows are empty it must say so plainly.

### 44. Data Transparency
- Every answer displays the underlying rows alongside it.
- No prose answer appears without the data that produced it.

### 45. No Guessing
- If no tool matches the question, say so and list what CAN be asked.
- Never guess at the closest tool and never answer from general knowledge.

### 46. Verified Data Only
- Query tools read from the last passing cycle only, per rule 38.

## Deployment

### 47. Ephemeral Filesystems
- Never rely on the local filesystem for anything that must survive a restart.
- Hosting filesystems are ephemeral. All persistent state is in the hosted database.

### 48. Secret Management
- Every secret comes from an environment variable read in one place.
- No secret is ever committed, printed, logged, or shown in an error message or traceback.

### 49. Process Separation
- The scheduled job and the dashboard are separate processes that share only the database.
- The dashboard never runs a cycle; the scheduler never serves a page.

### 50. Graceful Degradation
- The deployed app must start and render even when the database is empty, unreachable, or mid-migration.
- It shows a clear status message instead of a stack trace.
- A stranger must never see a traceback.

### 51. Idempotent Scheduling
- The scheduled job is idempotent and safe to run twice.
- It must have a hard timeout and stay inside free-tier limits.

## Style Guidelines

- Write small, testable functions with a single clear responsibility.
- Prefer plain, readable Python over clever or compact Python.
- When asked to build one module, build that module only. Do not scaffold the
  whole application unless explicitly asked.
