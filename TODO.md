# Technical debt & known limitations

Everything actionable has been worked through; what remains is either a
deliberate trade-off or blocked on data that doesn't exist yet. Each item
names its ceiling and what would change it.

## Telemetry / metrics

- **Thresholds are uncalibrated guesses.** `_LOCKUP_RATIO`, `_SPIN_SLIP_RATIO`,
  `_SPIN_MIN_ACCEL_MPS2`, `_HS_SPEED_KMH` (session.py) and every `_CONSTANT`
  in tuning.py are plausible values never fitted against a real FH6 session
  log. Upgrade path: record sessions on known setups, tune constants, add
  regression fixtures from real logs.
- **Aero rules ignore wind, gradient and banking** — high-speed grip loss is
  attributed to downforce alone; the Data Out stream offers no way to separate
  those effects.

## Advisor (AI layer)

- **Synchronous single attempt**: `advise()` blocks the caller up to
  `FTH_AI_TIMEOUT` (default 45s); no retry/streaming. Accepted: streaming
  output is over-engineering for a local tool; raise the env var if needed.
- **Prompt carries aggregates and per-lap tables, not raw series** — corner-by-
  corner transients stay invisible to the model. Fixing this means shipping a
  large serialized trace; revisit only if aggregate advice disappoints.
- **API key stored in plain text** at `~/.fth/config.json` when saved from the
  dashboard (file perms follow umask). Accepted for a single-user local tool;
  don't share the file, and don't build multi-user tooling on top of this.

## Dashboard

- **Car card shows raw codes**: `car_ordinal` and `car_class` are game-internal
  IDs — FH6's Data Out carries no model name, and the class-code → letter
  (D…X) mapping is not officially documented. Displayed as-is.
- **Live mode keeps one rolling buffer (~2-3 min)** with no persistence;
  returning to the menu clears it on the next packet (race-time reset) rather
  than archiving the previous session.
- **Polling every 2s**, not websockets/SSE — right size for localhost.
- **Chart.js comes from CDN**: the dashboard is offline except for that one
  request; vendoring ~200KB into the repo was declined.
- **UDP port for tests grabbed via bind-then-close probe** — racy under
  parallel test runs; switch to port 0 + socket introspection if it flakes.

## Tooling / repo

- **`summarize()` materializes the whole packet list in memory** — fine up to
  ~10⁵ samples; stream-reduce if marathon logs ever show up.
