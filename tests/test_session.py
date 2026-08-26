import io
from dataclasses import astuple

import pytest

from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket
from fth.session import CsvRecorder, format_report, load_csv, summarize


def _packets(n: int = 10) -> list[TelemetryPacket]:
    """n packets engineered for exact metric math (see test_summarize)."""
    ps = []
    for i in range(n):
        if i % 2 == 0:
            slip_fl, slip_rl = 1.5, 0.2  # front grip loss
            speed = 50.0
        else:
            slip_fl, slip_rl = 0.2, 1.5  # rear grip loss
            speed = 60.0
        ps.append(
            TelemetryPacket.from_bytes(
                make_packet(
                    speed=speed,
                    current_race_time=10.0 + i,
                    distance_traveled=1000.0 * i,
                    lap_number=2,
                    best_lap=95.5,
                    tire_combined_slip_front_left=slip_fl,
                    tire_combined_slip_rear_left=slip_rl,
                    engine_max_rpm=8000.0,
                    current_engine_rpm=7900.0 if i < 3 else 5000.0,  # 3/10 at redline
                    accel=255 if i < 2 else 0,  # 2/10 full throttle
                    brake=255 if i < 2 else 0,  # same 2/10 braking
                    power=200000.0,
                    torque=400.0,
                )
            )
        )
    return ps


def test_csv_roundtrip():
    ps = _packets(4)
    buf = io.StringIO()
    rec = CsvRecorder(buf)
    for p in ps:
        rec.write(p)
    buf.seek(0)
    loaded = list(load_csv(buf))
    assert len(loaded) == len(ps)
    assert astuple(loaded[2]) == astuple(ps[2])


def test_csv_header_written_once():
    buf = io.StringIO()
    rec = CsvRecorder(buf)
    rec.write(_packets(1)[0])
    rec.write(_packets(1)[0])
    assert buf.getvalue().count("\n") == 3  # header + 2 rows


def test_summarize_math():
    s = summarize(_packets(10))
    assert s.samples == 10
    assert s.duration_s == pytest.approx(9.0)
    assert s.distance_km == pytest.approx(9.0)
    assert s.laps == 2
    assert s.best_lap_s == pytest.approx(95.5)
    assert s.max_speed_kmh == pytest.approx(60 * 3.6)
    assert s.avg_speed_kmh == pytest.approx((50 * 5 + 60 * 5) / 10 * 3.6)
    assert s.redline_pct == pytest.approx(30.0)
    assert s.pedal_overlap_pct == pytest.approx(20.0)
    assert s.grip_loss_front_pct == pytest.approx(50.0)
    assert s.grip_loss_rear_pct == pytest.approx(50.0)
    assert s.balance_hint == "neutral"
    assert s.max_power_kw == pytest.approx(200.0)
    assert s.max_torque_nm == pytest.approx(400.0)


def test_balance_hints():
    def biased(fl_slip: float, rl_slip: float) -> str:
        pkt = TelemetryPacket.from_bytes(
            make_packet(tire_combined_slip_front_left=fl_slip, tire_combined_slip_rear_left=rl_slip)
        )
        return summarize([pkt]).balance_hint

    assert biased(1.5, 0.2) == "understeer-biased"
    assert biased(0.2, 1.5) == "oversteer-biased"
    assert biased(0.2, 0.2) == "neutral"


def test_empty_session_raises():
    with pytest.raises(ValueError):
        summarize([])


def test_report_render():
    s = summarize(_packets(3))
    text = format_report(s)
    assert "Session summary" in text
    assert f"front {s.grip_loss_front_pct:.1f}%" in text
    assert f"{s.max_torque_nm:.0f} Nm" in text
