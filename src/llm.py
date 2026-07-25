"""Resilient LLM calls: retry on transient server errors, then fall back to a
second provider.

The agent summarizes with Anthropic Claude. A single 5xx (server error) or a
dropped connection used to crash the whole run. `create_message()` is a drop-in
replacement for `anthropic_client.messages.create(...)` that:

  1. retries the primary (Anthropic) on 5xx / connection errors with exponential
     backoff (default 3 attempts: ~3s, 6s, 12s);
  2. if it still fails, falls back to an OpenAI-compatible provider (e.g. the
     local LumaDock/Hermes gateway) when one is configured via env;
  3. returns an object exposing `.content[0].text`, exactly like the Anthropic
     SDK, so call sites don't change how they read the reply.

Config (env):
  CLAUDE_API_KEY_GITHUB_EMAIL / CLAUDE_API_KEY / ANTHROPIC_API_KEY   primary key
  LLM_RETRY_ATTEMPTS       (default 3)
  LLM_RETRY_BASE_DELAY     seconds, default 3  (doubles each retry)
  LLM_FALLBACK_BASE_URL    e.g. http://127.0.0.1:8642/v1  (enables fallback)
  LLM_FALLBACK_API_KEY     bearer token for the fallback
  LLM_FALLBACK_MODEL       e.g. hermes  (default 'hermes')
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

try:
    from anthropic import Anthropic
except ImportError:  # anthropic not installed → primary disabled, fallback only
    Anthropic = None

RETRY_ATTEMPTS = int(os.getenv("LLM_RETRY_ATTEMPTS", "3"))
RETRY_BASE_DELAY = float(os.getenv("LLM_RETRY_BASE_DELAY", "3"))

FALLBACK_BASE_URL = os.getenv("LLM_FALLBACK_BASE_URL", "").rstrip("/")
FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "")
FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "hermes")

_primary = None
if Anthropic is not None:
    _primary = Anthropic(api_key=(
        os.getenv("CLAUDE_API_KEY_GITHUB_EMAIL")
        or os.getenv("CLAUDE_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    ))


class _Block:
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


class _Response:
    """Minimal shim mirroring anthropic's response.content[0].text."""
    def __init__(self, text: str):
        self.content = [_Block(text)]


def _status_of(exc) -> int | None:
    for attr in ("status_code", "status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    return None


def _is_retryable(exc) -> bool:
    """A transient failure worth retrying: 5xx server error or a connection drop."""
    st = _status_of(exc)
    if st is not None and 500 <= st < 600:
        return True
    name = type(exc).__name__.lower()
    return any(k in name for k in (
        "apiconnection", "apitimeout", "remotedisconnected", "connection",
        "timeout", "internalserver", "overloaded", "serviceunavailable",
        "protocol"))


def _log(msg: str) -> None:
    print(f"  [llm] {msg}", file=sys.stderr)


def _fallback(messages, system, max_tokens) -> _Response:
    """Call an OpenAI-compatible endpoint and return the shim response."""
    msgs = ([{"role": "system", "content": system}] if system else []) + list(messages)
    body = json.dumps({"model": FALLBACK_MODEL, "messages": msgs,
                       "max_tokens": max_tokens}).encode("utf-8")
    req = urllib.request.Request(
        FALLBACK_BASE_URL + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {FALLBACK_API_KEY}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    return _Response(d["choices"][0]["message"]["content"])


def create_message(model, max_tokens, messages, system=None, **kwargs):
    """Drop-in for client.messages.create with retry + provider fallback."""
    last = None
    if _primary is not None:
        for attempt in range(RETRY_ATTEMPTS):
            try:
                args = dict(model=model, max_tokens=max_tokens, messages=messages, **kwargs)
                if system is not None:
                    args["system"] = system
                return _primary.messages.create(**args)
            except Exception as exc:  # noqa: BLE001 — classify below
                last = exc
                if attempt < RETRY_ATTEMPTS - 1 and _is_retryable(exc):
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    _log(f"primary failed ({type(exc).__name__}), retry in {delay:.0f}s")
                    time.sleep(delay)
                    continue
                break  # non-retryable, or out of attempts

    if FALLBACK_BASE_URL and FALLBACK_API_KEY:
        _log(f"primary exhausted → fallback provider ({FALLBACK_MODEL})")
        try:
            return _fallback(messages, system, max_tokens)
        except Exception as exc:  # noqa: BLE001
            last = exc
            _log(f"fallback also failed ({type(exc).__name__})")

    raise last if last is not None else RuntimeError("no LLM provider available")
