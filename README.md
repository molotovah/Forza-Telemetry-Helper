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
- Forza Horizon 6 with telemetry enabled — needed for live capture only;
  `analyze`/`dashboard` also work from a recorded CSV on any machine

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

### Try it without a car

The repo ships a synthetic session — no game needed:

```sh
fth analyze examples/session.csv      # text report + tuning suggestions
fth dashboard examples/session.csv    # web dashboard → http://127.0.0.1:8000
```

### Use case 1 — real-time readout while driving

Watch speed, RPM, gear and tire temps update live as you drive:

```sh
fth                          # binds udp://127.0.0.1:20777 (Ctrl+C to quit)
fth --host 0.0.0.0           # game runs on another device? bind all interfaces
```

### Use case 2 — record, analyze, tune (the core loop)

1. Record one or more clean laps to CSV while driving:

```sh
fth live --csv session.csv
```

2. Get the report and apply the suggested changes in FH6's tuning menu:

```sh
fth analyze session.csv
fth analyze session.csv --out report.txt   # save it instead of printing
```

3. Drive again with the new setup, record `session2.csv`, and compare the two
reports — per-lap breakdown and grip-loss numbers show whether the change
worked.

Example output:

```
=== Session summary ===
samples 120  duration 119.0s  distance 0.00km
laps 2  best lap 88.50s
speed: avg 127.1 km/h, max 215.2 km/h
time at redline: 0.0%  brake/throttle overlap: 0.0%
grip loss: front 33.3% vs rear 0.0%  (understeer-biased)
tire temps avg C: front 49.8 / rear 0.0, hottest 114.0
max suspension travel m: front 0.000 / rear 0.000
peak power 300 kW  peak torque 450 Nm
drivetrain RWD  wheelspin 0.0%  brake lockup f/r 0.0%/0.0%
coast oversteer 0.0%
grip loss at >= 120 km/h: front 32.8% / rear 0.0%

=== Per-lap breakdown ===
lap 0: avg 138.4 km/h max 180.0  grip loss f/r 35%/0%  redline 0%
lap 1: avg 115.3 km/h max 197.9  grip loss f/r 32%/0%  redline 0%
lap 2: avg 127.6 km/h max 215.2  grip loss f/r 32%/0%  redline 0%

=== Suggested tuning changes (relative to your current setup) ===
* Tire pressure (front): +2 psi
    reason: avg front tire temp 50 C never reaches 70 C
* Anti-roll bar (front): -2
    reason: excess front grip loss (33% vs 0% rear)
* Camber (front): +0.3 deg
    reason: front axle slides before the rear
...
```

Suggestions can cover tires, alignment, anti-roll bars, springs, gearing,
brakes, differential and aero — whichever problems your data actually shows.

### Use case 3 — AI tuning plan via OpenRouter

Beyond the rules engine, get a prioritized plan written by **Ox Alpha**
(`stealth/ox-alpha`), which reads your full summary, per-lap table and rule
suggestions:

```sh
export FTH_AI_KEY="sk-or-v1-…"       # create one at https://openrouter.ai/keys
fth analyze session.csv --ai         # falls back to rules on any API error
```

Optional overrides: `FTH_AI_MODEL` (any OpenRouter model ID),
`FTH_AI_URL` (any OpenAI-compatible endpoint), `FTH_AI_TIMEOUT`,
`FTH_AI_REASONING` (`low|high|max`, ox-alpha effort).

### Use case 4 — web dashboard

Charts (speed/RPM, tire temps, grip loss) in your browser, with lap markers:

```sh
fth dashboard session.csv            # from a recording, port 8000
fth dashboard --live                 # fed directly by the UDP stream
fth dashboard session.csv --port 9000   # custom HTTP port; --udp-port for live
```

In live mode the page polls every 2 s, shows "waiting for telemetry…" until
you drive, and resets automatically when you return to the menu and start a
new session.

## Command reference

| Command                              | What it does                                    |
| ------------------------------------ | ----------------------------------------------- |
| `fth`                                | live readout (defaults: host `127.0.0.1`, UDP 20777) |
| `fth live --csv FILE`                | live readout + record packets to CSV            |
| `fth analyze FILE [--out F] [--ai]`  | session report (+ AI plan), print or save       |
| `fth dashboard [FILE] [--live]`      | local web dashboard from CSV or live UDP        |

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
