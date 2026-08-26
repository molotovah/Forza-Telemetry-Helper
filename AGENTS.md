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
- `session.py` — CSV record/load, `SessionSummary`, `summarize()`, `summarize_per_lap()`, report formatting
- `tuning.py` — rules engine mapping metrics to relative `Suggestion`s; thresholds are module-level `_CONSTANTS`
- `advisor.py` — AI layer: OpenRouter (`stealth/ox-alpha` by default) via stdlib `urllib`; settings resolved defaults <- `~/.fth/config.json` <- env (`FTH_AI_*`); always falls back to the rules engine on missing key or any error
- `config.py` — persistent user settings store (`~/.fth/config.json`, path overridable via `FTH_CONFIG`)
- `dashboard.py` — the web app (static CSV mode + live UDP mode): single page with Drive/Tune/Settings tabs polling JSON endpoints (`/data`, `/settings`, `/analyze`), Chart.js CDN, stdlib `http.server`
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
  0=FWD / 1=RWD / 2=AWD.
- The dashboard never echoes the stored API key back to the browser
  (`key_set: bool` only). POST /settings with an empty key keeps the old one.
- CLI lives in `__main__.py`; bare `fth` launches the live web app,
  `fth live` is the terminal readout.

## Roadmap & releases

Roadmap table lives in README.md; keep it in sync, along with TODO.md for
technical debt. One commit per roadmap phase, conventional-commit style
(`feat: … (phase N)`). Bump the version in `pyproject.toml` per shipped phase.
See CONTRIBUTING.md for contributor flow.
