"""AI advisor: sends the session summary + rules output to an OpenAI-compatible
chat API and returns a prioritized tuning report.

Configuration (environment variables):
  FTH_AI_URL    chat-completions endpoint, e.g. https://host/v1/chat/completions
  FTH_AI_KEY    bearer token
  FTH_AI_MODEL  model name (default: ox-alpha)

Without FTH_AI_URL/FTH_AI_KEY — or if the request fails — the rules-engine
output is returned unchanged (offline fallback).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from fth.session import SessionSummary, format_report
from fth.tuning import format_suggestions, suggest

_DEFAULT_MODEL = "ox-alpha"
_TIMEOUT_S = 45

_SYSTEM = (
    "You are an experienced Forza Horizon 6 race engineer. You get telemetry-derived "
    "session metrics plus rule-engine suggestions. Reply with a short prioritized tuning "
    "plan (at most ~10 bullets) naming only parameters that exist in FH6's tuning menu. "
    "Every change is relative to the driver's current setup: state parameter, direction/"
    "magnitude, and the data-backed reason."
)


def _chat(url: str, key: str, model: str, prompt: str) -> str:
    req = urllib.request.Request(
        url,
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
        ).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def advise(s: SessionSummary) -> str:
    """Full tuning report: AI when configured, otherwise the rules engine."""
    rules = suggest(s)
    fallback = format_suggestions(rules)
    url = os.environ.get("FTH_AI_URL", "")
    key = os.environ.get("FTH_AI_KEY", "")
    if not (url and key):
        return fallback

    prompt = (
        "Session telemetry summary:\n"
        f"{format_report(s)}\n\n"
        f"Rule-engine suggestions:\n{fallback}\n\n"
        "Turn this into a prioritized tuning plan."
    )
    try:
        return _chat(url, key, os.environ.get("FTH_AI_MODEL", _DEFAULT_MODEL), prompt)
    except Exception as exc:  # network/API errors must never lose the rules report
        print(f"fth: AI advisor unavailable ({exc}); using rules engine.", file=sys.stderr)
        return fallback
