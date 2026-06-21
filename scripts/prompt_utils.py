#!/usr/bin/env python3
"""Shared prompt + AI helpers for ASG Lead Command Center.

This module is the single dependency for every script that needs to:
  * load a versioned prompt from prompts/<rel_path>
  * render {{key}} template variables into that prompt
  * extract a JSON object from a raw AI response (handles ```json fences and prose)
  * build a provider-agnostic AI request envelope (no secrets embedded)
  * call OpenAI Chat Completions or Anthropic Messages via urllib (stdlib only)

Design notes (business rules that are not obvious from the code):
- Secrets are read from the environment ONLY at call time and placed in HTTP
  headers, never inside the request body that gets logged/serialized.
- call_ai raises AIConfigError when no key is configured so callers can fall
  back to a deterministic local heuristic and set review_needed=True
  (per design spec §0 rule 6 — never silently fake an AI response).
- Module is import-safe with no env vars set (no side effects at import).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


# Repository root = parent of this scripts/ directory. Matches the convention
# used by scripts/generate_outreach.py so prompt loading is consistent.
ROOT = lambda: None  # placeholder, real path computed lazily below (kept for clarity)
import pathlib
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROMPTS_DIR = _REPO_ROOT / "prompts"


# API endpoints (constants, not secrets).
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Default model ids when DEFAULT_MODEL env var is empty. Kept conservative and
# overridable by the operator via env — never hard-coded per call site.
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_ANTHROPIC_DEFAULT_MODEL = "claude-3-5-sonnet-latest"

# Shared system message. The strong wording is load-bearing: models that
# paraphrase enum values or ramble in summary fields break downstream JSON
# parsing/validation, so we force exact enums + concision + no truncation.
_SYSTEM_MESSAGE = (
    "You are a precise assistant for ASG Dropshipping business workflows. "
    "Output ONLY a single valid JSON object — no prose, no markdown code fences. "
    "Use ONLY the exact enum values stated in the schema. "
    "Keep every text field concise (reasoning/summary fields under 40 words). "
    "Never truncate the JSON; close every object and array."
)


def _max_tokens(default: int = 4096) -> int:
    """Max output tokens for Anthropic-style calls; overridable via AI_MAX_TOKENS.

    2048 (the prior hard-coded value) truncated verbose reasoning mid-object and
    produced un-parseable JSON. 4096 is a safer default for structured scoring.
    """
    raw = _env("AI_MAX_TOKENS")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


class AIConfigError(RuntimeError):
    """Raised when AI cannot run because of missing configuration (e.g. no API key)."""


class AIRuntimeError(RuntimeError):
    """Raised when an AI HTTP call fails or returns an unexpected payload."""


def _env(name: str, default: str = "") -> str:
    """Read an environment variable, stripped of surrounding whitespace."""
    return os.getenv(name, default).strip()


def _anthropic_url() -> str:
    """Resolve the Anthropic Messages endpoint URL.

    Defaults to the real Anthropic API, but honors ``ANTHROPIC_BASE_URL`` so an
    Anthropic-compatible gateway can be used instead — e.g. Zhipu GLM at
    ``https://open.bigmodel.cn/api/anthropic``. The env var holds the base;
    ``/v1/messages`` is appended here.
    """
    base = _env("ANTHROPIC_BASE_URL")
    if base:
        return base.rstrip("/") + "/v1/messages"
    return _ANTHROPIC_URL


def load_prompt(rel_path: str) -> str:
    """Read prompts/<rel_path> from the repository root as UTF-8 text.

    rel_path is relative to the prompts/ directory, e.g.
    ``load_prompt("lead-scoring/lead-scoring-v1.md")``.
    Raises FileNotFoundError if the prompt is missing so callers fail loudly
    rather than silently rendering an empty prompt.
    """
    path = _PROMPTS_DIR / rel_path
    if not path.is_file():
        raise FileNotFoundError("prompt not found: %s" % path)
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, variables: Dict[str, Any]) -> str:
    """Replace ``{{key}}`` tokens in template with the matching variable.

    Unknown tokens (no matching key) are left untouched on purpose so missing
    context is visible in the rendered prompt instead of silently blanked.
    Whitespace inside the braces is tolerated: ``{{ key }}`` == ``{{key}}``.
    """
    if not isinstance(variables, dict):
        raise TypeError("variables must be a dict")

    pattern = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")

    def replacer(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key in variables:
            return str(variables[key])
        return match.group(0)

    return pattern.sub(replacer, template)


def extract_json(raw: str) -> Dict[str, Any]:
    """Pull a JSON object out of a raw model response.

    Handles three common shapes:
      1. Pure JSON.
      2. ```json ... ``` fenced block (optionally with leading/trailing prose).
      3. Prose wrapping a bare JSON object (falls back to first ``{...}`` span).
    Raises ValueError if the extracted text is not valid JSON or not a dict.
    """
    if raw is None:
        raise ValueError("AI output is empty")
    text = raw.strip()
    if not text:
        raise ValueError("AI output is empty")

    # Strip a leading ```json / ``` fence block if present.
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    candidate = fence_match.group(1).strip() if fence_match else text

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: carve out the outermost {...} span. Useful when the model
        # emits prose like "Sure! Here is the result: {...}" without a fence.
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("AI output does not contain a JSON object")
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("AI output is not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("AI output must be a JSON object")
    return parsed


def _resolve_provider(provider: str) -> str:
    """Return the effective provider: explicit arg > DEFAULT_AI_PROVIDER > 'openai'."""
    provider = (provider or "").strip()
    if provider:
        return provider.lower()
    return (_env("DEFAULT_AI_PROVIDER", "openai") or "openai").lower()


def _resolve_model(provider: str, model: str) -> str:
    """Return the effective model: explicit arg > DEFAULT_MODEL > provider default."""
    model = (model or "").strip()
    if model:
        return model
    env_model = _env("DEFAULT_MODEL")
    if env_model:
        return env_model
    if provider == "anthropic":
        return _ANTHROPIC_DEFAULT_MODEL
    return _OPENAI_DEFAULT_MODEL


def has_ai_key() -> bool:
    """True iff an OpenAI or Anthropic API key is configured in the environment."""
    return bool(_env("OPENAI_API_KEY")) or bool(_env("ANTHROPIC_API_KEY"))


def build_ai_envelope(prompt: str, provider: str = "", model: str = "") -> Dict[str, Any]:
    """Build a provider-specific request body dict.

    No secrets are embedded in the body — the API key is applied as a header
    at call time inside call_ai. This keeps the envelope safe to log/inspect.

    - openai    -> OpenAI Chat Completions body (messages + model).
    - anthropic -> Anthropic Messages body (system + messages + model + max_tokens).
    """
    effective_provider = _resolve_provider(provider)
    effective_model = _resolve_model(effective_provider, model)

    if effective_provider == "anthropic":
        return {
            "model": effective_model,
            "system": _SYSTEM_MESSAGE,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _max_tokens(),
        }
    # Default: OpenAI Chat Completions shape.
    return {
        "model": effective_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }


def _post_json(
    url: str,
    body: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    """POST JSON via urllib and return the decoded JSON response dict."""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best-effort error body
            detail = ""
        raise AIRuntimeError(
            "AI HTTP %s from %s: %s" % (exc.code, url, detail.strip() or exc.reason)
        ) from exc
    except urllib.error.URLError as exc:
        raise AIRuntimeError("AI network error contacting %s: %s" % (url, exc.reason)) from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIRuntimeError("AI response was not valid JSON") from exc


def _extract_openai_text(payload: Dict[str, Any]) -> str:
    try:
        choices = payload["choices"]
    except (KeyError, TypeError) as exc:
        raise AIRuntimeError("OpenAI response missing choices") from exc
    if not choices:
        raise AIRuntimeError("OpenAI response had no choices")
    first = choices[0]
    try:
        return str(first["message"]["content"])
    except (KeyError, TypeError) as exc:
        raise AIRuntimeError("OpenAI response missing message content") from exc


def _extract_anthropic_text(payload: Dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list) or not content:
        raise AIRuntimeError("Anthropic response missing content blocks")
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            value = block.get("text", "")
            if value:
                parts.append(str(value))
    if not parts:
        raise AIRuntimeError("Anthropic response had no text blocks")
    return "".join(parts)


def call_ai(
    prompt: str,
    provider: str = "",
    model: str = "",
    timeout: float = 60.0,
) -> str:
    """Call the configured AI provider and return the raw text content.

    Resolution order for provider/model:
      provider: explicit arg > DEFAULT_AI_PROVIDER (default 'openai')
      model:    explicit arg > DEFAULT_MODEL > provider default

    Provider/key selection:
      - provider == 'openai'    -> requires OPENAI_API_KEY
      - provider == 'anthropic' -> requires ANTHROPIC_API_KEY
      - provider == ''          -> auto-pick the provider whose key is set
        (OpenAI preferred when both are present, mirroring the DEFAULT_AI_PROVIDER
        default of 'openai').

    Raises:
      AIConfigError  - no API key configured for the resolved provider.
      AIRuntimeError - HTTP failure, network error, or malformed response.
    """
    effective_provider = _resolve_provider(provider)
    effective_model = _resolve_model(effective_provider, model)
    envelope = build_ai_envelope(prompt, provider=effective_provider, model=effective_model)

    openai_key = _env("OPENAI_API_KEY")
    anthropic_key = _env("ANTHROPIC_API_KEY")

    # Decide which provider to actually call.
    use_provider: Optional[str]
    if effective_provider == "openai":
        use_provider = "openai" if openai_key else None
    elif effective_provider == "anthropic":
        use_provider = "anthropic" if anthropic_key else None
    else:
        # Unknown provider string: fall back to whichever key exists.
        if openai_key:
            use_provider = "openai"
        elif anthropic_key:
            use_provider = "anthropic"
        else:
            use_provider = None

    if use_provider is None:
        # Per spec §0 rule 6: never fake an AI call. Surface a config error so
        # the caller can switch to a local heuristic with review_needed=True.
        raise AIConfigError("no AI API key configured")

    if use_provider == "openai":
        headers = {
            "Authorization": "Bearer %s" % openai_key,
            "Content-Type": "application/json",
        }
        # Rebuild envelope against the resolved provider/model in case auto-pick
        # switched from anthropic->openai.
        envelope = build_ai_envelope(prompt, provider="openai", model=effective_model)
        payload = _post_json(_OPENAI_URL, envelope, headers, timeout)
        return _extract_openai_text(payload)

    # use_provider == "anthropic"
    headers = {
        "x-api-key": anthropic_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    envelope = build_ai_envelope(prompt, provider="anthropic", model=effective_model)
    payload = _post_json(_anthropic_url(), envelope, headers, timeout)
    return _extract_anthropic_text(payload)


# --- Self-test --------------------------------------------------------------
# Run with: python3 -m scripts.prompt_utils  (or python3 scripts/prompt_utils.py)
# Verifies extract_json handles ```json fences and that render_prompt substitutes.
def _self_test() -> int:
    assert extract_json("```json\n{\"a\":1}\n```") == {"a": 1}, "extract_json fence failed"
    assert extract_json("  {\"a\":1}  ") == {"a": 1}, "extract_json bare failed"
    assert extract_json("Here you go:\n```json\n{\"b\":2}\n```\nThanks!") == {"b": 2}, "extract_json prose+fence failed"
    assert extract_json("Result: {\"c\": 3} end") == {"c": 3}, "extract_json prose+brace failed"
    rendered = render_prompt("Hello {{name}}, score {{score}} vs {{missing}}", {"name": "ASG", "score": 10})
    assert rendered == "Hello ASG, score 10 vs {{missing}}", "render_prompt failed: %r" % rendered
    assert isinstance(build_ai_envelope("p", provider="openai", model="gpt-4o-mini"), dict)
    assert isinstance(build_ai_envelope("p", provider="anthropic", model="claude-3-5-sonnet-latest"), dict)
    print("prompt_utils self-test OK")
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(_self_test())
