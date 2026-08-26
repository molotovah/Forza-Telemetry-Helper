"""AI advisor: sends the session summary + rules output to an OpenRouter model
(OpenAI-compatible chat API) and returns a prioritized tuning report.

Settings resolution: defaults <- ~/.fth/config.json <- environment variables.
  FTH_AI_KEY       OpenRouter API key (openrouter.ai/keys) — the only required value
  FTH_AI_URL       endpoint override (default: OpenRouter chat completions)
  FTH_AI_MODEL     model ID (default: stealth/ox-alpha)
  FTH_AI_TIMEOUT   request timeout in seconds (default: 45)
  FTH_AI_REASONING optional reasoning effort for ox-alpha (low/high/max)

Without any key — or if the request fails — the rules-engine output is
returned unchanged (offline fallback). The key/model can also be set from the
dashboard's Settings tab, which writes the same config file.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from fth import config
from fth.ingest import TelemetryPacket
from fth.session import SessionSummary, format_per_lap, format_report, summarize_per_lap
from fth.tuning import format_suggestions, suggest

_DEFAULTS = {
    "url": "https://openrouter.ai/api/v1/chat/completions",
    "model": "stealth/ox-alpha",
    "timeout": "45",
}
_ENV_NAMES = {
    "key": "FTH_AI_KEY",
    "url": "FTH_AI_URL",
    "model": "FTH_AI_MODEL",
    "reasoning": "FTH_AI_REASONING",
    "timeout": "FTH_AI_TIMEOUT",
}

_SYSTEM = (
    "You are a race engineer for Forza Horizon 6. You receive telemetry-derived session "
    "metrics from the game's one-way Data Out stream, plus heuristic suggestions from a "
    "rules engine. Produce a prioritized tuning plan the driver can apply in FH6's "
    "tuning menu.\n"
    "Rules:\n"
    "- Name only parameters that exist in FH6's tuning menu: tire pressure; gearing "
    "(final drive, gear ratios); alignment (camber, toe, caster); anti-roll bars; spring "
    "stiffness; ride height; damping (rebound, bump); aero (front/rear downforce); brake "
    "pressure and balance; differential acceleration/deceleration (AWD also has center).\n"
    "- Every change is RELATIVE: the current setup is unknown. Small, testable steps only.\n"
    "- Order items by expected lap-time impact, biggest first. If the data contradicts a "
    "rule-engine suggestion, drop or correct it and say so in one line.\n"
    "- Match differential advice to the drivetrain type reported in the summary.\n"
    "- Each item: parameter | direction and rough magnitude | one-line reason quoting "
    "the metric that drives it.\n"
    "- Start with one line naming the dominant handling problem you see in the numbers.\n"
    "- If the session is too short or a metric is inconclusive, ask for specific extra "
    "driving instead of guessing.\n"
    "- End with a one-line test protocol to validate the changes (same track/conditions).\n"
    "- Keep the whole reply under ~250 words."
)


def resolve_settings() -> dict[str, str]:
    """defaults <- config file <- environment variables."""
    resolved = dict(_DEFAULTS)
    resolved.update(config.load())
    resolved.update(
        {name: value for name, env in _ENV_NAMES.items() if (value := os.environ.get(env))}
    )
    return resolved


def _chat(settings: dict[str, str], prompt: str) -> str:
    payload: dict = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    # ox-alpha reasons by default at max effort; allow opting down for speed
    if settings.get("reasoning"):
        payload["reasoning_effort"] = settings["reasoning"]
    req = urllib.request.Request(
        settings["url"],
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings['key']}",
            "X-Title": "Forza Telemetry Helper",
        },
    )
    with urllib.request.urlopen(req, timeout=int(settings["timeout"])) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def advise(s: SessionSummary, packets: list[TelemetryPacket] | None = None) -> str:
    """Full tuning report: AI when configured, otherwise the rules engine.

    `packets`, when given, add a per-lap breakdown to the prompt so the model
    sees lap-to-lap evolution, not just aggregates.
    """
    rules = suggest(s)
    fallback = format_suggestions(rules)
    settings = resolve_settings()
    if not settings.get("key"):
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
    prompt += "Turn this into a prioritized tuning plan following your instructions."
    try:
        return _chat(settings, prompt)
    except Exception as exc:  # network/API errors must never lose the rules report
        print(f"fth: AI advisor unavailable ({exc}); using rules engine.", file=sys.stderr)
        return fallback
