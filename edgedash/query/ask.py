"""
ask.py — Two-call natural language query pipeline (steering rules 42-45).

NO TEXT-TO-SQL. The model routes to a fixed registry, never composes a query.

Public API
----------
ask(question: str) -> Answer
  Answer a natural language question about job listings data.

Answer: namedtuple with text, rows, tool_used, params.
"""
from __future__ import annotations

import json
import time
from collections import namedtuple
from dataclasses import dataclass
from typing import Any

from edgedash import llm, storage
from edgedash.config import load_config
from edgedash.query.tools import TOOLS


Answer = namedtuple("Answer", ["text", "rows", "tool_used", "params"])


# ---------------------------------------------------------------------------
# Routing prompt (rule 42, first call)
# ---------------------------------------------------------------------------

def _build_routing_prompt(question: str) -> str:
    """Build the routing prompt that selects a tool and parameters.
    
    Per rule 40: NO text-to-SQL. The model selects from a fixed registry.
    Per rule 45: Explicitly instruct NOT to guess the closest tool.
    """
    # Build tool registry for the prompt
    tools_desc = []
    for name, spec in TOOLS.items():
        param_lines = []
        for param_name, param_spec in spec.parameters.items():
            ptype = param_spec.get("type", "any")
            default = param_spec.get("default", "required")
            desc = param_spec.get("description", "")
            param_lines.append(f"      - {param_name} ({ptype}, default={default}): {desc}")
        
        params_text = "\n".join(param_lines) if param_lines else "      (no parameters)"
        tools_desc.append(f"  - {name}: {spec.description}\n    Parameters:\n{params_text}")
    
    tools_list = "\n\n".join(tools_desc)
    
    return f"""You are a query router for a job listings database.

Your task: select the ONE tool that matches this question, or return null if none match.

CRITICAL RULES:
- Do NOT guess at the closest tool. If no tool is a clear match, return null.
- Do NOT invent tools. Only choose from the registry below.
- Do NOT compose SQL or generate queries. You only route to pre-built tools.
- If the question asks for something none of these tools provide, return null.

Available tools:

{tools_list}

Question: "{question}"

Return JSON with this EXACT structure:
{{
  "tool": "<tool_name>" or null,
  "params": {{"param_name": value, ...}},
  "confidence": "high" or "low"
}}

If tool is null, set params to {{}}.
If a parameter has a default, you may omit it from params.

Examples:
- "Which companies are hiring?" → {{"tool": "companies_hiring", "params": {{}}, "confidence": "high"}}
- "Top 10 jobs" → {{"tool": "best_matches", "params": {{"n": 10}}, "confidence": "high"}}
- "What is the weather?" → {{"tool": null, "params": {{}}, "confidence": "high"}}
"""


# ---------------------------------------------------------------------------
# Phrasing prompt (rule 42, second call)
# ---------------------------------------------------------------------------

def _build_phrasing_prompt(question: str, rows: list[dict], summary: str) -> str:
    """Build the phrasing prompt that turns rows into prose.
    
    Per rule 43: Use ONLY numbers present in the rows. No estimation, no
    extrapolation, no outside context. If rows are empty, say so plainly.
    """
    rows_json = json.dumps(rows, indent=2)
    
    return f"""You are writing a brief answer to a question about job listings data.

Question: "{question}"

Data summary: {summary}

Data rows:
{rows_json}

CRITICAL RULES:
- Use ONLY the numbers and values present in these rows.
- Do NOT estimate, extrapolate, or add outside context.
- Do NOT infer values that are not in the data.
- If the rows are empty, say plainly that the data does not contain an answer.
- Write 2-3 sentences maximum.
- Include what you looked at (e.g., "across 47 listings from the last 7 days").

Return JSON with this EXACT structure:
{{
  "answer": "<your 2-3 sentence answer here>"
}}
"""


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def ask(question: str, config: Any = None) -> Answer:
    """Answer a natural language question using the two-call pipeline.
    
    Per rule 42: Model appears exactly twice:
      1. ROUTE — pick a tool and params
      2. PHRASE — turn returned rows into prose
    
    Per rule 44: Return both text and rows for transparency.
    Per rule 45: If no tool matches, list what CAN be asked.
    """
    if config is None:
        config = load_config()
    
    start_time = time.time()
    
    # Step 1: ROUTE (first LLM call)
    routing_prompt = _build_routing_prompt(question)
    
    routing_schema = {
        "type": "object",
        "properties": {
            "tool": {"type": ["string", "null"]},
            "params": {"type": "object"},
            "confidence": {"type": "string", "enum": ["high", "low"]},
        },
        "required": ["tool", "params", "confidence"],
    }
    
    try:
        route_response = llm.complete_json(
            prompt=routing_prompt,
            schema=routing_schema,
        )
    except Exception as e:
        # Log and return error
        _log_query(question, None, {}, False, time.time() - start_time, error=str(e))
        return Answer(
            text=f"Error routing question: {e}",
            rows=[],
            tool_used=None,
            params={},
        )
    
    tool_name = route_response.get("tool")
    params = route_response.get("params", {})
    confidence = route_response.get("confidence", "unknown")
    
    # If tool is null, return "cannot answer" with available tools list
    if tool_name is None:
        _log_query(question, None, {}, False, time.time() - start_time)
        available_tools = "\n".join(
            f"- {spec.description}" for spec in TOOLS.values()
        )
        return Answer(
            text=(
                f"I cannot answer that question with the available data tools.\n\n"
                f"I can answer questions like:\n{available_tools}"
            ),
            rows=[],
            tool_used=None,
            params={},
        )
    
    # Validate tool name is in registry
    if tool_name not in TOOLS:
        _log_query(question, tool_name, params, False, time.time() - start_time, error="Invalid tool")
        return Answer(
            text=f"Error: Model returned invalid tool '{tool_name}'. Available tools: {', '.join(TOOLS.keys())}",
            rows=[],
            tool_used=tool_name,
            params=params,
        )
    
    # Step 2: EXECUTE (call the tool)
    tool_spec = TOOLS[tool_name]
    
    try:
        # Call the tool function with params
        # Pass config for tools that need it (gap_detail, skill_demand)
        if tool_name in ("gap_detail", "skill_demand"):
            result = tool_spec.fn(config=config, **params)
        else:
            result = tool_spec.fn(**params)
    except Exception as e:
        _log_query(question, tool_name, params, False, time.time() - start_time, error=str(e))
        return Answer(
            text=f"Error executing tool '{tool_name}': {e}",
            rows=[],
            tool_used=tool_name,
            params=params,
        )
    
    # Step 3: PHRASE (second LLM call)
    phrasing_prompt = _build_phrasing_prompt(question, result.rows, result.summary)
    
    phrasing_schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
        },
        "required": ["answer"],
    }
    
    try:
        phrase_response = llm.complete_json(
            prompt=phrasing_prompt,
            schema=phrasing_schema,
        )
        answer_text = phrase_response.get("answer", "No answer generated.")
    except Exception as e:
        # If phrasing fails, fall back to summary
        answer_text = f"{result.summary}. (Phrasing error: {e})"
    
    duration = time.time() - start_time
    _log_query(question, tool_name, params, True, duration)
    
    return Answer(
        text=answer_text,
        rows=result.rows,
        tool_used=tool_name,
        params=params,
    )


# ---------------------------------------------------------------------------
# Query logging (rule 5 from original ask — should be rule 47)
# ---------------------------------------------------------------------------

def _log_query(
    question: str,
    tool: str | None,
    params: dict,
    answerable: bool,
    duration: float,
    error: str | None = None,
) -> None:
    """Log every question to query_log table."""
    with storage._connection() as conn:
        # Ensure table exists (for both SQLite and Postgres)
        if storage._backend == "postgres":
            # For Postgres, try to create with BOOLEAN type
            # If table already exists with INTEGER, this will fail silently
            try:
                storage._execute(conn, """
                    CREATE TABLE IF NOT EXISTS query_log (
                        id          SERIAL PRIMARY KEY,
                        asked_at    TIMESTAMP NOT NULL,
                        question    TEXT NOT NULL,
                        tool        TEXT,
                        params      TEXT,
                        answerable  BOOLEAN NOT NULL,
                        duration_ms INTEGER NOT NULL,
                        error       TEXT
                    )
                """)
            except Exception as e:
                # Table might already exist with different schema
                # Try to check and migrate if needed
                logger.warning(f"query_log table creation/check failed: {e}")
        else:
            storage._execute(conn, """
                CREATE TABLE IF NOT EXISTS query_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    asked_at    TEXT NOT NULL,
                    question    TEXT NOT NULL,
                    tool        TEXT,
                    params      TEXT,
                    answerable  INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    error       TEXT
                )
            """)
        
        # Convert answerable to appropriate type for each backend
        if storage._backend == "postgres":
            answerable_value = answerable  # Postgres accepts boolean directly
        else:
            answerable_value = 1 if answerable else 0  # SQLite uses integers
        
        storage._execute(
            conn,
            """
            INSERT INTO query_log (asked_at, question, tool, params, answerable, duration_ms, error)
            VALUES (:asked_at, :question, :tool, :params, :answerable, :duration_ms, :error)
            """,
            {
                "asked_at": storage.utc_now(),
                "question": question,
                "tool": tool,
                "params": json.dumps(params),
                "answerable": answerable_value,
                "duration_ms": int(duration * 1000),
                "error": error,
            },
        )
