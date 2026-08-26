"""Session recording (CSV) and feature extraction.

A "session" is any iterable of TelemetryPacket captured while driving.
Metrics follow the official field semantics: |tire_combined_slip| > 1.0
means grip loss; normalized suspension travel 0 = max stretch, 1 = max
compression; inputs are 0-255.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from statistics import mode
from typing import IO, Iterable, Iterator

from fth.ingest import _INT_NAMES, _NAMES, TelemetryPacket

_REDLINE_RATIO = 0.95
_GRIP_LOSS_THRESHOLD = 1.0
_PEDAL_THRESHOLD = 51  # ~20% of 255
_BALANCE_TOLERANCE_PTS = 5.0

# Extended-metric thresholds (plausible starting points; calibrate against
# real sessions before trusting them blindly).
_DT_FWD, _DT_RWD, _DT_AWD = 0, 1, 2  # DrivetrainType per official FH6 docs
_LOCKUP_RATIO = 0.25  # wheel spinning below 25% of the fastest wheel = locked
_LOCKUP_MIN_SPEED_KMH = 30.0
_SPIN_SLIP_RATIO = 0.5  # driven-wheel slip under power = wheelspin
_SPIN_MIN_ACCEL_MPS2 = 1.0  # forward g required, else it's corner-exit scrub
_HS_SPEED_KMH = 120.0  # aero-relevant speed band

# Unit handling: the wire format is documented in SI units, but a game running
# with imperial display units may stream converted values instead. Everything
# downstream (metrics, rules, CSVs) expects SI, so convert once at the edge.
# ponytail: detection is a plausibility heuristic, not a spec — verify against
# a real localized FH6 install before trusting "auto" (see TODO.md).
_MPH_TO_MS = 0.44704
_HP_TO_W = 745.699872
_LBFT_TO_NM = 1.35581795
_DETECT_MIN_SAMPLES = 20
_DETECT_TEMP = 110.0  # p95 hottest-tire above this reads like F, not C
_DETECT_SPEED = 75.0  # p95 speed above this is implausible m/s -> mph


def _kmh(p: TelemetryPacket) -> float:
    return p.speed * 3.6


def _dt_label(dt: int) -> str:
    return ("FWD", "RWD", "AWD")[dt] if dt in (_DT_FWD, _DT_RWD, _DT_AWD) else "?"


def normalize_units(pkt: TelemetryPacket, system: str) -> TelemetryPacket:
    """Copy of `pkt` converted to SI; identity for "metric".

    "imperial" converts tire temps (F->C), speed (mph->m/s), power (hp->W)
    and torque (lb-ft->Nm). Every other field is unit-free or already SI.
    """
    if system != "imperial":
        return pkt

    def f_to_c(t: float) -> float:
        return (t - 32.0) * 5.0 / 9.0

    return replace(
        pkt,
        tire_temp_front_left=f_to_c(pkt.tire_temp_front_left),
        tire_temp_front_right=f_to_c(pkt.tire_temp_front_right),
        tire_temp_rear_left=f_to_c(pkt.tire_temp_rear_left),
        tire_temp_rear_right=f_to_c(pkt.tire_temp_rear_right),
        speed=pkt.speed * _MPH_TO_MS,
        power=pkt.power * _HP_TO_W,
        torque=pkt.torque * _LBFT_TO_NM,
    )


def detect_units(packets: Iterable[TelemetryPacket]) -> str:
    """Guess "metric" or "imperial" from physical plausibility anchors.

    Fires only when BOTH anchors look imperial on enough samples:
    p95 of per-packet hottest tire temp above ~110 and p95 speed above
    ~75 (implausible as m/s at sustained pace, natural in mph).
    """
    ps = list(packets)
    if len(ps) < _DETECT_MIN_SAMPLES:
        return "metric"

    def p95(values: list[float]) -> float:
        return sorted(values)[int(len(values) * 0.95)]

    hot = p95(
        [
            max(
                p.tire_temp_front_left,
                p.tire_temp_front_right,
                p.tire_temp_rear_left,
                p.tire_temp_rear_right,
            )
            for p in ps
        ]
    )
    fast = p95([p.speed for p in ps])
    return "imperial" if hot > _DETECT_TEMP and fast > _DETECT_SPEED else "metric"


def normalize_session(
    packets: Iterable[TelemetryPacket], units: str = "auto"
) -> list[TelemetryPacket]:
    """Apply normalize_units to a whole session; "auto" runs detect_units first.

    This is the actual entry point callers should use — detect_units/
    normalize_units alone don't do anything unless something calls them.
    """
    ps = list(packets)
    system = units if units in ("metric", "imperial") else detect_units(ps)
    return [normalize_units(p, system) for p in ps]


class CsvRecorder:
    """Writes packets to a CSV stream. Open the stream with newline="".

    The header row is written lazily on the first packet.
    """

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self._writer = csv.writer(stream)
        self._header_written = False

    def write(self, pkt: TelemetryPacket) -> None:
        if not self._header_written:
            self._writer.writerow(_NAMES)
            self._header_written = True
        self._writer.writerow([getattr(pkt, name) for name in _NAMES])

    def flush(self) -> None:
        self._stream.flush()


def load_csv(stream: IO[str]) -> Iterator[TelemetryPacket]:
    """Read back packets written by CsvRecorder."""
    casters = {name: int if name in _INT_NAMES else float for name in _NAMES}
    for row in csv.DictReader(stream):
        yield TelemetryPacket(**{name: casters[name](value) for name, value in row.items()})


@dataclass(slots=True)
class SessionSummary:
    samples: int
    duration_s: float
    distance_km: float
    laps: int
    best_lap_s: float
    max_speed_kmh: float
    avg_speed_kmh: float
    redline_pct: float
    pedal_overlap_pct: float
    grip_loss_front_pct: float
    grip_loss_rear_pct: float
    balance_hint: str  # "understeer-biased" / "oversteer-biased" / "neutral"
    tire_temp_front_avg_c: float
    tire_temp_rear_avg_c: float
    tire_temp_max_c: float
    susp_travel_front_max_m: float
    susp_travel_rear_max_m: float
    susp_travel_front_max_norm: float  # 0..1, 1 = fully compressed
    susp_travel_rear_max_norm: float
    max_power_kw: float
    max_torque_nm: float
    drivetrain_type: int  # 0 FWD, 1 RWD, 2 AWD (modal value of the session)
    lockup_front_pct: float  # braking samples with front wheels nearly stopped
    lockup_rear_pct: float
    wheelspin_pct: float  # driven-axle slip ratio under throttle
    hs_grip_loss_front_pct: float  # grip loss at >= _HS_SPEED_KMH only
    hs_grip_loss_rear_pct: float
    coast_oversteer_pct: float  # rear slip while off both pedals


def summarize(packets: Iterable[TelemetryPacket]) -> SessionSummary:
    ps = list(packets)
    if not ps:
        raise ValueError("cannot summarize an empty session")

    speeds_kmh = [p.speed * 3.6 for p in ps]

    def axle_grip_loss_pct(axle: str, pool: list[TelemetryPacket]) -> float:
        if not pool:
            return 0.0
        lost = sum(
            1
            for p in pool
            if abs(getattr(p, f"tire_combined_slip_{axle}_left")) > _GRIP_LOSS_THRESHOLD
            or abs(getattr(p, f"tire_combined_slip_{axle}_right")) > _GRIP_LOSS_THRESHOLD
        )
        return 100.0 * lost / len(pool)

    front_loss = axle_grip_loss_pct("front", ps)
    rear_loss = axle_grip_loss_pct("rear", ps)

    fast = [p for p in ps if _kmh(p) >= _HS_SPEED_KMH]

    def lockup_pct(axle: str) -> float:
        """Relative detection: a wheel turning well below the fastest wheel
        while braking is locked, regardless of tire radius."""
        locked = sum(
            1
            for p in ps
            if p.brake >= _PEDAL_THRESHOLD
            and _kmh(p) >= _LOCKUP_MIN_SPEED_KMH
            and min(
                getattr(p, f"wheel_rotation_speed_{axle}_left"),
                getattr(p, f"wheel_rotation_speed_{axle}_right"),
            )
            < _LOCKUP_RATIO
            * max(
                p.wheel_rotation_speed_front_left,
                p.wheel_rotation_speed_front_right,
                p.wheel_rotation_speed_rear_left,
                p.wheel_rotation_speed_rear_right,
            )
        )
        return 100.0 * locked / len(ps)

    drivetrain = mode(p.drivetrain_type for p in ps)
    driven_axles = {
        _DT_FWD: ("front",),
        _DT_RWD: ("rear",),
        _DT_AWD: ("front", "rear"),
    }.get(drivetrain, ("front", "rear"))
    spinning = sum(
        1
        for p in ps
        if p.accel >= _PEDAL_THRESHOLD
        and p.acceleration_z > _SPIN_MIN_ACCEL_MPS2
        and any(
            getattr(p, f"tire_slip_ratio_{axle}_left") > _SPIN_SLIP_RATIO
            or getattr(p, f"tire_slip_ratio_{axle}_right") > _SPIN_SLIP_RATIO
            for axle in driven_axles
        )
    )
    coast_oversteer = sum(
        1
        for p in ps
        if p.accel < _PEDAL_THRESHOLD
        and p.brake < _PEDAL_THRESHOLD
        and (
            abs(p.tire_combined_slip_rear_left) > _GRIP_LOSS_THRESHOLD
            or abs(p.tire_combined_slip_rear_right) > _GRIP_LOSS_THRESHOLD
        )
    )

    if front_loss - rear_loss > _BALANCE_TOLERANCE_PTS:
        balance = "understeer-biased"
    elif rear_loss - front_loss > _BALANCE_TOLERANCE_PTS:
        balance = "oversteer-biased"
    else:
        balance = "neutral"

    redlined = sum(
        1
        for p in ps
        if p.engine_max_rpm > 0 and p.current_engine_rpm >= _REDLINE_RATIO * p.engine_max_rpm
    )
    overlapped = sum(1 for p in ps if p.accel >= _PEDAL_THRESHOLD and p.brake >= _PEDAL_THRESHOLD)
    race_times = [p.current_race_time for p in ps]
    best_laps = [p.best_lap for p in ps if p.best_lap > 0]

    return SessionSummary(
        samples=len(ps),
        duration_s=max(race_times) - min(race_times),
        distance_km=max(p.distance_traveled for p in ps) / 1000,
        laps=max(p.lap_number for p in ps),
        best_lap_s=min(best_laps) if best_laps else 0.0,
        max_speed_kmh=max(speeds_kmh),
        avg_speed_kmh=sum(speeds_kmh) / len(speeds_kmh),
        redline_pct=100.0 * redlined / len(ps),
        pedal_overlap_pct=100.0 * overlapped / len(ps),
        grip_loss_front_pct=front_loss,
        grip_loss_rear_pct=rear_loss,
        balance_hint=balance,
        tire_temp_front_avg_c=(
            sum(p.tire_temp_front_left + p.tire_temp_front_right for p in ps) / (2 * len(ps))
        ),
        tire_temp_rear_avg_c=(
            sum(p.tire_temp_rear_left + p.tire_temp_rear_right for p in ps) / (2 * len(ps))
        ),
        tire_temp_max_c=max(
            temp
            for p in ps
            for temp in (
                p.tire_temp_front_left,
                p.tire_temp_front_right,
                p.tire_temp_rear_left,
                p.tire_temp_rear_right,
            )
        ),
        susp_travel_front_max_m=max(
            max(p.suspension_travel_meters_front_left, p.suspension_travel_meters_front_right)
            for p in ps
        ),
        susp_travel_rear_max_m=max(
            max(p.suspension_travel_meters_rear_left, p.suspension_travel_meters_rear_right)
            for p in ps
        ),
        susp_travel_front_max_norm=max(
            max(
                p.normalized_suspension_travel_front_left,
                p.normalized_suspension_travel_front_right,
            )
            for p in ps
        ),
        susp_travel_rear_max_norm=max(
            max(p.normalized_suspension_travel_rear_left, p.normalized_suspension_travel_rear_right)
            for p in ps
        ),
        max_power_kw=max(p.power for p in ps) / 1000,
        max_torque_nm=max(p.torque for p in ps),
        drivetrain_type=drivetrain,
        lockup_front_pct=lockup_pct("front"),
        lockup_rear_pct=lockup_pct("rear"),
        wheelspin_pct=100.0 * spinning / len(ps),
        hs_grip_loss_front_pct=axle_grip_loss_pct("front", fast),
        hs_grip_loss_rear_pct=axle_grip_loss_pct("rear", fast),
        coast_oversteer_pct=100.0 * coast_oversteer / len(ps),
    )


def summarize_per_lap(packets: Iterable[TelemetryPacket]) -> list[tuple[int, SessionSummary]]:
    """One SessionSummary per observed lap_number, in lap order."""
    by_lap: dict[int, list[TelemetryPacket]] = {}
    for p in packets:
        by_lap.setdefault(p.lap_number, []).append(p)
    return [(n, summarize(ps)) for n, ps in sorted(by_lap.items())]


def format_per_lap(laps: list[tuple[int, SessionSummary]]) -> str:
    """Per-lap table; empty until there are at least two laps to compare."""
    if len(laps) < 2:
        return ""
    lines = ["=== Per-lap breakdown ==="]
    for n, s in laps:
        lines.append(
            f"lap {n}: avg {s.avg_speed_kmh:.1f} km/h max {s.max_speed_kmh:.1f}"
            f"  grip loss f/r {s.grip_loss_front_pct:.0f}%/{s.grip_loss_rear_pct:.0f}%"
            f"  redline {s.redline_pct:.0f}%"
        )
    return "\n".join(lines)


def format_report(s: SessionSummary) -> str:
    return "\n".join(
        [
            "=== Session summary ===",
            f"samples {s.samples}  duration {s.duration_s:.1f}s  distance {s.distance_km:.2f}km",
            f"laps {s.laps}  best lap {s.best_lap_s:.2f}s",
            f"speed: avg {s.avg_speed_kmh:.1f} km/h, max {s.max_speed_kmh:.1f} km/h",
            f"time at redline: {s.redline_pct:.1f}%"
            f"  brake/throttle overlap: {s.pedal_overlap_pct:.1f}%",
            (
                f"grip loss: front {s.grip_loss_front_pct:.1f}% vs rear {s.grip_loss_rear_pct:.1f}%"
                f"  ({s.balance_hint})"
            ),
            (
                f"tire temps avg C: front {s.tire_temp_front_avg_c:.1f} / rear "
                f"{s.tire_temp_rear_avg_c:.1f}, hottest {s.tire_temp_max_c:.1f}"
            ),
            (
                f"max suspension travel m: front {s.susp_travel_front_max_m:.3f} / rear "
                f"{s.susp_travel_rear_max_m:.3f}"
            ),
            f"peak power {s.max_power_kw:.0f} kW  peak torque {s.max_torque_nm:.0f} Nm",
            (
                f"drivetrain {_dt_label(s.drivetrain_type)}  wheelspin {s.wheelspin_pct:.1f}%"
                f"  brake lockup f/r {s.lockup_front_pct:.1f}%/{s.lockup_rear_pct:.1f}%"
            ),
            f"coast oversteer {s.coast_oversteer_pct:.1f}%",
            (
                f"grip loss at >= {_HS_SPEED_KMH:.0f} km/h:"
                f" front {s.hs_grip_loss_front_pct:.1f}% / rear {s.hs_grip_loss_rear_pct:.1f}%"
            ),
        ]
    )
