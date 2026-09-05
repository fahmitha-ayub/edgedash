"""
llm.py — Single interface to any language model (steering rule 15).

Public API
----------
complete_json(prompt: str, schema: dict, *, max_retries: int = 1) -> dict

Enforces:
  - Provider and model from config, never hardcoded
  - Rate limiting: minimum 1 second between calls, max 15 calls per minute
  - Response validation against schema before returning
  - Retry once on validation failure with error feedback
  - Strip markdown fences and prose before parsing
  - Exponential backoff on 429 / quota errors (3 attempts)
  - Clear LLMError on all terminal failures

Supported providers:
  - "gemini": google-generativeai (requires GEMINI_API_KEY in .env)
  - "ollama": local HTTP (no key required)

Dependency: google-generativeai (third-party, justified: Gemini is the free
tier target and the official SDK handles auth, retries, and safety filters).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when an LLM call fails after all retry attempts."""


# ---------------------------------------------------------------------------
# Rate limiting state
# ---------------------------------------------------------------------------

_last_call_time: float = 0.0
_call_timestamps: deque[float] = deque(maxlen=15)
_MIN_INTERVAL = 1.0  # seconds between calls
_MAX_PER_MINUTE = 15


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def complete_json(
    prompt: str,
    schema: dict,
    *,
    max_retries: int = 1,
) -> dict:
    """Send prompt to LLM, parse JSON response, validate against schema.

    Returns the validated dict. Raises LLMError on terminal failure.
    """
    from edgedash.config import load_config
    config = load_config()

    provider_name = config.llm_provider
    model_name = config.llm_model

    provider = _get_provider(provider_name, model_name)

    for attempt in range(1 + max_retries):
        _rate_limit()

        if attempt == 0:
            full_prompt = prompt + "\n\nRespond with valid JSON only, no prose."
        else:
            full_prompt = (
                prompt
                + f"\n\nYour previous response failed validation. "
                f"Respond with valid JSON only, no prose, no markdown fence."
            )

        try:
            raw_response = provider.call(full_prompt)
        except Exception as exc:
            if attempt < max_retries:
                continue
            raise LLMError(f"Provider call failed: {exc}") from exc

        cleaned = _strip_fences_and_prose(raw_response)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            if attempt < max_retries:
                continue
            raise LLMError(
                f"JSON decode failed after {1 + max_retries} attempts: {exc}"
            ) from exc

        validation_error = _validate_schema(parsed, schema)
        if validation_error is None:
            return parsed

        if attempt < max_retries:
            continue

        raise LLMError(
            f"Schema validation failed after {1 + max_retries} attempts: {validation_error}"
        )

    raise LLMError("Unreachable: retry loop exhausted without raising")


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

class _Provider:
    def call(self, prompt: str) -> str:
        raise NotImplementedError


class _GeminiProvider(_Provider):
    def __init__(self, model_name: str) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError(
                "GEMINI_API_KEY not found in environment. "
                "Add it to your .env file at the project root."
            )

        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise LLMError(
                "google-generativeai not installed. Run: pip install google-generativeai"
            ) from exc

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)

    def call(self, prompt: str) -> str:
        import google.generativeai as genai

        for attempt in range(3):
            try:
                response = self._model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"},
                )
                return response.text

            except Exception as exc:
                error_str = str(exc).lower()
                if "429" in error_str or "quota" in error_str or "resource_exhausted" in error_str:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                raise LLMError(f"Gemini API error: {exc}") from exc

        raise LLMError("Gemini: quota exhausted after 3 retries")


class _OllamaProvider(_Provider):
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def call(self, prompt: str) -> str:
        import requests

        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")

            except requests.exceptions.HTTPError as exc:
                if exc.response and exc.response.status_code == 429:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                raise LLMError(f"Ollama HTTP error: {exc}") from exc

            except requests.exceptions.RequestException as exc:
                raise LLMError(f"Ollama request failed: {exc}") from exc

        raise LLMError("Ollama: rate limited after 3 retries")


def _get_provider(provider_name: str, model_name: str) -> _Provider:
    if provider_name == "gemini":
        return _GeminiProvider(model_name)
    elif provider_name == "ollama":
        return _OllamaProvider(model_name)
    else:
        raise LLMError(
            f"Unknown llm_provider '{provider_name}'. "
            f"Supported: 'gemini', 'ollama'."
        )


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def _rate_limit() -> None:
    """Enforce minimum 1s between calls and max 15 calls per minute."""
    global _last_call_time

    now = time.time()

    # Minimum interval
    elapsed = now - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
        now = time.time()

    # Rolling window: remove calls older than 60s
    cutoff = now - 60.0
    while _call_timestamps and _call_timestamps[0] < cutoff:
        _call_timestamps.popleft()

    # If at capacity, sleep until the oldest call falls out of the window
    if len(_call_timestamps) >= _MAX_PER_MINUTE:
        wait = 60.0 - (now - _call_timestamps[0])
        if wait > 0:
            time.sleep(wait)
            now = time.time()

    _call_timestamps.append(now)
    _last_call_time = now


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _strip_fences_and_prose(text: str) -> str:
    """Remove markdown code fences and leading/trailing prose."""
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)

    # Find JSON object or array bounds
    start = min(
        (text.find(c) for c in ["{", "["] if text.find(c) != -1),
        default=0,
    )
    end = max(
        (text.rfind(c) for c in ["}", "]"] if text.rfind(c) != -1),
        default=len(text) - 1,
    )

    return text[start : end + 1].strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_schema(data: Any, schema: dict) -> str | None:
    """Return None if valid, else a string describing the error."""
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    if not isinstance(data, dict):
        return f"Expected dict, got {type(data).__name__}"

    for key in required:
        if key not in data:
            return f"Missing required key: '{key}'"

    for key, value in data.items():
        if key not in properties:
            continue
        expected_type = properties[key].get("type")
        if expected_type == "string" and not isinstance(value, str):
            return f"'{key}' must be string, got {type(value).__name__}"
        if expected_type == "number" and not isinstance(value, (int, float)):
            return f"'{key}' must be number, got {type(value).__name__}"
        if expected_type == "array" and not isinstance(value, list):
            return f"'{key}' must be array, got {type(value).__name__}"

    return None


# ---------------------------------------------------------------------------
# CLI check
# ---------------------------------------------------------------------------

def _check() -> None:
    """CLI command: python -m edgedash.llm --check"""
    from edgedash.config import load_config

    try:
        config = load_config()
    except Exception as exc:
        print(f"❌ Config load failed: {exc}")
        return

    provider_name = config.llm_provider
    model_name = config.llm_model

    print(f"Provider: {provider_name}")
    print(f"Model:    {model_name}")

    schema = {
        "type": "object",
        "required": ["status"],
        "properties": {"status": {"type": "string"}},
    }

    try:
        result = complete_json(
            "Respond with a JSON object containing one key 'status' set to 'ok'.",
            schema=schema,
            max_retries=1,
        )
        if result.get("status") == "ok":
            print("✓ LLM check passed")
        else:
            print(f"⚠ Unexpected response: {result}")

    except LLMError as exc:
        print(f"❌ LLM check failed: {exc}")
    except Exception as exc:
        print(f"❌ Unexpected error: {exc}")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _check()
    else:
        print("Usage: python -m edgedash.llm --check")
