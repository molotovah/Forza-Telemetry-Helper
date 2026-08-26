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
- **Damping (bump/rebound) suggestions are co-inferred from the same signal
  as springs** — max normalized suspension travel, not oscillation frequency
  or velocity. Bottoming out could mean the spring rate is wrong, the damping
  is wrong, or both; the rule fires for both parameters off one shared
  observation. Treat as a starting point paired with the spring suggestion,
  not an independently validated damping read. A real fix needs per-sample
  travel *velocity*, not just the session max.
- **Toe, caster and per-gear ratio tuning are not covered** — deliberately.
  The Data Out stream has no field that plausibly proxies toe or caster
  (they affect turn-in feel/tire wear, not anything in the slip/temp/travel
  aggregates here), and per-gear ratio advice would need per-gear
  time-at-redline from raw packets (`gear` field exists per-packet, but
  `SessionSummary` only aggregates `redline_pct` across the whole session,
  not broken out by gear) — a real feature, not a one-line addition. Add
  a `gear`-keyed breakdown to `summarize()` before attempting it; don't
  guess a rule without a data source the way the units heuristic did.
- **(Resolved, keeping the postmortem.)** An earlier "auto-detect metric vs
  imperial" heuristic (`detect_units`, a `units` config field) assumed the
  wire format had two variants depending on display/language settings — it
  did not, and the heuristic required *both* a hot-tire and a fast-speed
  anchor to fire, so a session with F-scale tire temps but normal-looking
  speed (the actual reported bug: "141°C" front tire, i.e. a converted
  Fahrenheit value mislabeled as Celsius) never triggered it. Checked against
  the official Data Out docs plus an independently-validated sibling FH
  telemetry project: `Speed`/`Power`/`Torque` are explicitly SI on the wire,
  unconditionally, no imperial variant exists; `TireTemp*` is unconditionally
  Fahrenheit, undocumented officially but confirmed by every community
  parser checked. `normalize_units()`/`normalize_session()` now do a fixed,
  always-on TireTemp F→C conversion — no detection, no config field, nothing
  to misfire. If a *future* report shows some other field wrong (e.g. an
  actual metric/imperial user preference toggle in a later Forza title),
  don't resurrect this heuristic — get the field-level unit from
  documentation or a validated source first, the way this fix did.

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

## Localization (i18n)

- **Only English/French, only two languages.** Adding a third means a third
  branch in every `_T`/`_R`/`I18N` table (tuning.py, session.py, dashboard.py)
  plus the `advisor._SYSTEM` French-only instruction — no abstraction over
  "supported languages" exists yet, by design (two tables per module is
  simple; a registry for two entries would be over-engineering).
- **No locale number/date formatting** — percentages and decimals use plain
  `.toFixed()`/Python `:.1f` regardless of language (period decimals even in
  French text). Deliberate: correct-enough for a technical audience, avoids
  pulling in `Intl`/locale-data complexity for a cosmetic difference.
- **The AI advisor's free-text reply depends on model compliance, not
  enforcement** — `_SYSTEM_FR` (advisor.py) is a full French system prompt
  (not an appended "reply in French" afterthought — that version let a
  reported case through in English with psi units) that also states tire
  pressure must be in bar for French; nothing validates the model actually
  followed either instruction, only that it was asked clearly. Weaker/
  distilled models are the likeliest to ignore it. The rules-engine fallback
  (used when no key is configured, i.e. most users) has no such gap — its
  text and units (bar for `lang="fr"`, psi for `"en"`) are template-generated,
  not model-generated.
- **Client i18n has no automated parity check** — `I18N.en`/`I18N.fr` in
  `dashboard.py`'s `_PAGE` must have matching keys by hand; nothing in CI
  verifies it (checked manually at write time via a one-off script, not a
  repo test). A missing key falls back to showing the raw key name via `t()`
  — visible immediately in the UI, not a silent crash, but still worth a
  real test if this file grows further.

## Tooling / repo

- **`summarize()` materializes the whole packet list in memory** — fine up to
  ~10⁵ samples; stream-reduce if marathon logs ever show up.
