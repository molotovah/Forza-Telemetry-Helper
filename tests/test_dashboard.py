"""Tests for the web dashboard: /data endpoint, static and live modes."""

import json
import socket
import threading
import time
import urllib.request

from fth.dashboard import _MAX_POINTS, _dashboard_data, make_live_server, make_server
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


def _get(url: str) -> tuple[int, str, str]:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.headers["Content-Type"], resp.read().decode()


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


def test_http_page_and_data():
    httpd = make_server(lambda: _dashboard_data(_packets(6)), host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}"

        status, ctype, page = _get(base + "/")
        assert status == 200
        assert "text/html" in ctype
        assert "Forza Telemetry Helper — session dashboard" in page
        assert 'fetch("/data")' in page

        status, ctype, payload = _get(base + "/data")
        assert status == 200
        assert "application/json" in ctype
        assert json.loads(payload)["summary"]["samples"] == 6
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_provider_updates_between_polls():
    """The live path: same server, fresh JSON each request."""
    ps: list[TelemetryPacket] = []
    httpd = make_server(lambda: _dashboard_data(ps) if len(ps) >= 2 else None)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}/data"

        _, _, payload = _get(base)
        assert json.loads(payload) == {"waiting": True}

        ps.extend(_packets(3))
        _, _, payload = _get(base)
        assert json.loads(payload)["summary"]["samples"] == 3
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_live_server_receives_udp_packets():
    """End to end: UDP datagrams in -> /data JSON out."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    udp_port = probe.getsockname()[1]
    probe.close()

    httpd = make_live_server(host="127.0.0.1", port=0, udp_port=udp_port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for i in range(4):
            sock.sendto(
                make_packet(speed=50.0 + i, current_race_time=float(i)),
                ("127.0.0.1", udp_port),
            )
        sock.close()

        base = f"http://{httpd.server_address[0]}:{httpd.server_port}/data"
        payload = None
        for _ in range(50):  # up to ~5s for the feeder thread to process
            try:
                _, _, payload = _get(base)
            except OSError:
                payload = None
            if payload and "waiting" not in payload:
                break
            time.sleep(0.1)

        data = json.loads(payload)
        assert data["summary"]["samples"] == 4
        assert data["summary"]["max_speed_kmh"] == (53.0 * 3.6)
    finally:
        httpd.shutdown()
        httpd.server_close()
