"""AI advisor: sends the session summary + rules output to a configured model
(OpenAI-compatible chat API) and returns a prioritized tuning report.

Settings resolution: provider defaults <- ~/.fth/config.json <- environment
variables.
  FTH_AI_PROVIDER  "openrouter" (default) or "groq"
  FTH_AI_KEY       provider API key — the only required value
  FTH_AI_URL       endpoint override (default: the provider's chat endpoint)
  FTH_AI_MODEL     model ID (default: the provider's default model)
  FTH_AI_TIMEOUT   request timeout in seconds (default: 45)
  FTH_AI_REASONING optional reasoning effort (low/high/max); OpenRouter only

Without any key — or if the request fails — the rules-engine output is
returned unchanged (offline fallback). Provider/key/model can also be set
from the dashboard's Settings tab, which writes the same config file.
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

_PROVIDERS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models_url": "https://openrouter.ai/api/v1/models",
        "default_model": "stealth/ox-alpha",
        "supports_reasoning_effort": True,
        "requires_key_for_models": False,  # public, unauthenticated listing
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models_url": "https://api.groq.com/openai/v1/models",
        "default_model": "openai/gpt-oss-120b",
        "supports_reasoning_effort": False,
        "requires_key_for_models": True,
    },
}
_DEFAULT_PROVIDER = "openrouter"
_ENV_NAMES = {
    "key": "FTH_AI_KEY",
    "url": "FTH_AI_URL",
    "model": "FTH_AI_MODEL",
    "reasoning": "FTH_AI_REASONING",
    "timeout": "FTH_AI_TIMEOUT",
    "provider": "FTH_AI_PROVIDER",
}

_SYSTEM_EN = (
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
    "- Tire pressure changes are in psi.\n"
    "- Order items by expected lap-time impact, biggest first. If the data contradicts a "
    "rule-engine suggestion, drop or correct it and say so in one line.\n"
    "- Match differential advice to the drivetrain type reported in the summary.\n"
    "- Each item: parameter | direction and rough magnitude | one-line reason quoting "
    "the metric that drives it.\n"
    "- Start with one line naming the dominant handling problem you see in the numbers.\n"
    "- If the session is too short or a metric is inconclusive, ask for specific extra "
    "driving instead of guessing.\n"
    "- End with a one-line test protocol to validate the changes (same track/conditions).\n"
    "- Keep the whole reply under ~250 words.\n"
    "- Write the entire reply in English: headings, bullet points and reasons."
)

_SYSTEM_FR = (
    "Tu es un ingénieur de course pour Forza Horizon 6. Tu reçois des métriques de "
    'session dérivées de la télémétrie du flux "Data Out" à sens unique du jeu, plus des '
    "suggestions heuristiques d'un moteur de règles. Produis un plan de réglage priorisé "
    "que le pilote peut appliquer dans le menu de réglage de FH6.\n"
    "Règles :\n"
    "- Ne nomme que des paramètres qui existent dans le menu de réglage de FH6 : pression "
    "des pneus ; transmission (rapport de pont, rapports de boîte) ; géométrie (carrossage, "
    "pincement, chasse) ; barres anti-roulis ; raideur des ressorts ; garde au sol ; "
    "amortissement (détente, compression) ; aérodynamique (appui avant/arrière) ; pression "
    "et répartition de freinage ; différentiel accélération/décélération (AWD a aussi un "
    "différentiel central).\n"
    "- Chaque changement est RELATIF : le réglage actuel est inconnu. Uniquement des pas "
    "petits et testables.\n"
    "- Les changements de pression des pneus sont en bar, jamais en psi — c'est le système "
    "métrique.\n"
    "- Classe les éléments par impact attendu sur le temps au tour, le plus grand d'abord. "
    "Si les données contredisent une suggestion du moteur de règles, corrige-la ou "
    "supprime-la et dis-le en une ligne.\n"
    "- Adapte les conseils de différentiel au type de transmission indiqué dans le résumé.\n"
    "- Chaque élément : paramètre | direction et ordre de grandeur | raison en une ligne "
    "citant la métrique qui la justifie.\n"
    "- Commence par une ligne nommant le problème de comportement dominant visible dans "
    "les chiffres.\n"
    "- Si la session est trop courte ou qu'une métrique n'est pas concluante, demande de "
    "la conduite supplémentaire précise plutôt que de deviner.\n"
    "- Termine par un protocole de test en une ligne pour valider les changements (même "
    "piste/conditions).\n"
    "- Garde la réponse entière sous ~250 mots.\n"
    "- Écris toute la réponse en français : titres, puces et raisons. N'écris rien en "
    "anglais."
)


def resolve_settings() -> dict[str, str]:
    """provider defaults <- config file <- environment variables."""
    stored = config.load()
    provider = os.environ.get("FTH_AI_PROVIDER") or stored.get("provider", _DEFAULT_PROVIDER)
    conf = _PROVIDERS.get(provider, _PROVIDERS[_DEFAULT_PROVIDER])
    resolved = {
        "timeout": "45",
        "provider": provider,
        "url": conf["url"],
        "model": conf["default_model"],
    }
    resolved.update(stored)
    resolved.update(
        {name: value for name, env in _ENV_NAMES.items() if (value := os.environ.get(env))}
    )
    resolved["provider"] = provider
    return resolved


_REASONING_HINTS = (
    "r1",
    "reasoner",
    "reasoning",
    "qwq",
    "o1",
    "o3",
    "think",
    "gpt-oss",
    "deepseek",
)


def _normalize_model(provider: str, m: dict) -> dict:
    model_id = m["id"]
    lower = model_id.lower()
    if provider == "groq":
        free = True
    else:
        free = model_id.endswith(":free") or m.get("pricing", {}).get("prompt") == "0"
    return {
        "id": model_id,
        "name": m.get("name", model_id),
        "free": free,
        "reasoning": any(hint in lower for hint in _REASONING_HINTS),
    }


def list_models(settings: dict[str, str] | None = None) -> list[dict]:
    """[{"id", "name", "free", "reasoning"}, ...] for the configured provider.

    Sorted by id. Empty on any network/parse error or a missing key when the
    provider requires one for listing (Groq) — the caller renders "unavailable".
    """
    settings = settings or resolve_settings()
    provider = settings.get("provider", _DEFAULT_PROVIDER)
    conf = _PROVIDERS.get(provider, _PROVIDERS[_DEFAULT_PROVIDER])
    if conf["requires_key_for_models"] and not settings.get("key"):
        return []
    headers = (
        {"Authorization": f"Bearer {settings['key']}"} if conf["requires_key_for_models"] else {}
    )
    req = urllib.request.Request(conf["models_url"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=int(settings.get("timeout", "45"))) as resp:
            raw = json.load(resp)["data"]
    except Exception as exc:
        print(f"fth: model list unavailable ({exc})", file=sys.stderr)
        return []
    return sorted((_normalize_model(provider, m) for m in raw), key=lambda m: m["id"])


def _chat(settings: dict[str, str], prompt: str) -> str:
    system_text = _SYSTEM_FR if settings.get("lang") == "fr" else _SYSTEM_EN
    provider = settings.get("provider", _DEFAULT_PROVIDER)
    conf = _PROVIDERS.get(provider, _PROVIDERS[_DEFAULT_PROVIDER])
    payload: dict = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    # ox-alpha reasons by default at max effort; allow opting down for speed
    if settings.get("reasoning") and conf["supports_reasoning_effort"]:
        payload["reasoning_effort"] = settings["reasoning"]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings['key']}",
    }
    if provider == "openrouter":
        headers["X-Title"] = "Forza Telemetry Helper"
    req = urllib.request.Request(
        settings["url"], data=json.dumps(payload).encode(), headers=headers
    )
    with urllib.request.urlopen(req, timeout=int(settings["timeout"])) as resp:
        data = json.load(resp)
    if "choices" not in data:
        err = data.get("error", data)
        msg = err.get("message", err) if isinstance(err, dict) else err
        raise RuntimeError(f"API error: {msg}")
    return data["choices"][0]["message"]["content"]


def advise(s: SessionSummary, packets: list[TelemetryPacket] | None = None) -> str:
    """Full tuning report: AI when configured, otherwise the rules engine.

    `packets`, when given, add a per-lap breakdown to the prompt so the model
    sees lap-to-lap evolution, not just aggregates.
    """
    settings = resolve_settings()
    lang = settings.get("lang", "en")
    rules = suggest(s, lang=lang)
    fallback = format_suggestions(rules, lang=lang)
    if not settings.get("key"):
        return fallback

    prompt = (
        "Session telemetry summary:\n"
        f"{format_report(s, lang=lang)}\n\n"
        f"Rule-engine suggestions:\n{fallback}\n\n"
    )
    if packets is not None:
        per_lap = format_per_lap(summarize_per_lap(packets), lang=lang)
        if per_lap:
            prompt += f"{per_lap}\n\n"
    prompt += "Turn this into a prioritized tuning plan following your instructions."
    try:
        return _chat(settings, prompt)
    except Exception as exc:  # network/API errors must never lose the rules report
        print(f"fth: AI advisor unavailable ({exc}); using rules engine.", file=sys.stderr)
        return fallback
