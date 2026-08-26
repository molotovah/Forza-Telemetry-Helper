# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

AI-assisted tuning advisor for Forza Horizon 6: ingests the game's one-way UDP
"Data Out" telemetry (fixed 324-byte packets), extracts session metrics, and
produces tuning-menu suggestions via a rules engine plus an optional AI layer.
Not affiliated with Microsoft/Forza.

## Commands

```sh
pip install -e '.[dev]'        # setup (Python 3.10+)
pytest -q                      # tests (CI gate)
ruff check .                   # lint (CI gate; E,F,W,I — line length 100)
ruff format --check .          # CI gate too — repo IS format-clean, keep it that way
```

## Layout (`src/fth/`)

- `ingest.py` — 324-byte packet struct spec, `TelemetryPacket`, `listen()` UDP loop
- `session.py` — CSV record/load, `SessionSummary`, `summarize()`, `summarize_per_lap()`, report formatting (`format_report`/`format_per_lap`, bilingual via `lang="en"|"fr"`, template tables `_R`/`_BALANCE_LABEL`)
- `tuning.py` — rules engine mapping metrics to relative `Suggestion`s; thresholds are module-level `_CONSTANTS`; bilingual via `lang="en"|"fr"` (template tables `_T`/`_AXLE`) threaded through `suggest()`/`format_suggestions()`
- `advisor.py` — AI layer: OpenRouter or Groq (`_PROVIDERS` table, OpenAI-compatible chat API) via stdlib `urllib`; settings resolved provider defaults <- `~/.fth/config.json` <- env (`FTH_AI_*`); `list_models()` fetches/flags free+reasoning models per provider; always falls back to the rules engine on missing key or any error
- `config.py` — persistent user settings store (`~/.fth/config.json`, path overridable via `FTH_CONFIG`)
- `captures.py` — named capture storage (`~/.fth/captures/<name>.csv`, path overridable via `FTH_CAPTURES_DIR`): save/load/import/list, reuses `session.CsvRecorder`/`load_csv`
- `dashboard.py` — the web app (static CSV mode + live UDP mode): single page with Drive/Tune/Captures/Settings tabs polling JSON endpoints (`/data`, `/settings`, `/analyze`, `/captures`, `/capture/*`, `/capture/auto*`), Chart.js CDN, stdlib `http.server`. `CaptureController` (manual start/stop/save) and `AutoLapRecorder` (opt-in, saves each completed lap automatically) run independently off the same UDP feed.
- `fixtures.py` — synthetic packet builder for tests/demos (`make_packet(**overrides)`)

## Conventions

- **Zero runtime dependencies** — stdlib only. Dev deps (pytest, ruff) are fine.
- Tests mirror the module they cover (`tests/test_<module>.py`); use
  `fth.fixtures.make_packet` for synthetic data. No test frameworks beyond pytest.
- Tuning suggestions are always **relative** to the user's current setup
  (the game's Data Out stream is one-way; current tune values are unknown).
- Rule thresholds live as named constants at the top of `tuning.py` and
  `session.py`; most are uncalibrated guesses — see TODO.md before trusting them.
- Metric semantics follow the official FH6 docs: slip values are normalized
  (0 = full grip, |v| > 1 = grip loss), wheel speeds in rad/s, DrivetrainType
  0=FWD / 1=RWD / 2=AWD. Wire units are fixed, not display/language-dependent:
  `Speed` m/s, `Power` W, `Torque` N·m (explicit in the docs); `TireTemp*` is
  always Fahrenheit (undocumented there, confirmed by independent FH
  telemetry projects) — `session.normalize_units()`/`normalize_session()`
  convert it to Celsius unconditionally. Raw packets (as read off the wire,
  pre-normalization) are what CSVs store; normalize only at analysis/display
  time, never at capture time.
- The dashboard never echoes the stored API key back to the browser
  (`key_set: bool` only). POST /settings with an empty key keeps the old one.
- CLI lives in `__main__.py`; bare `fth` launches the live web app,
  `fth live` is the terminal readout.
- **i18n (en/fr)**: `config.lang` ("en" default, "fr") drives *all* generated
  text — tuning suggestions (`tuning.suggest`/`format_suggestions`), the
  session report (`session.format_report`/`format_per_lap`), and the AI
  advisor's system prompt (`advisor._chat`). The dashboard UI itself is
  translated client-side (`I18N` object + `t()`/`applyLang()` in `_PAGE`'s
  `<script>`, `data-i18n`/`data-i18n-html` attributes in the HTML) and kept
  in sync with the stored `lang` via `GET /settings`; the header's EN/FR
  toggle POSTs the change and immediately re-polls so suggestion text updates
  without waiting for the next 2s cycle. Adding a UI string: put it in both
  `I18N.en` and `I18N.fr` (same key) — nothing enforces parity automatically,
  so a mismatch means one language silently shows raw key names or falls
  back through `t()`. Adding a rule-engine string: same pattern in
  `tuning._T`/`session._R`.

## Roadmap & releases

Roadmap table lives in README.md; keep it in sync, along with TODO.md for
technical debt. One commit per roadmap phase, conventional-commit style
(`feat: … (phase N)`). Bump the version in **both** `pyproject.toml` and
`src/fth/__init__.py`'s `__version__` per shipped phase — they're two
separate sources of truth and have drifted before (fixed once already).
See CONTRIBUTING.md for contributor flow.
