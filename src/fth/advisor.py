"""AI advisor: sends the session summary + rules output to an OpenAI-compatible
chat API and returns a prioritized tuning report.

Configuration (environment variables):
  FTH_AI_URL      chat-completions endpoint, e.g. https://host/v1/chat/completions
  FTH_AI_KEY      bearer token
  FTH_AI_MODEL    model name (default: ox-alpha)
  FTH_AI_TIMEOUT  request timeout in seconds (default: 45)

Without FTH_AI_URL/FTH_AI_KEY — or if the request fails — the rules-engine
output is returned unchanged (offline fallback).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from fth.ingest import TelemetryPacket
from fth.session import SessionSummary, format_per_lap, format_report, summarize_per_lap
from fth.tuning import format_suggestions, suggest

_DEFAULT_MODEL = "ox-alpha"
_DEFAULT_TIMEOUT_S = 45

_SYSTEM = (
    "You are an experienced Forza Horizon 6 race engineer. You get telemetry-derived "
    "session metrics plus rule-engine suggestions. Reply with a short prioritized tuning "
    "plan (at most ~10 bullets) naming only parameters that exist in FH6's tuning menu. "
    "Every change is relative to the driver's current setup: state parameter, direction/"
    "magnitude, and the data-backed reason."
)


def _chat(url: str, key: str, model: str, prompt: str, timeout: int) -> str:
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def advise(s: SessionSummary, packets: list[TelemetryPacket] | None = None) -> str:
    """Full tuning report: AI when configured, otherwise the rules engine.

    `packets`, when given, add a per-lap breakdown to the prompt so the model
    sees lap-to-lap evolution, not just aggregates.
    """
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
    )
    if packets is not None:
        per_lap = format_per_lap(summarize_per_lap(packets))
        if per_lap:
            prompt += f"{per_lap}\n\n"
    prompt += "Turn this into a prioritized tuning plan."
    try:
        model = os.environ.get("FTH_AI_MODEL", _DEFAULT_MODEL)
        timeout = int(os.environ.get("FTH_AI_TIMEOUT", _DEFAULT_TIMEOUT_S))
        return _chat(url, key, model, prompt, timeout)
    except Exception as exc:  # network/API errors must never lose the rules report
        print(f"fth: AI advisor unavailable ({exc}); using rules engine.", file=sys.stderr)
        return fallback
