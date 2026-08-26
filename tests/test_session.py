import io
from dataclasses import astuple

import pytest

from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket
from fth.session import (
    CsvRecorder,
    format_per_lap,
    format_report,
    load_csv,
    normalize_session,
    normalize_units,
    summarize,
    summarize_per_lap,
)


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


def test_summarize_per_lap():
    ps = [
        TelemetryPacket.from_bytes(
            make_packet(speed=50.0, current_race_time=float(i), lap_number=n)
        )
        for i, n in enumerate([0, 0, 1, 1])
    ]
    laps = summarize_per_lap(ps)
    assert [n for n, _ in laps] == [0, 1]
    assert all(s.samples == 2 for _, s in laps)


def test_format_per_lap_needs_two_laps():
    ps = [TelemetryPacket.from_bytes(make_packet(lap_number=n)) for n in (0, 0)]
    assert format_per_lap(summarize_per_lap(ps)) == ""
    ps.append(TelemetryPacket.from_bytes(make_packet(lap_number=1)))
    text = format_per_lap(summarize_per_lap(ps))
    assert "Per-lap breakdown" in text
    assert "lap 0:" in text and "lap 1:" in text


def test_extended_metrics():
    """RWD car: half the samples spinning under power, a quarter locking fronts,
    fast samples losing front grip."""
    ps = []
    for i in range(8):
        kw = dict(
            drivetrain_type=1,  # RWD
            speed=40.0,
        )
        if i < 4:  # wheelspin: full throttle + rear slip ratio + forward g
            kw.update(accel=255, tire_slip_ratio_rear_left=0.9, acceleration_z=3.0)
        elif i < 6:  # brake lockup: braking + one stopped front wheel at speed
            kw.update(
                brake=255,
                accel=0,
                wheel_rotation_speed_front_left=0.5,
                wheel_rotation_speed_front_right=150.0,
                wheel_rotation_speed_rear_left=200.0,
                wheel_rotation_speed_rear_right=200.0,
            )
        else:  # high-speed band with front grip loss only
            kw.update(speed=40.0, tire_combined_slip_front_left=1.4, accel=0)
        ps.append(TelemetryPacket.from_bytes(make_packet(**kw)))

    s = summarize(ps)
    assert s.drivetrain_type == 1
    assert s.wheelspin_pct == pytest.approx(50.0)
    assert s.lockup_front_pct == pytest.approx(25.0)
    assert s.lockup_rear_pct == pytest.approx(0.0)
    # every packet runs at 40 m/s = 144 km/h, inside the >= 120 km/h band;
    # only the last two lose front grip
    assert s.hs_grip_loss_front_pct == pytest.approx(25.0)
    assert s.hs_grip_loss_rear_pct == pytest.approx(0.0)


def test_wheelspin_needs_forward_acceleration():
    """Corner-exit scrub without longitudinal g must not read as wheelspin."""
    ps = [
        TelemetryPacket.from_bytes(
            make_packet(
                accel=255,
                tire_slip_ratio_rear_left=0.9,
                acceleration_z=0.2,
                drivetrain_type=1,
            )
        )
        for _ in range(3)
    ]
    assert summarize(ps).wheelspin_pct == 0.0


def test_lockup_is_relative_to_fastest_wheel():
    """All four wheels slow but equal = normal braking, nobody is locked."""
    ps = [
        TelemetryPacket.from_bytes(
            make_packet(
                brake=255,
                speed=40.0,
                wheel_rotation_speed_front_left=30.0,
                wheel_rotation_speed_front_right=30.0,
                wheel_rotation_speed_rear_left=30.0,
                wheel_rotation_speed_rear_right=30.0,
            )
        )
    ]
    s = summarize(ps)
    assert s.lockup_front_pct == 0.0
    assert s.lockup_rear_pct == 0.0


def test_coast_oversteer_counts_only_when_coasting():
    def pct(**kw):
        base = {"tire_combined_slip_rear_left": 1.5, "accel": 0}
        base.update(kw)
        return summarize([TelemetryPacket.from_bytes(make_packet(**base))]).coast_oversteer_pct

    assert pct() == pytest.approx(100.0)  # no pedals -> coasting
    assert pct(accel=255) == 0.0
    assert pct(brake=255) == 0.0


def test_hs_grip_loss_empty_band_is_zero():
    s = summarize([TelemetryPacket.from_bytes(make_packet(speed=20.0))])  # 72 km/h
    assert s.hs_grip_loss_front_pct == 0.0
    assert s.hs_grip_loss_rear_pct == 0.0


def test_normalize_units_converts_tire_temp_f_to_c():
    pkt = TelemetryPacket.from_bytes(
        make_packet(
            tire_temp_front_left=212.0,  # 100 C
            tire_temp_front_right=32.0,  # 0 C
            tire_temp_rear_left=141.0,  # ~60.6 C — the value from the reported bug
            tire_temp_rear_right=98.6,  # ~37 C
        )
    )
    n = normalize_units(pkt)
    assert n.tire_temp_front_left == pytest.approx(100.0)
    assert n.tire_temp_front_right == pytest.approx(0.0)
    assert n.tire_temp_rear_left == pytest.approx(60.56, abs=0.01)
    assert n.tire_temp_rear_right == pytest.approx(37.0, abs=0.01)


def test_normalize_units_never_touches_speed_power_torque():
    """Speed/Power/Torque are explicitly SI in the official Data Out docs —
    always, unconditionally. There is no imperial wire format for them."""
    pkt = TelemetryPacket.from_bytes(make_packet(speed=55.5, power=300000.0, torque=450.0))
    n = normalize_units(pkt)
    assert n.speed == pkt.speed
    assert n.power == pkt.power
    assert n.torque == pkt.torque


def test_normalize_session_converts_every_packet_unconditionally():
    ps = [TelemetryPacket.from_bytes(make_packet(tire_temp_front_left=212.0)) for _ in range(3)]
    normalized = normalize_session(ps)
    assert all(p.tire_temp_front_left == pytest.approx(100.0) for p in normalized)


def test_config_stores_lang(monkeypatch, tmp_path):
    from fth import config

    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "config.json"))
    config.save(lang="fr")
    assert config.load()["lang"] == "fr"
