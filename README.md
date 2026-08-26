# Forza-Telemetry-Helper

AI-assisted tuning advisor for **Forza Horizon 6**. The tool listens to the game's official
"Data Out" UDP telemetry stream, extracts performance indicators from real driving data
(tire slip, temperatures, suspension usage, RPM range, throttle/brake overlap, understeer /
oversteer balance), and turns them into **data-driven car setup suggestions** — powered by a
rules engine and an AI analysis layer.

> Not affiliated with or endorsed by Microsoft or the Forza franchise.
> "Forza", "Forza Horizon" and their logos are trademarks of Microsoft.

## How it works

```
FH6 (UDP "Data Out", 324-byte packets)
        │
        ▼
  fth ingest ──► live readout (CLI)
        │
        ▼
  session metrics ──► rules engine ──► setup suggestions
        │
        ▼
  AI advisor (Ox Alpha) ──► prioritized tuning report
```

The game only **sends** telemetry (one-way UDP); it cannot receive settings back.
Suggestions are meant to be applied manually in FH6's tuning menu.

## Requirements

- Python 3.10+
- Forza Horizon 6 with telemetry enabled

## Install

```sh
git clone https://github.com/molotovah/Forza-Telemetry-Helper.git
cd Forza-Telemetry-Helper
pip install -e .
```

## Game configuration

In FH6: **Settings > HUD and Gameplay**

| Setting             | Value                                        |
| ------------------- | -------------------------------------------- |
| Data Out            | On                                           |
| Data Out IP Address | `127.0.0.1` (same PC) or your PC's local IP  |
| Data Out IP Port    | `20777` (avoid 5200–5300 — used by the game) |

## Usage

```sh
fth                            # live readout while driving (default port 20777)
fth live --csv session.csv     # same + record raw packets to CSV
fth analyze session.csv        # session report from a recorded log
fth analyze session.csv --out report.txt   # same, written to a file
fth dashboard session.csv      # local web dashboard with charts (port 8000)
fth dashboard --live           # same, fed directly by the UDP stream
```

### AI advisor

`fth analyze --ai` sends the session summary plus rule-engine suggestions to
**Ox Alpha** (`stealth/ox-alpha`) through [OpenRouter](https://openrouter.ai/stealth/ox-alpha)
for a prioritized tuning plan. Without a key (or on any API error) the offline
rules engine is used.

```sh
export FTH_AI_KEY="sk-or-v1-…"      # create one at https://openrouter.ai/keys
fth analyze session.csv --ai

# optional overrides
export FTH_AI_MODEL="stealth/ox-alpha"   # any OpenRouter model ID (default: this)
export FTH_AI_URL="https://…"            # any OpenAI-compatible endpoint
export FTH_AI_TIMEOUT="45"               # request timeout in seconds
export FTH_AI_REASONING="high"           # ox-alpha effort: low | high | max
```

Example report (`fth analyze`):

```
=== Session summary ===
samples 30  duration 2.9s  distance 1.45km
laps 0  best lap 0.00s
speed: avg 248.4 km/h, max 352.8 km/h
time at redline: 0.0%  brake/throttle overlap: 0.0%
grip loss: front 66.7% vs rear 0.0%  (understeer-biased)
tire temps avg C: front 44.0 / rear 0.0, hottest 90.8
max suspension travel m: front 0.000 / rear 0.000
peak power 300 kW  peak torque 450 Nm
```

## Roadmap

| Phase | Feature                                                            | Status         |
| ----- | ------------------------------------------------------------------ | -------------- |
| 0     | Project scaffolding, CI                                            | ✅ done        |
| 1     | UDP ingestion + packet parser + synthetic fixtures                 | ✅ done        |
| 2     | Session recording & feature extraction (per-lap aggregates, CSV)   | ✅ done        |
| 3     | Rules-based tuning engine (tires, alignment, springs, gearing)     | ✅ done        |
| 4     | AI advisor via Ox Alpha HTTP API (offline fallback to rules)       | ✅ done        |
| 5     | CLI reports + community web dashboard                              | ✅ done        |
| 6     | Community docs, examples, contribution workflow                    | ✅ done        |
| 7     | Extended tuning rules: brakes, differential, aero                  | ✅ done        |
| 8     | Live dashboard fed by the UDP stream                               | ✅ done        |
| 9     | Calibrated metrics: relative lockup, coast oversteer, spin gating  | ✅ done        |
| 10    | AI advisor: per-lap prompt context, configurable timeout           | ✅ done        |
| 11    | Repo hygiene: repo-wide formatting, CI matrix 3.10–3.14, CLI tests | ✅ done        |
| 12    | Dashboard lap markers and live session reset                       | ✅ done        |

Known limitations and deferred work live in [TODO.md](TODO.md).

## Protocol notes (FH6 specifics)

- Fixed 324-byte packet format; sent at frame rate, only while driving.
- Compared with Forza Motorsport, FH6 adds `CarGroup`, `SmashableVelDiff` and
  `SmashableMass` (after `NumCylinders`) and omits `TireWear`/`TrackOrdinal`.
- Official documentation:
  [Forza Horizon 6 "Data Out"](https://support.forza.net/hc/en-us/articles/51744149102611-Forza-Horizon-6-Data-Out-Documentation).

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues:
session analytics, additional tuning heuristics, dashboard work.

## License

[MIT](LICENSE)
