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
- **Unit auto-detection (`detect_units`/`normalize_units`) is a plausibility
  heuristic, not a spec** — it existed unused for a while (nothing called it)
  until dashboard.py/`__main__.py` were wired to run every session through
  `normalize_session()` before summarizing/advising. Still unverified against
  a real localized (e.g. French) FH6 install; if display units aren't
  actually tied to game language the way reported, or the p95 thresholds
  misfire on a real car/track combo, recalibrate `_DETECT_TEMP`/
  `_DETECT_SPEED` (session.py) or add an explicit `units` override in
  Settings instead of relying on auto-detect.

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
- **Free/reasoning-model detection is a substring heuristic**
  (`_REASONING_HINTS` in advisor.py), not sourced from an official capability
  flag — recalibrate against real API responses; provider catalogs change
  over time. Groq's `default_model` (`openai/gpt-oss-120b`) and its
  `supports_reasoning_effort: False` guard are likewise best-effort as of
  writing — verify against Groq's current docs before trusting either.
- **Single stored API key for both providers**: switching provider in
  Settings doesn't switch which key is stored — there's one `key` field in
  `~/.fth/config.json`, not one per provider. Fine for a single-provider-at-a-
  time workflow; re-enter the key after switching if it differs.

## Dashboard

- **Car card shows raw codes**: `car_ordinal` and `car_class` are game-internal
  IDs — FH6's Data Out carries no model name, and the class-code → letter
  (D…X) mapping is not officially documented. Displayed as-is.
- **The Drive tab's rolling buffer (~2-3 min) is still separate from
  captures**. Explicit recording (start/stop/save via the Captures tab) is
  independent and must be saved before stopping or the process exits, or the
  recorded packets are discarded — `CaptureController` in dashboard.py holds
  them only in memory until `.save()` writes to `~/.fth/captures/`.
- **Auto-lap capture (`AutoLapRecorder`) drops the in-progress lap when
  disabled or the process exits** — only fully completed laps (a
  `lap_number` change while enabled) get auto-saved. Turn it off after your
  last lap if you want that final partial lap too; use manual start/stop for
  that instead.
- **Session-restart detection (`feed()` in `make_live_server`) requires both
  a race-time dip AND a non-advancing lap number** before clearing the
  buffer, specifically so a per-lap race-time reset in time-trial/hot-lap
  modes (reported: race time restarts every lap, wiping accumulated laps)
  doesn't get mistaken for a real "back to menu, new race" restart. This is
  inferred from the symptom, not verified against real FH6 time-trial
  telemetry — if lap_number *also* resets per lap in that mode, this
  heuristic won't catch it either; revisit with a real capture if so.
- **Captures tab is list/manage only**: saved captures aren't loaded back into
  the Drive/Tune charts in-app; review one with `fth dashboard <path>`.
- **Polling every 2s**, not websockets/SSE — right size for localhost.
- **Chart.js comes from CDN**: the dashboard is offline except for that one
  request; vendoring ~200KB into the repo was declined.
- **UDP port for tests grabbed via bind-then-close probe** — racy under
  parallel test runs; switch to port 0 + socket introspection if it flakes.

## Tooling / repo

- **`summarize()` materializes the whole packet list in memory** — fine up to
  ~10⁵ samples; stream-reduce if marathon logs ever show up.
