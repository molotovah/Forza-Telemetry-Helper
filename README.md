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

The wire format's units are fixed, not tied to any in-game display/region/
language setting: `Speed`/`Power`/`Torque` are always SI (documented), tire
temperatures are always Fahrenheit (undocumented but confirmed by every
independently-validated FH telemetry project). fth converts tire temps to
Celsius at analysis time; nothing to configure.

## Usage

### The app — one command while you play

```sh
fth                # web app on http://127.0.0.1:8000 + live UDP telemetry
```

This is all you need while playing. The UI is bilingual (English/French) —
toggle with the **EN/FR** button next to the theme toggle; it persists to
`~/.fth/config.json` (`lang`) and immediately re-renders everything, tuning
suggestions and session report text included, not just the UI chrome. The
browser window opens by itself with four tabs:

- **Drive** — live charts (speed/RPM, tire temps, grip loss), session summary
  and a car card (ID, class code, performance index, drivetrain, cylinders)
  as soon as you're on the road. Charts get lap markers.
- **Tune** — rule-engine suggestions updating live, plus a *Generate AI tuning
  plan* button that sends your whole session to the configured model.
- **Captures** — start/stop recording independently of the live rolling
  buffer (that buffer is capped at ~100,000 samples / ~30 min for live-chart
  performance; a capture itself is not — it records everything from start to
  stop, however long that takes). Quick start/stop and a recording-status
  indicator also live right on the Drive tab, so you don't need to switch
  tabs to begin recording. Save the recording under a name, import a
  CSV recorded elsewhere, or delete a capture you no longer want — a Delete
  button sits next to each row in the list, and the list always reflects
  `~/.fth/captures/` as it actually is on disk (delete a file by hand and
  it's gone from the list too, no restart needed). An *auto-capture per lap*
  checkbox additionally saves every completed lap as its own capture
  automatically (named `auto-lap<n>-<timestamp>`), running alongside — not
  instead of — the manual start/stop. Open a saved capture's charts with
  `fth dashboard ~/.fth/captures/<name>.csv`. Recording controls only appear
  in live mode (`fth` / `fth dashboard --live`).
- **Settings** — units (metric/imperial — affects speed, tire pressure,
  temperature, power and torque everywhere: charts, reports, tuning
  suggestions, the AI prompt), AI provider/API key/model/reasoning effort.
  Saved locally to `~/.fth/config.json`; the key is never sent anywhere
  except the model endpoint.

Options: `fth --host 127.0.0.1 --port 8000 --udp-port 20777`.

If the game runs on another device, bind the LAN interface: `fth --host 0.0.0.0`.

### Try it without a car

The repo ships a synthetic session — no game needed:

```sh
fth dashboard examples/session.csv    # same UI over recorded data → port 8000
fth analyze examples/session.csv      # text report + tuning suggestions
```

### Terminal workflow (alternative)

Prefer the command line? Record and analyze from the shell:

```sh
fth live --csv session.csv     # terminal readout + record packets to CSV
fth analyze session.csv        # report + suggestions (--ai adds the AI plan)
fth analyze session.csv --out report.txt   # save the report instead of printing
```

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
* Tire pressure (front): +0.1 bar
    reason: avg front tire temp 50 C never reaches 70 C
* Anti-roll bar (front): -2
    reason: excess front grip loss (33% vs 0% rear)
* Camber (front): +0.3 deg
    reason: front axle slides before the rear
...
```

Suggestions can cover tires, alignment, anti-roll bars, springs, damping,
ride height, gearing, brakes, differential (including AWD center split) and
aero — whichever problems your data actually shows. Rule text and the
session report are generated in whichever language is set (`lang` in
`~/.fth/config.json`, or the dashboard's EN/FR toggle); the AI advisor's
free-text plan follows the same setting when a key is configured.

Units (`units` in `~/.fth/config.json`, or the Settings tab's Units select)
are a separate choice from language — French text with imperial units, or
English text with metric, both work. Default is metric everywhere (speed,
tire pressure, temperature, power, torque); pick Imperial to see mph, psi,
°F, hp and lb-ft instead, in the dashboard, the CLI report and the AI prompt
alike.

### AI advisor settings

The provider/key/model configured in the dashboard's Settings tab are used
everywhere. Environment variables override the file if both are set:

| Variable           | Default                                                    |
| ------------------ | ----------------------------------------------------------- |
| `FTH_AI_PROVIDER`  | `openrouter` — or `groq`                                   |
| `FTH_AI_KEY`       | *(none — or the key saved in the dashboard)*                |
| `FTH_AI_MODEL`     | `stealth/ox-alpha` via [OpenRouter](https://openrouter.ai/stealth/ox-alpha), `openai/gpt-oss-120b` via [Groq](https://console.groq.com/) |
| `FTH_AI_URL`       | the provider's chat completions endpoint                    |
| `FTH_AI_TIMEOUT`   | `45` seconds                                                 |
| `FTH_AI_REASONING` | *(model default)* — `low`, `high` or `max`; **OpenRouter only**, ignored on Groq |

Settings tab also has a *Refresh models* button that lists the selected
provider's free/reasoning-capable models as checkboxes — checking one sets it
as the active model. OpenRouter's list is public; Groq's requires a saved key.
Detection of "free"/"reasoning" is a heuristic (see TODO.md), not an official
capability flag, so double-check a model actually fits your use before relying
on the badge.

## Command reference

| Command                              | What it does                                    |
| ------------------------------------ | ----------------------------------------------- |
| `fth`                                | launches the web app with live telemetry        |
| `fth dashboard [FILE] [--live]`      | same UI from a CSV recording                    |
| `fth live [--csv FILE]`              | terminal-only readout (+ record to CSV)         |
| `fth analyze FILE [--out F] [--ai]`  | text report (+ AI plan), print or save          |

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
| 13    | Dashboard-first app: settings, AI trigger and car card in the UI   | ✅ done        |
| 14    | Dark/light mode toggle                                             | ✅ done        |
| 15    | Named capture storage: save/load/import/list endpoints             | ✅ done        |
| 16    | Captures tab UI: start/stop/save/import/list                       | ✅ done        |
| 17    | AI provider choice: OpenRouter or Groq                             | ✅ done        |
| 18    | Free/reasoning model listing + checkbox picker                     | ✅ done        |
| 19    | Fixed TireTemp F→C conversion; lap-aware session reset; auto-lap capture | ✅ done  |
| 20    | Missing tuning rules (center diff, ride height, damping) + full FR/EN i18n | ✅ done |
| 21    | Capture delete; metric/imperial units setting independent of language | ✅ done |
| 22    | Larger Drive-tab buffer; quick capture start/stop + status on Drive tab | ✅ done |

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
