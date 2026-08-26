"""Minimal local web dashboard: one self-contained HTML page (Chart.js from
CDN) with the session summary and telemetry charts embedded as JSON.

Served with the stdlib http.server on 127.0.0.1 — nothing leaves the machine
except the Chart.js library request to the CDN.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterable

from fth.ingest import TelemetryPacket
from fth.session import summarize, summarize_per_lap

_MAX_POINTS = 500  # downsample long sessions so the page stays light

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
  table { border-collapse: collapse; }
  td { padding: .15rem 1rem .15rem 0; white-space: nowrap; }
  td:first-child { color: #9ab; }
  .charts { display: grid; gap: 1.5rem; max-width: 900px; }
</style>
</head>
<body>
<h1>Forza Telemetry Helper — session dashboard</h1>
<div id="summary"></div>
<h2>Speed / RPM</h2><div class="charts"><canvas id="c-speed"></canvas></div>
<h2>Tire temps (C)</h2><div class="charts"><canvas id="c-tires"></canvas></div>
<h2>Grip loss (|combined slip| per axle)</h2>
<div class="charts"><canvas id="c-slip"></canvas></div>
<script>
const DATA = __DATA__;
const s = DATA.summary;
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
];
document.getElementById("summary").innerHTML =
  "<table>" + rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join("") + "</table>";

function chart(id, labels, sets, yExtra) {
  new Chart(document.getElementById(id), {
    type: "line",
    data: { labels,
            datasets: sets.map(d => ({ label: d.label, data: d.data,
                                       pointRadius: 0, borderWidth: d.width || 1.5,
                                       borderColor: d.color, yAxisID: d.axis || "y" })) },
    options: { animation: false, interaction: { mode: "index", intersect: false },
               scales: { x: { ticks: { maxTicksLimit: 10 } }, ...yExtra } } });
}

const t = DATA.series.t;
chart("c-speed", t,
  [{ label: "km/h", data: DATA.series.speed_kmh, color: "#4fc3f7" },
   { label: "rpm", data: DATA.series.rpm, color: "#ffb74d", axis: "y1" }],
  { y: { position: "left" }, y1: { position: "right" } });

chart("c-tires", t,
  [["FL", "#e57373"], ["FR", "#f06292"], ["RL", "#81c784"], ["RR", "#4db6ac"]]
    .map(([k, c]) => ({ label: k, data: DATA.series["tire_" + k.toLowerCase()], color: c })));

chart("c-slip", t,
  [{ label: "front", data: DATA.series.slip_front, color: "#ba68c8" },
   { label: "rear", data: DATA.series.slip_rear, color: "#ffd54f" }]);
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


def _dashboard_data(packets: list[TelemetryPacket]) -> dict:
    summary = summarize(packets)
    return {
        "summary": asdict(summary),
        "laps": [{"lap": n, **asdict(s)} for n, s in summarize_per_lap(packets)],
        "series": _series(packets),
    }


def render_page(data: dict) -> str:
    return _PAGE.replace("__DATA__", json.dumps(data))


def make_server(
    packets: list[TelemetryPacket], host: str = "127.0.0.1", port: int = 8000
) -> HTTPServer:
    page = render_page(_dashboard_data(packets))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:  # silence request spam
            pass

    return HTTPServer((host, port), Handler)


def serve(packets: Iterable[TelemetryPacket], host: str = "127.0.0.1", port: int = 8000) -> None:
    httpd = make_server(list(packets), host, port)
    url = f"http://{httpd.server_address[0]}:{httpd.server_port}/"
    print(f"Dashboard on {url} — Ctrl+C to stop.")
    threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
