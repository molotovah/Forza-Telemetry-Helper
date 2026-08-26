# Technical debt & known limitations

Deliberate simplifications and deferred work. Items are ordered roughly by
impact; each names its ceiling and the upgrade path.

## Telemetry / metrics

- **Thresholds are uncalibrated guesses.** `_LOCKUP_WHEEL_RADS`, `_SPIN_SLIP_RATIO`,
  `_HS_SPEED_KMH` (session.py) and every `_CONSTANT` in tuning.py were picked
  from plausible values, never against a real FH6 session log.
  Upgrade path: record sessions on known setups, tune constants, add regression
  fixtures from real logs.
- **Lockup detection is absolute, not relative.** A locked wheel = rotation
  speed < 5 rad/s while the car moves; it ignores wheel radius and expected
  wheel speed derived from `speed`. Fine for full lockups; misses partial ABS
  intervention. Upgrade path: derive expected rad/s from speed per axle.
- **No decel-differential rule.** Off-throttle oversteer needs coasting-state
  slip metrics that aren't computed yet; the diff rule only covers power
  wheelspin.
- **Wheelspin uses a fixed slip-ratio cut** (0.5) regardless of gear/speed;
  low-speed corner-exit scrubs may read as spin. Upgrade path: gate by gear or
  longitudinal acceleration.
- **Aero rules ignore wind/gradient and track banking** — high-speed grip loss
  is attributed to downforce alone.

## Advisor (AI layer)

- **Synchronous, no retry/streaming**: `advise()` blocks the CLI up to 45s,
  single attempt. Upgrade path: background call with progressive output.
- **Prompt carries only aggregate metrics**, not raw series; the model can't
  spot transients (e.g., lift-off oversteer in one corner).
- **API key travels via env var** — fine locally, but `ps -e` can expose it;
  don't ship multi-user tooling on top of this.

## Dashboard

- **Live mode is single-buffer, single-consumer**: one rolling deque (~2-3 min
  of driving), no persistence, no lap markers on charts, no session reset when
  returning to menu (`is_race_on` gaps are simply dropped).
- **Polling every 2s**, not websockets/SSE — fine locally, chatty if ever hosted.
- **Chart.js comes from CDN**: dashboard is offline except for that one request.
- **UDP port for tests grabbed via bind-then-close probe** — racy under
  parallel test runs; switch to port 0 + socket introspection if it flakes.

## Tooling / repo

- **Repo is not `ruff format`-clean**; CI enforces `ruff check` only. Format
  files you touch; do not bulk-reformat without a dedicated commit.
- **CI matrix lacks Python 3.10 and 3.14** although `requires-python >= 3.10`.
- **No CLI-dispatch tests** (`__main__.py`: subcommands, flag wiring) — covered
  only by manual smoke tests.
- **`examples/report.txt` is regenerated manually** after formatting changes;
  drift goes unnoticed until someone reads it closely.
- **`summarize()` materializes the whole packet list in memory** — fine up to
  ~10⁵ samples; stream-reduce if marathon logs show up.
