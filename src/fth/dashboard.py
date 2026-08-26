"""The fth web app: local dashboard over recorded or live FH6 telemetry.

Launched by `fth` (live UDP) or `fth dashboard FILE` (static CSV). One page,
three tabs — Drive (charts + car card), Tune (rule suggestions + AI plan),
Settings (OpenRouter key/model stored in ~/.fth/config.json). Everything is
stdlib http.server + JSON endpoints; Chart.js comes from a CDN.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from collections import deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from fth import config
from fth.advisor import advise, resolve_settings
from fth.ingest import TelemetryPacket, listen
from fth.session import summarize, summarize_per_lap
from fth.tuning import suggest

_MAX_POINTS = 500  # downsample long sessions so the page stays light
_BUFFER_LEN = 4000  # rolling window of live packets (~2-3 min of driving)

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fth</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body { background: #101418; color: #d8dee6; font: 14px/1.5 system-ui, sans-serif;
         margin: 0; padding: 1.5rem; }
  h1 { font-size: 1.15rem; margin: 0 0 .75rem; }
  h2 { font-size: .95rem; margin: 1.25rem 0 .5rem; color: #9ab; }
  nav button { background: #1b222a; color: #d8dee6; border: 0; border-radius: 6px 6px 0 0;
               padding: .4rem 1.1rem; margin-right: .25rem; cursor: pointer; font-size: .9rem; }
  nav button.active { background: #2a3440; font-weight: 600; }
  section { display: none; max-width: 900px; }
  section.active { display: block; }
  td { padding: .15rem 1rem .15rem 0; white-space: nowrap; }
  td:first-child { color: #9ab; }
  #status { color: #e5c07b; }
  #udp-error { color: #e06c75; }
  .card { background: #1b222a; border-radius: 8px; padding: .75rem 1rem;
          display: inline-block; vertical-align: top; margin-right: 1rem; }
  canvas { max-width: 900px; }
  label { display: block; margin-top: .8rem; color: #9ab; }
  input, select { background: #0d1117; color: #d8dee6; border: 1px solid #2a3440;
                  border-radius: 5px; padding: .35rem .5rem; width: 320px; }
  button.action { background: #2a5d8f; border: 0; border-radius: 6px; color: #fff;
                  padding: .45rem 1.2rem; cursor: pointer; margin-top: .8rem; }
  button.action:disabled { opacity: .5; cursor: wait; }
  pre { white-space: pre-wrap; background: #161b22; border-radius: 8px; padding: 1rem; }
  .hint { color: #7d8894; font-size: .85rem; }
</style>
</head>
<body>
<h1>Forza Telemetry Helper <span id="status"></span><span id="udp-error"></span></h1>
<nav>
  <button data-tab="drive" class="active">Drive</button>
  <button data-tab="tune">Tune</button>
  <button data-tab="settings">Settings</button>
</nav>

<section id="tab-drive" class="active">
  <div id="summary"><span class="hint">waiting for telemetry…</span></div>
  <h2>Car</h2><div id="car"></div>
  <h2>Speed / RPM</h2><canvas id="c-speed"></canvas>
  <h2>Tire temps (C)</h2><canvas id="c-tires"></canvas>
  <h2>Grip loss (|combined slip| per axle)</h2><canvas id="c-slip"></canvas>
</section>

<section id="tab-tune">
  <h2>Rule-engine suggestions</h2><div id="suggestions"></div>
  <h2>AI tuning plan</h2>
  <p class="hint">Sends the full session (summary, per-lap table, rule suggestions)
  to the configured model. Needs an API key in Settings.</p>
  <button class="action" id="analyze-btn">Generate AI tuning plan</button>
  <pre id="ai-out" hidden></pre>
</section>

<section id="tab-settings">
  <p class="hint">Stored in your user config file; the key is sent only to the
  configured API endpoint.</p>
  <form id="settings-form">
    <label>API key (leave empty to keep the saved one)</label>
    <input type="password" id="f-key" placeholder="sk-or-v1-…">
    <label>Model ID</label>
    <input type="text" id="f-model">
    <label>Reasoning effort (ox-alpha)</label>
    <select id="f-reasoning">
      <option value="">default (max)</option>
      <option value="low">low</option>
      <option value="high">high</option>
      <option value="max">max</option>
    </select>
    <button class="action" type="submit">Save settings</button>
    <span id="save-status" class="hint"></span>
  </form>
</section>

<script>
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("active"));
  document.querySelectorAll("section").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  document.getElementById("tab-" + b.dataset.tab).classList.add("active");
});

const CHART_DEFS = [
  ["c-speed",
   [{label: "km/h", key: "speed_kmh", color: "#4fc3f7"},
    {label: "rpm", key: "rpm", color: "#ffb74d", axis: "y1"}],
   {y: {position: "left"}, y1: {position: "right"}}],
  ["c-tires",
   [{label: "FL", key: "tire_fl", color: "#e57373"},
    {label: "FR", key: "tire_fr", color: "#f06292"},
    {label: "RL", key: "tire_rl", color: "#81c784"},
    {label: "RR", key: "tire_rr", color: "#4db6ac"}],
   {}],
  ["c-slip",
   [{label: "front", key: "slip_front", color: "#ba68c8"},
    {label: "rear", key: "slip_rear", color: "#ffd54f"}],
   {}],
];
const charts = {};

const lapLines = {
  id: "lapLines",
  afterDatasetsDraw(chart) {
    const laps = chart.$laps || [];
    if (laps.length < 2) return;
    const labels = chart.data.labels;
    const ctx = chart.ctx;
    ctx.save();
    ctx.strokeStyle = "#5c6370";
    ctx.setLineDash([4, 4]);
    for (let i = 1; i < laps.length; i++) {
      const idx = labels.indexOf(laps[i].t_start);
      if (idx < 0) continue;
      const x = chart.scales.x.getPixelForValue(idx);
      if (!isFinite(x)) continue;
      ctx.beginPath();
      ctx.moveTo(x, chart.chartArea.top);
      ctx.lineTo(x, chart.chartArea.bottom);
      ctx.stroke();
    }
    ctx.restore();
  },
};

function makeChart(id, sets, scales) {
  return new Chart(document.getElementById(id), {
    type: "line",
    data: {labels: [],
           datasets: sets.map(d => ({label: d.label, data: [], pointRadius: 0,
                                     borderWidth: d.width || 1.5,
                                     borderColor: d.color, yAxisID: d.axis || "y"}))},
    options: {animation: false, interaction: {mode: "index", intersect: false}, scales},
    plugins: [lapLines]});
}

async function api(path, opts) {
  const resp = await fetch(path, opts);
  return resp.json();
}

function renderSummary(s) {
  const rows = [
    ["samples / duration", `${s.samples} / ${s.duration_s.toFixed(1)}s`],
    ["speed avg / max", `${s.avg_speed_kmh.toFixed(1)} / ${s.max_speed_kmh.toFixed(1)} km/h`],
    ["redline / pedal overlap",
     `${s.redline_pct.toFixed(1)}% / ${s.pedal_overlap_pct.toFixed(1)}%`],
    ["grip loss front / rear",
     `${s.grip_loss_front_pct.toFixed(1)}% / ${s.grip_loss_rear_pct.toFixed(1)}%`
     + ` (${s.balance_hint})`],
    ["tire temps avg f / r",
     `${s.tire_temp_front_avg_c.toFixed(1)} / ${s.tire_temp_rear_avg_c.toFixed(1)} C`],
    ["peak power / torque", `${s.max_power_kw.toFixed(0)} kW / ${s.max_torque_nm.toFixed(0)} Nm`],
    ["wheelspin / lockup f-r",
     `${s.wheelspin_pct.toFixed(1)}% / ${s.lockup_front_pct.toFixed(1)}%`
     + ` - ${s.lockup_rear_pct.toFixed(1)}%`],
    ["coast oversteer", `${s.coast_oversteer_pct.toFixed(1)}%`],
  ];
  document.getElementById("summary").innerHTML =
    "<table>" + rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join("") + "</table>";
}

function renderCar(car) {
  const rows = Object.entries(car).map(([k, v]) =>
    `<tr><td>${k.replace(/_/g, " ")}</td><td>${v}</td></tr>`).join("");
  document.getElementById("car").innerHTML = `<div class="card"><table>${rows}</table></div>`;
}

function renderSuggestions(items) {
  const el = document.getElementById("suggestions");
  if (!items.length) {
    el.innerHTML = '<span class="hint">none yet — setup looks balanced so far.</span>';
    return;
  }
  el.innerHTML = "<ul>" + items.map(it =>
    `<li><b>${it.parameter}</b>: ${it.change}<br><span class="hint">${it.reason}</span></li>`
  ).join("") + "</ul>";
}

async function poll() {
  let data;
  try {
    data = await api("/data");
  } catch {
    return;  // server went away; keep the last frame on screen
  }
  if (data.waiting) {
    document.getElementById("status").textContent = "— waiting for telemetry…";
    return;
  }
  document.getElementById("status").textContent = "";
  document.getElementById("udp-error").textContent =
    data.udp_error ? "UDP error: " + data.udp_error : "";
  renderSummary(data.summary);
  renderCar(data.car);
  renderSuggestions(data.suggestions || []);
  const ser = data.series;
  for (const [id, sets, scales] of CHART_DEFS) {
    if (!charts[id]) charts[id] = makeChart(id, sets, scales);
    const ch = charts[id];
    ch.$laps = data.lap_bounds || [];
    ch.data.labels = ser.t;
    ch.data.datasets.forEach(ds => { ds.data = ser[ds.key]; });
    ch.update("none");
  }
}
setInterval(poll, 2000);
poll();

document.getElementById("analyze-btn").onclick = async () => {
  const btn = document.getElementById("analyze-btn");
  const out = document.getElementById("ai-out");
  btn.disabled = true;
  btn.textContent = "Thinking… (can take up to a minute)";
  try {
    const result = await api("/analyze", {method: "POST"});
    out.textContent = result.text;
    out.hidden = false;
  } catch {
    out.textContent = "Request failed.";
    out.hidden = false;
  }
  btn.disabled = false;
  btn.textContent = "Generate AI tuning plan";
};

async function loadSettingsForm() {
  const s = await api("/settings");
  document.getElementById("f-model").value = s.model || "stealth/ox-alpha";
  document.getElementById("f-reasoning").value = s.reasoning || "";
  document.getElementById("f-key").placeholder =
    s.key_set ? "saved — leave empty to keep" : "sk-or-v1-…";
}

document.getElementById("settings-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const body = {
    model: document.getElementById("f-model").value.trim(),
    reasoning: document.getElementById("f-reasoning").value,
  };
  const key = document.getElementById("f-key").value.trim();
  if (key) body.key = key;
  await api("/settings", {method: "POST",
                          headers: {"Content-Type": "application/json"},
                          body: JSON.stringify(body)});
  document.getElementById("f-key").value = "";
  document.getElementById("save-status").textContent = "saved ✓";
  setTimeout(() => document.getElementById("save-status").textContent = "", 2000);
  loadSettingsForm();
};
loadSettingsForm();
</script>
</body>
</html>
"""


def _axle_slip(p: TelemetryPacket, axle: str) -> float:
    left = getattr(p, f"tire_combined_slip_{axle}_left")
    right = getattr(p, f"tire_combined_slip_{axle}_right")
    return round(max(abs(left), abs(right)), 2)


def _series(packets: list[TelemetryPacket]) -> dict:
    sel = packets[:: max(1, len(packets) // _MAX_POINTS)]
    return {
        "t": [round(p.current_race_time, 1) for p in sel],
        "speed_kmh": [round(p.speed * 3.6, 1) for p in sel],
        "rpm": [round(p.current_engine_rpm) for p in sel],
        "tire_fl": [round(p.tire_temp_front_left, 1) for p in sel],
        "tire_fr": [round(p.tire_temp_front_right, 1) for p in sel],
        "tire_rl": [round(p.tire_temp_rear_left, 1) for p in sel],
        "tire_rr": [round(p.tire_temp_rear_right, 1) for p in sel],
        "slip_front": [_axle_slip(p, "front") for p in sel],
        "slip_rear": [_axle_slip(p, "rear") for p in sel],
    }


def _lap_bounds(packets: list[TelemetryPacket]) -> list[dict]:
    """Start time of each lap; a lap_number change is always a boundary."""
    bounds: list[dict] = []
    for p in packets:
        if not bounds or bounds[-1]["lap"] != p.lap_number:
            bounds.append({"lap": p.lap_number, "t_start": round(p.current_race_time, 1)})
    return bounds


_DT_LABELS = ("FWD", "RWD", "AWD")


def _car_block(packets: list[TelemetryPacket]) -> dict:
    """Identity/performance fields from the latest packet (constant per car)."""
    p = packets[-1]
    return {
        "car_id": p.car_ordinal,  # game-internal ID; FH6 sends no model name
        "class_code": p.car_class,  # raw code, letter mapping unconfirmed
        "performance_index": p.car_performance_index,  # 100-999
        "drivetrain": (_DT_LABELS[p.drivetrain_type] if p.drivetrain_type in (0, 1, 2) else "?"),
        "cylinders": p.num_cylinders,
        "car_group": p.car_group,
    }


def _dashboard_data(packets: list[TelemetryPacket], udp_error: str | None = None) -> dict:
    summary = summarize(packets)
    return {
        "summary": asdict(summary),
        "laps": [{"lap": n, **asdict(s)} for n, s in summarize_per_lap(packets)],
        "lap_bounds": _lap_bounds(packets),
        "car": _car_block(packets),
        "suggestions": [
            {"parameter": it.parameter, "change": it.change, "reason": it.reason}
            for it in suggest(summary)
        ],
        "series": _series(packets),
        **({"udp_error": udp_error} if udp_error else {}),
    }


def make_server(
    packets_getter: Callable[[], list[TelemetryPacket] | None],
    host: str = "127.0.0.1",
    port: int = 8000,
    error_getter: Callable[[], str] | None = None,
) -> HTTPServer:
    """packets_getter() -> current packet list, or None while nothing arrived."""

    def udp_error() -> str:
        return error_getter() if error_getter else ""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: str, ctype: str, code: int = 200) -> None:
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/data":
                ps = packets_getter()
                if ps:
                    self._send(json.dumps(_dashboard_data(ps, udp_error())), "application/json")
                else:
                    self._send(
                        json.dumps({"waiting": True, "udp_error": udp_error()}),
                        "application/json",
                    )
            elif path == "/settings":
                stored = config.load()
                self._send(
                    json.dumps(
                        {
                            # readiness considers env vars too
                            "key_set": bool(resolve_settings().get("key")),
                            "model": stored.get("model", ""),
                            "reasoning": stored.get("reasoning", ""),
                        }
                    ),
                    "application/json",
                )
            else:
                self._serve_page()

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            length = int(self.headers.get("Content-Length", 0))
            try:
                fields = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._send('{"error": "invalid JSON"}', "application/json", 400)
                return
            if path == "/settings":
                allowed = {k: str(fields[k]) for k in ("key", "model", "reasoning") if k in fields}
                config.save(**allowed)
                self._send('{"ok": true}', "application/json")
            elif path == "/analyze":
                ps = packets_getter()
                if not ps or len(ps) < 2:
                    self._send('{"error": "no session data yet"}', "application/json", 400)
                else:
                    self._send(json.dumps({"text": advise(summarize(ps), ps)}), "application/json")
            else:
                self._send('{"error": "not found"}', "application/json", 404)

        def _serve_page(self) -> None:
            self._send(_PAGE, "text/html; charset=utf-8")

        def log_message(self, *_args) -> None:  # silence request spam
            pass

    return HTTPServer((host, port), Handler)


def _run(httpd: HTTPServer) -> None:
    url = f"http://{httpd.server_address[0]}:{httpd.server_port}/"
    print(f"fth running on {url} — Ctrl+C to stop.")
    threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def serve(packets: list[TelemetryPacket], host: str = "127.0.0.1", port: int = 8000) -> None:
    """Static mode: everything is computed once from the recorded packets."""
    _run(make_server(lambda: packets, host, port))


def make_live_server(
    host: str = "127.0.0.1", port: int = 8000, udp_host: str = "127.0.0.1", udp_port: int = 20777
) -> HTTPServer:
    """Live mode server: a daemon thread feeds a rolling buffer from UDP."""
    buf: deque[TelemetryPacket] = deque(maxlen=_BUFFER_LEN)
    state = {"udp_error": ""}

    def feed() -> None:
        last_t: float | None = None
        try:
            for pkt in listen(udp_host, udp_port):
                if not pkt.is_race_on:
                    continue
                if last_t is not None and pkt.current_race_time < last_t - 1.0:
                    buf.clear()  # race time went backwards: fresh session
                buf.append(pkt)
                last_t = pkt.current_race_time
        except OSError as exc:
            state["udp_error"] = f"cannot bind udp://{udp_host}:{udp_port}: {exc}"
            print(f"fth: {state['udp_error']}", file=sys.stderr)

    def getter() -> list[TelemetryPacket] | None:
        return list(buf) if len(buf) >= 2 else None

    threading.Thread(target=feed, daemon=True).start()
    return make_server(getter, host, port, error_getter=lambda: state["udp_error"])


def serve_live(
    host: str = "127.0.0.1", port: int = 8000, udp_host: str = "127.0.0.1", udp_port: int = 20777
) -> None:
    _run(make_live_server(host, port, udp_host, udp_port))
