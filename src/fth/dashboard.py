"""Local web dashboard over recorded or live FH6 telemetry.

Static mode (`fth dashboard session.csv`): one HTML page whose charts are fed
by a /data endpoint generated once from the CSV.
Live mode (`fth dashboard --live`): the same page polls /data every 2s while a
daemon thread fills a rolling buffer from the game's UDP stream.
Chart.js comes from a CDN; everything else is stdlib.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from collections import deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Iterable

from fth.ingest import TelemetryPacket, listen
from fth.session import summarize, summarize_per_lap

_MAX_POINTS = 500  # downsample long sessions so the page stays light
_BUFFER_LEN = 4000  # rolling window of live packets (~2-3 min of driving)

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fth dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  body { background: #101418; color: #d8dee6; font: 14px/1.5 system-ui, sans-serif;
         margin: 0; padding: 1.5rem; }
  h1 { font-size: 1.2rem; margin: 0 0 .5rem; }
  h2 { font-size: 1rem; margin: 1.5rem 0 .5rem; color: #9ab; }
  td { padding: .15rem 1rem .15rem 0; white-space: nowrap; }
  td:first-child { color: #9ab; }
  #status { color: #e5c07b; }
  canvas { max-width: 900px; }
</style>
</head>
<body>
<h1>Forza Telemetry Helper — session dashboard <span id="status"></span></h1>
<div id="summary"><span id="status">waiting for telemetry…</span></div>
<h2>Speed / RPM</h2><canvas id="c-speed"></canvas>
<h2>Tire temps (C)</h2><canvas id="c-tires"></canvas>
<h2>Grip loss (|combined slip| per axle)</h2><canvas id="c-slip"></canvas>
<script>
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
  ];
  document.getElementById("summary").innerHTML =
    "<table>" + rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join("") + "</table>";
}

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

async function poll() {
  let data;
  try {
    data = await (await fetch("/data")).json();
  } catch {
    return;  // server went away; keep the last frame on screen
  }
  if (data.waiting) {
    document.getElementById("status").textContent = "waiting for telemetry…";
    return;
  }
  document.getElementById("status").textContent = "";
  renderSummary(data.summary);
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


def _dashboard_data(packets: list[TelemetryPacket]) -> dict:
    summary = summarize(packets)
    return {
        "summary": asdict(summary),
        "laps": [{"lap": n, **asdict(s)} for n, s in summarize_per_lap(packets)],
        "lap_bounds": _lap_bounds(packets),
        "series": _series(packets),
    }


def make_server(
    provider: Callable[[], dict | None], host: str = "127.0.0.1", port: int = 8000
) -> HTTPServer:
    """provider() returns the current dashboard payload, or None while waiting."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/data":
                body = json.dumps(provider() or {"waiting": True}).encode()
                ctype = "application/json"
            else:
                body = _PAGE.encode()
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:  # silence request spam
            pass

    return HTTPServer((host, port), Handler)


def _run(httpd: HTTPServer) -> None:
    url = f"http://{httpd.server_address[0]}:{httpd.server_port}/"
    print(f"Dashboard on {url} — Ctrl+C to stop.")
    threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def serve(packets: Iterable[TelemetryPacket], host: str = "127.0.0.1", port: int = 8000) -> None:
    """Static mode: everything is computed once from the recorded packets."""
    data = _dashboard_data(list(packets))
    _run(make_server(lambda: data, host, port))


def make_live_server(
    host: str = "127.0.0.1", port: int = 8000, udp_host: str = "127.0.0.1", udp_port: int = 20777
) -> HTTPServer:
    """Live mode server: a daemon thread feeds a rolling buffer from UDP."""
    buf: deque[TelemetryPacket] = deque(maxlen=_BUFFER_LEN)

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
            print(f"fth: cannot bind udp://{udp_host}:{udp_port} ({exc})", file=sys.stderr)

    def provider() -> dict | None:
        return _dashboard_data(list(buf)) if len(buf) >= 2 else None

    threading.Thread(target=feed, daemon=True).start()
    return make_server(provider, host, port)


def serve_live(
    host: str = "127.0.0.1", port: int = 8000, udp_host: str = "127.0.0.1", udp_port: int = 20777
) -> None:
    _run(make_live_server(host, port, udp_host, udp_port))
