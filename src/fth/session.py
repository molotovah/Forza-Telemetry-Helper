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

# Unit handling: per the official Data Out docs, Speed is explicitly "meters
# per second", Power "watts", Torque "newton-meters" — always SI, unconditionally,
# regardless of any in-game display/region/language setting (there is no
# imperial wire format). TireTemp's unit is undocumented there, but every
# independently-validated FH telemetry project agrees it's always Fahrenheit
# on the wire (e.g. ClickClickMedia/Forza-6-telemetry's packet.py: "TireTemp*
# degrees Fahrenheit"). So this is a fixed, unconditional conversion — not a
# detected or configurable one.


def _kmh(p: TelemetryPacket) -> float:
    return p.speed * 3.6


def _dt_label(dt: int) -> str:
    return ("FWD", "RWD", "AWD")[dt] if dt in (_DT_FWD, _DT_RWD, _DT_AWD) else "?"


def normalize_units(pkt: TelemetryPacket) -> TelemetryPacket:
    """Copy of `pkt` with TireTemp* converted from the wire's Fahrenheit to
    Celsius. Speed/Power/Torque are left untouched — always SI on the wire."""

    def f_to_c(t: float) -> float:
        return (t - 32.0) * 5.0 / 9.0

    return replace(
        pkt,
        tire_temp_front_left=f_to_c(pkt.tire_temp_front_left),
        tire_temp_front_right=f_to_c(pkt.tire_temp_front_right),
        tire_temp_rear_left=f_to_c(pkt.tire_temp_rear_left),
        tire_temp_rear_right=f_to_c(pkt.tire_temp_rear_right),
    )


def normalize_session(packets: Iterable[TelemetryPacket]) -> list[TelemetryPacket]:
    """Apply normalize_units to a whole session — the entry point callers
    should use everywhere packets are summarized, displayed or sent to the AI."""
    return [normalize_units(p) for p in packets]


# Display units: a user preference (config.units, "metric"/"imperial"), fully
# separate from the wire normalization above. Everything internal (packets,
# SessionSummary) always stays canonical metric/Celsius; these convert only
# at the point numbers are formatted for a report or a UI. Covers the
# quantities Forza itself measures and that plausibly differ by convention:
# speed, distance, tire temp, tire pressure (tuning.py), power, torque.
_KMH_TO_MPH = 0.621371
_KM_TO_MI = 0.621371
_KW_TO_HP = 1.341022
_NM_TO_LBFT = 0.737562


def disp_speed(kmh: float, units: str) -> float:
    return kmh * _KMH_TO_MPH if units == "imperial" else kmh


def disp_distance(km: float, units: str) -> float:
    return km * _KM_TO_MI if units == "imperial" else km


def disp_temp(c: float, units: str) -> float:
    return c * 9.0 / 5.0 + 32.0 if units == "imperial" else c


def disp_power(kw: float, units: str) -> float:
    return kw * _KW_TO_HP if units == "imperial" else kw


def disp_torque(nm: float, units: str) -> float:
    return nm * _NM_TO_LBFT if units == "imperial" else nm


def speed_unit(units: str) -> str:
    return "mph" if units == "imperial" else "km/h"


def distance_unit(units: str) -> str:
    return "mi" if units == "imperial" else "km"


def temp_unit(units: str) -> str:
    return "F" if units == "imperial" else "C"


def power_unit(units: str) -> str:
    return "hp" if units == "imperial" else "kW"


def torque_unit(units: str) -> str:
    return "lb-ft" if units == "imperial" else "Nm"


def pressure_unit(units: str) -> str:
    return "psi" if units == "imperial" else "bar"


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


_BALANCE_LABEL = {
    "en": {
        "understeer-biased": "understeer-biased",
        "oversteer-biased": "oversteer-biased",
        "neutral": "neutral",
    },
    "fr": {
        "understeer-biased": "sous-vireur",
        "oversteer-biased": "survireur",
        "neutral": "neutre",
    },
}

# balance_hint stays a stable English code on SessionSummary (a data value,
# not display text) — only format_report() localizes it, via this table.
_R = {
    "en": {
        "header": "=== Session summary ===",
        "samples": "samples {samples}  duration {duration:.1f}s  distance {distance:.2f}{du}",
        "laps": "laps {laps}  best lap {best_lap:.2f}s",
        "speed": "speed: avg {avg:.1f} {u}, max {max:.1f} {u}",
        "redline_overlap": (
            "time at redline: {redline:.1f}%  brake/throttle overlap: {overlap:.1f}%"
        ),
        "grip_loss": "grip loss: front {front:.1f}% vs rear {rear:.1f}%  ({hint})",
        "tire_temp": (
            "tire temps avg {tu}: front {front:.1f} / rear {rear:.1f}, hottest {hottest:.1f}"
        ),
        "susp": "max suspension travel m: front {front:.3f} / rear {rear:.3f}",
        "power": "peak power {power:.0f} {pu}  peak torque {torque:.0f} {tqu}",
        "drivetrain": (
            "drivetrain {dt}  wheelspin {spin:.1f}%  brake lockup f/r {lf:.1f}%/{lr:.1f}%"
        ),
        "coast": "coast oversteer {pct:.1f}%",
        "hs_grip": "grip loss at >= {thresh:.0f} {u}: front {front:.1f}% / rear {rear:.1f}%",
        "per_lap_header": "=== Per-lap breakdown ===",
        "per_lap_line": (
            "lap {n}: avg {avg:.1f} {u} max {max:.1f}  grip loss f/r {front:.0f}%/{rear:.0f}%"
            "  redline {redline:.0f}%"
        ),
    },
    "fr": {
        "header": "=== Résumé de la session ===",
        "samples": "échantillons {samples}  durée {duration:.1f}s  distance {distance:.2f}{du}",
        "laps": "tours {laps}  meilleur tour {best_lap:.2f}s",
        "speed": "vitesse : moy. {avg:.1f} {u}, max {max:.1f} {u}",
        "redline_overlap": (
            "temps à la limite : {redline:.1f}%  chevauchement frein/accél. : {overlap:.1f}%"
        ),
        "grip_loss": "perte d'adhérence : avant {front:.1f}% contre arrière {rear:.1f}%  ({hint})",
        "tire_temp": (
            "temp. pneus moy. {tu} : avant {front:.1f} / arrière {rear:.1f}, max {hottest:.1f}"
        ),
        "susp": "débattement suspension max m : avant {front:.3f} / arrière {rear:.3f}",
        "power": "puissance max {power:.0f} {pu}  couple max {torque:.0f} {tqu}",
        "drivetrain": (
            "transmission {dt}  patinage {spin:.1f}%  blocage freins av/ar {lf:.1f}%/{lr:.1f}%"
        ),
        "coast": "survirage en roue libre {pct:.1f}%",
        "hs_grip": (
            "perte d'adhérence à >= {thresh:.0f} {u} : avant {front:.1f}% / arrière {rear:.1f}%"
        ),
        "per_lap_header": "=== Détail par tour ===",
        "per_lap_line": (
            "tour {n} : moy. {avg:.1f} {u} max {max:.1f}"
            "  perte d'adhérence av/ar {front:.0f}%/{rear:.0f}%  limite {redline:.0f}%"
        ),
    },
}


def _report_lang(lang: str) -> str:
    return lang if lang in _R else "en"


def format_per_lap(
    laps: list[tuple[int, SessionSummary]], lang: str = "en", units: str = "metric"
) -> str:
    """Per-lap table; empty until there are at least two laps to compare."""
    if len(laps) < 2:
        return ""
    r = _R[_report_lang(lang)]
    u = speed_unit(units)
    lines = [r["per_lap_header"]]
    for n, s in laps:
        lines.append(
            r["per_lap_line"].format(
                n=n,
                avg=disp_speed(s.avg_speed_kmh, units),
                max=disp_speed(s.max_speed_kmh, units),
                front=s.grip_loss_front_pct,
                rear=s.grip_loss_rear_pct,
                redline=s.redline_pct,
                u=u,
            )
        )
    return "\n".join(lines)


def format_report(s: SessionSummary, lang: str = "en", units: str = "metric") -> str:
    lang = _report_lang(lang)
    r = _R[lang]
    hint = _BALANCE_LABEL[lang].get(s.balance_hint, s.balance_hint)
    u, du = speed_unit(units), distance_unit(units)
    tu, pu, tqu = temp_unit(units), power_unit(units), torque_unit(units)
    return "\n".join(
        [
            r["header"],
            r["samples"].format(
                samples=s.samples,
                duration=s.duration_s,
                distance=disp_distance(s.distance_km, units),
                du=du,
            ),
            r["laps"].format(laps=s.laps, best_lap=s.best_lap_s),
            r["speed"].format(
                avg=disp_speed(s.avg_speed_kmh, units), max=disp_speed(s.max_speed_kmh, units), u=u
            ),
            r["redline_overlap"].format(redline=s.redline_pct, overlap=s.pedal_overlap_pct),
            r["grip_loss"].format(
                front=s.grip_loss_front_pct, rear=s.grip_loss_rear_pct, hint=hint
            ),
            r["tire_temp"].format(
                front=disp_temp(s.tire_temp_front_avg_c, units),
                rear=disp_temp(s.tire_temp_rear_avg_c, units),
                hottest=disp_temp(s.tire_temp_max_c, units),
                tu=tu,
            ),
            r["susp"].format(front=s.susp_travel_front_max_m, rear=s.susp_travel_rear_max_m),
            r["power"].format(
                power=disp_power(s.max_power_kw, units),
                torque=disp_torque(s.max_torque_nm, units),
                pu=pu,
                tqu=tqu,
            ),
            r["drivetrain"].format(
                dt=_dt_label(s.drivetrain_type),
                spin=s.wheelspin_pct,
                lf=s.lockup_front_pct,
                lr=s.lockup_rear_pct,
            ),
            r["coast"].format(pct=s.coast_oversteer_pct),
            r["hs_grip"].format(
                thresh=disp_speed(_HS_SPEED_KMH, units),
                front=s.hs_grip_loss_front_pct,
                rear=s.hs_grip_loss_rear_pct,
                u=u,
            ),
        ]
    )
