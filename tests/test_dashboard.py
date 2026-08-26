"""Tests for the web app: /data payload, settings, analyze, live modes."""

import io
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from fth.dashboard import _MAX_POINTS, _dashboard_data, make_live_server, make_server
from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket
from fth.session import CsvRecorder


@pytest.fixture(autouse=True)
def _clean_ai_env(monkeypatch, tmp_path):
    for name in ("FTH_AI_KEY", "FTH_AI_URL", "FTH_AI_MODEL", "FTH_AI_REASONING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "config.json"))


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


def _post(url: str, payload: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_dashboard_data_shape():
    data = _dashboard_data(_packets(25))
    assert data["summary"]["samples"] == 25
    assert [lap["lap"] for lap in data["laps"]] == [0, 1, 2]
    assert [b["lap"] for b in data["lap_bounds"]] == [0, 1, 2]
    assert data["car"]["drivetrain"] == "RWD"  # fixture default
    assert data["car"]["performance_index"] == 800
    assert isinstance(data["suggestions"], list)
    for key in ("t", "speed_kmh", "rpm", "tire_fl", "slip_front", "slip_rear"):
        assert len(data["series"][key]) == 25
        assert len(data["series"][key]) == len(data["series"]["t"])


def test_dashboard_data_converts_tire_temp_f_to_c():
    ps = [
        TelemetryPacket.from_bytes(
            make_packet(current_race_time=float(i), tire_temp_front_left=212.0)  # 100 C
        )
        for i in range(3)
    ]
    data = _dashboard_data(ps)
    assert data["series"]["tire_fl"][0] == pytest.approx(100.0, abs=0.1)


def test_dashboard_data_never_converts_speed():
    # Speed is always m/s on the wire, unconditionally -- must never be touched.
    data = _dashboard_data(_packets(25))
    assert data["series"]["speed_kmh"][0] == pytest.approx(40.0 * 3.6, abs=0.1)


def test_settings_roundtrip_over_http():
    httpd = make_server(lambda: None, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://{httpd.server_address[0]}:{httpd.server_port}"
    try:
        _, _, body = _get(base + "/settings")
        assert json.loads(body) == {
            "key_set": False,
            "model": "",
            "reasoning": "",
            "provider": "openrouter",
        }

        status, body = _post(base + "/settings", {"key": "k1", "model": "vendor/m"})
        assert status == 200

        _, _, body = _get(base + "/settings")
        assert json.loads(body) == {
            "key_set": True,
            "model": "vendor/m",
            "reasoning": "",
            "provider": "openrouter",
        }

        # posting without a key must keep the stored one
        _post(base + "/settings", {"model": "vendor/m2"})
        _, _, body = _get(base + "/settings")
        cfg = json.loads(body)
        assert cfg["key_set"] and cfg["model"] == "vendor/m2"

        # provider switches and round-trips
        _post(base + "/settings", {"provider": "groq"})
        _, _, body = _get(base + "/settings")
        assert json.loads(body)["provider"] == "groq"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_analyze_endpoint(monkeypatch):
    monkeypatch.setattr("fth.dashboard.advise", lambda s, ps: "PLAN-TEXT")
    httpd = make_server(lambda: _packets(6), host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://{httpd.server_address[0]}:{httpd.server_port}"
    try:
        status, body = _post(base + "/analyze", {})
        assert status == 200
        assert json.loads(body)["text"] == "PLAN-TEXT"
    finally:
        httpd.shutdown()
        httpd.server_close()

    # no data yet -> 400
    empty = make_server(lambda: None, host="127.0.0.1", port=0)
    thread2 = threading.Thread(target=empty.serve_forever, daemon=True)
    thread2.start()
    try:
        base2 = f"http://{empty.server_address[0]}:{empty.server_port}"
        status, body = _post(base2 + "/analyze", {})
        assert status == 400
        assert "no session data" in body
    finally:
        empty.shutdown()
        empty.server_close()


def test_http_page_and_data():
    httpd = make_server(lambda: _packets(6), host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}"

        status, ctype, page = _get(base + "/")
        assert status == 200
        assert "text/html" in ctype
        assert 'id="tab-settings"' in page
        assert 'id="analyze-btn"' in page
        assert 'fetch("/data")' in page or 'api("/data")' in page
        assert 'id="theme-toggle"' in page
        assert "--bg:" in page
        assert '[data-theme="light"]' in page
        assert 'id="tab-captures"' in page
        assert 'id="capture-start"' in page
        assert 'id="f-provider"' in page
        assert 'id="model-checks"' in page
        assert 'id="auto-capture-toggle"' in page

        status, ctype, payload = _get(base + "/data")
        assert status == 200
        assert "application/json" in ctype
        assert json.loads(payload)["summary"]["samples"] == 6
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_series_downsampled():
    data = _dashboard_data(_packets(_MAX_POINTS * 3))
    assert len(data["series"]["t"]) <= _MAX_POINTS + 1


def test_provider_updates_between_polls():
    """The live path: same server, fresh JSON each request."""
    ps: list[TelemetryPacket] = []
    httpd = make_server(lambda: ps if len(ps) >= 2 else None)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}/data"

        _, _, payload = _get(base)
        assert json.loads(payload)["waiting"] is True

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


def test_models_endpoint(monkeypatch):
    monkeypatch.setattr(
        "fth.dashboard.list_models",
        lambda settings=None: [{"id": "m1", "name": "M1", "free": True, "reasoning": False}],
    )
    httpd = make_server(lambda: None, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}"
        _, _, body = _get(base + "/models")
        data = json.loads(body)
        assert data["models"] == [{"id": "m1", "name": "M1", "free": True, "reasoning": False}]
        assert data["provider"] == "openrouter"

        _, _, body = _get(base + "/models?provider=groq")
        assert json.loads(body)["provider"] == "groq"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_capture_lifecycle_over_http(monkeypatch, tmp_path):
    monkeypatch.setenv("FTH_CAPTURES_DIR", str(tmp_path / "captures"))
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    udp_port = probe.getsockname()[1]
    probe.close()

    httpd = make_live_server(host="127.0.0.1", port=0, udp_port=udp_port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}"

        status, body = _post(base + "/capture/start", {})
        assert status == 200

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for i in range(3):
            sock.sendto(
                make_packet(speed=50.0 + i, current_race_time=float(i)), ("127.0.0.1", udp_port)
            )
        sock.close()

        samples = None
        for _ in range(50):
            _, _, body = _get(base + "/capture/status")
            samples = json.loads(body)["samples"]
            if samples >= 3:
                break
            time.sleep(0.1)
        assert samples == 3

        status, body = _post(base + "/capture/stop", {})
        assert status == 200
        _, _, body = _get(base + "/capture/status")
        assert json.loads(body) == {"recording": False, "samples": 3}

        status, body = _post(base + "/capture/save", {"name": "lap-test"})
        assert status == 200
        assert json.loads(body)["name"] == "lap-test"

        _, _, body = _get(base + "/captures")
        names = [c["name"] for c in json.loads(body)["captures"]]
        assert "lap-test" in names
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_auto_lap_capture_saves_each_completed_lap(monkeypatch, tmp_path):
    monkeypatch.setenv("FTH_CAPTURES_DIR", str(tmp_path / "captures"))
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    udp_port = probe.getsockname()[1]
    probe.close()

    httpd = make_live_server(host="127.0.0.1", port=0, udp_port=udp_port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}"

        status, body = _post(base + "/capture/auto", {"enabled": True})
        assert status == 200
        assert json.loads(body)["enabled"] is True

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        def send(rows):
            for t, lap in rows:
                sock.sendto(
                    make_packet(speed=50.0, current_race_time=float(t), lap_number=lap),
                    ("127.0.0.1", udp_port),
                )

        def auto_status():
            for _ in range(50):
                _, _, body = _get(base + "/capture/auto/status")
                s = json.loads(body)
                if s["samples"] > 0:
                    return s
                time.sleep(0.1)
            return None

        send([(0, 0), (1, 0), (2, 0)])
        assert auto_status()["current_lap"] == 0

        send([(0, 1), (1, 1)])  # lap boundary: lap 0 must be auto-saved
        for _ in range(50):
            _, _, body = _get(base + "/captures")
            names = [c["name"] for c in json.loads(body)["captures"]]
            if any(n.startswith("auto-lap0-") for n in names):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("lap 0 was never auto-saved")

        status, body = _post(base + "/capture/auto", {"enabled": False})
        assert json.loads(body) == {"enabled": False, "current_lap": None, "samples": 0}
        sock.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_capture_endpoints_404_in_static_mode():
    httpd = make_server(lambda: _packets(6), host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}"
        status, body = _post(base + "/capture/start", {})
        assert status == 404
        try:
            _get(base + "/capture/status")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        try:
            _get(base + "/capture/auto/status")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        status, body = _post(base + "/capture/auto", {"enabled": True})
        assert status == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_captures_import_over_http(monkeypatch, tmp_path):
    monkeypatch.setenv("FTH_CAPTURES_DIR", str(tmp_path / "captures"))
    httpd = make_server(lambda: None, host="127.0.0.1", port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}"
        buf = io.StringIO()
        recorder = CsvRecorder(buf)
        for pkt in _packets(3):
            recorder.write(pkt)
        recorder.flush()

        status, body = _post(base + "/captures/import", {"name": "imported", "csv": buf.getvalue()})
        assert status == 200

        _, _, body = _get(base + "/captures")
        names = [c["name"] for c in json.loads(body)["captures"]]
        assert "imported" in names

        status, body = _post(base + "/captures/import", {"name": "bad", "csv": "x,y\n1,2\n"})
        assert status == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_live_server_resets_on_session_restart():
    """Race time going backwards means a new session: the buffer must clear."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    udp_port = probe.getsockname()[1]
    probe.close()

    httpd = make_live_server(host="127.0.0.1", port=0, udp_port=udp_port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        def send(times):
            for t in times:
                sock.sendto(
                    make_packet(speed=50.0, current_race_time=float(t)),
                    ("127.0.0.1", udp_port),
                )

        send([0, 1, 2, 3])
        base = f"http://{httpd.server_address[0]}:{httpd.server_port}/data"

        def samples():
            for _ in range(50):
                try:
                    _, _, payload = _get(base)
                except OSError:
                    continue
                if "waiting" not in payload:
                    return json.loads(payload)["summary"]["samples"]
                time.sleep(0.1)
            return None

        assert samples() == 4
        send([-10, -9])  # session restart: race time went backwards
        assert samples() == 2
        sock.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_live_server_keeps_buffer_across_lap_time_reset():
    """Time-trial/hot-lap: race time resets each lap but the lap number keeps
    advancing — that's a new lap, not a new session, so nothing should clear."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    udp_port = probe.getsockname()[1]
    probe.close()

    httpd = make_live_server(host="127.0.0.1", port=0, udp_port=udp_port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        def send(rows):
            for t, lap in rows:
                sock.sendto(
                    make_packet(speed=50.0, current_race_time=float(t), lap_number=lap),
                    ("127.0.0.1", udp_port),
                )

        base = f"http://{httpd.server_address[0]}:{httpd.server_port}/data"

        def samples():
            for _ in range(50):
                try:
                    _, _, payload = _get(base)
                except OSError:
                    continue
                if "waiting" not in payload:
                    return json.loads(payload)["summary"]["samples"]
                time.sleep(0.1)
            return None

        send([(0, 0), (1, 0), (2, 0)])  # lap 0
        assert samples() == 3
        send([(0, 1), (1, 1)])  # lap 1: race time restarts, lap number advances
        assert samples() == 5  # kept, not cleared
        sock.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
