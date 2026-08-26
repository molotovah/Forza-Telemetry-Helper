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
ruff format <touched files>    # repo is NOT format-clean overall; only format files you edit
```

## Layout (`src/fth/`)

- `ingest.py` — 324-byte packet struct spec, `TelemetryPacket`, `listen()` UDP loop
- `session.py` — CSV record/load, `SessionSummary`, `summarize()`, `summarize_per_lap()`, report formatting
- `tuning.py` — rules engine mapping metrics to relative `Suggestion`s; thresholds are module-level `_CONSTANTS`
- `advisor.py` — AI layer: OpenAI-compatible chat endpoint via stdlib `urllib`; env `FTH_AI_URL`/`FTH_AI_KEY`/`FTH_AI_MODEL`; always falls back to the rules engine on missing config or any error
- `dashboard.py` — local web dashboard: single self-contained HTML page (Chart.js CDN) served by stdlib `http.server`
- `fixtures.py` — synthetic packet builder for tests/demos (`make_packet(**overrides)`)

## Conventions

- **Zero runtime dependencies** — stdlib only. Dev deps (pytest, ruff) are fine.
- Tests mirror the module they cover (`tests/test_<module>.py`); use
  `fth.fixtures.make_packet` for synthetic data. No test frameworks beyond pytest.
- Tuning suggestions are always **relative** to the user's current setup
  (the game's Data Out stream is one-way; current tune values are unknown).
- Rule thresholds live as named constants at the top of `tuning.py`.
- CLI lives in `__main__.py`; subcommand dispatch handles bare `fth` → live mode.

## Roadmap & releases

Roadmap table lives in README.md; keep it in sync. One commit per roadmap
phase, conventional-commit style (`feat: … (phase N)`). Bump the version in
`pyproject.toml` per shipped phase. See CONTRIBUTING.md for contributor flow.
