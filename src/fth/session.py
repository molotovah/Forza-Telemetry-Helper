"""Session recording (CSV) and feature extraction.

A "session" is any iterable of TelemetryPacket captured while driving.
Metrics follow the official field semantics: |tire_combined_slip| > 1.0
means grip loss; normalized suspension travel 0 = max stretch, 1 = max
compression; inputs are 0-255.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import IO, Iterable, Iterator

from fth.ingest import _INT_NAMES, _NAMES, TelemetryPacket

_REDLINE_RATIO = 0.95
_GRIP_LOSS_THRESHOLD = 1.0
_PEDAL_THRESHOLD = 51  # ~20% of 255
_BALANCE_TOLERANCE_PTS = 5.0


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
    max_power_kw: float
    max_torque_nm: float


def summarize(packets: Iterable[TelemetryPacket]) -> SessionSummary:
    ps = list(packets)
    if not ps:
        raise ValueError("cannot summarize an empty session")

    speeds_kmh = [p.speed * 3.6 for p in ps]

    def grip_loss_pct(front: bool) -> float:
        attr = "tire_combined_slip_" + ("front_left" if front else "rear_left")
        attr_r = "tire_combined_slip_" + ("front_right" if front else "rear_right")
        lost = sum(
            1
            for p in ps
            if abs(getattr(p, attr)) > _GRIP_LOSS_THRESHOLD
            or abs(getattr(p, attr_r)) > _GRIP_LOSS_THRESHOLD
        )
        return 100.0 * lost / len(ps)

    front_loss = grip_loss_pct(front=True)
    rear_loss = grip_loss_pct(front=False)
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
        max_power_kw=max(p.power for p in ps) / 1000,
        max_torque_nm=max(p.torque for p in ps),
    )


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
        ]
    )
