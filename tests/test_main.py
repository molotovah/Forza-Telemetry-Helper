"""CLI dispatch tests and the example-report drift guard."""

import csv
import sys

import pytest

from fth import __main__ as cli
from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket


@pytest.fixture
def session_csv(tmp_path):
    path = tmp_path / "session.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        from fth.session import _NAMES

        writer.writerow(_NAMES)
        for i in range(4):
            pkt = TelemetryPacket.from_bytes(make_packet(current_race_time=float(i)))
            writer.writerow([getattr(pkt, name) for name in _NAMES])
    return str(path)


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["fth", *argv])
    cli.main()


def test_analyze_prints_report(monkeypatch, capsys, session_csv):
    run_cli(monkeypatch, "analyze", session_csv)
    out = capsys.readouterr().out
    assert "Session summary" in out
    assert "Suggested tuning changes" in out


def test_analyze_out_writes_file(monkeypatch, capsys, tmp_path, session_csv):
    out_path = tmp_path / "report.txt"
    run_cli(monkeypatch, "analyze", session_csv, "--out", str(out_path))
    assert "Report saved" in capsys.readouterr().out
    assert out_path.exists()


def test_dashboard_static_dispatch(monkeypatch, session_csv):
    seen = {}
    monkeypatch.setattr(
        cli,
        "serve",
        lambda packets, host="127.0.0.1", port=8000: seen.update(host=host, port=port),
    )
    run_cli(monkeypatch, "dashboard", session_csv, "--host", "0.0.0.0", "--port", "9001")
    assert seen == {"host": "0.0.0.0", "port": 9001}


def test_dashboard_live_dispatch(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "serve_live", lambda **kw: seen.update(kw))
    run_cli(monkeypatch, "dashboard", "--live", "--udp-port", "9999")
    assert seen["udp_port"] == 9999


def test_dashboard_without_log_or_live_fails(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["fth", "dashboard"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2  # argparse usage error


def test_bare_fth_launches_web_app(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "serve_live", lambda **kw: seen.update(kw))
    run_cli(monkeypatch)  # no subcommand
    assert seen == {"host": "127.0.0.1", "port": 8000, "udp_port": 20777}


def test_bare_fth_flag_passthrough(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "serve_live", lambda **kw: seen.update(kw))
    run_cli(monkeypatch, "--port", "9000", "--udp-port", "30000")
    assert seen == {"host": "127.0.0.1", "port": 9000, "udp_port": 30000}


def test_fth_live_still_terminal_readout(monkeypatch):
    seen = {}

    def fake_listen(host, port):
        seen.update(host=host, port=port)
        return iter(())

    monkeypatch.setattr(cli, "listen", fake_listen)
    run_cli(monkeypatch, "live")
    assert seen == {"host": "127.0.0.1", "port": 20777}


def test_example_report_matches_code():
    """examples/report.txt must be exactly what the current code produces."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    with open(root / "examples/session.csv", newline="") as f:
        packets = [p for p in cli.load_csv(f) if p.is_race_on]
    expected = cli.build_report(packets)
    assert (root / "examples/report.txt").read_text() == expected
