"""Tests for the local web dashboard (data shape, downsampling, HTTP page)."""

import json
import threading
import urllib.request

from fth.dashboard import _MAX_POINTS, _dashboard_data, make_server, render_page
from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket


def _packets(n: int) -> list[TelemetryPacket]:
    return [
        TelemetryPacket.from_bytes(
            make_packet(
                speed=40.0 + i,
                current_race_time=float(i),
                lap_number=i // 10,
                tire_temp_front_left=80.0 + i,
            )
        )
        for i in range(n)
    ]


def test_dashboard_data_shape():
    data = _dashboard_data(_packets(25))
    assert data["summary"]["samples"] == 25
    assert [lap["lap"] for lap in data["laps"]] == [0, 1, 2]
    for key in ("t", "speed_kmh", "rpm", "tire_fl", "slip_front", "slip_rear"):
        assert len(data["series"][key]) == 25
        assert len(data["series"][key]) == len(data["series"]["t"])


def test_series_downsampled():
    data = _dashboard_data(_packets(_MAX_POINTS * 3))
    assert len(data["series"]["t"]) <= _MAX_POINTS + 1


def test_render_page_embeds_json():
    page = render_page(_dashboard_data(_packets(4)))
    assert "__DATA__" not in page
    assert '"balance_hint"' in page
    # the embedded JSON must parse back out of the script tag
    payload = page.split("const DATA = ", 1)[1].split(";\n", 1)[0]
    assert json.loads(payload)["summary"]["samples"] == 4


def test_http_roundtrip():
    httpd = make_server(_packets(6), host="127.0.0.1", port=0)  # ephemeral port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://{httpd.server_address[0]}:{httpd.server_port}/"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode()
            assert resp.status == 200
            assert "text/html" in resp.headers["Content-Type"]
        assert "Forza Telemetry Helper — session dashboard" in body
        assert '"speed_kmh"' in body
    finally:
        httpd.shutdown()
        httpd.server_close()
