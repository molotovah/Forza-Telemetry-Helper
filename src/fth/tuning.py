"""Rules-based setup advisor: maps session metrics to FH6 tuning-menu changes.

The Data Out stream is one-way — current tune values are unknown, so every
change is RELATIVE to the user's current setup. Steps are starting points
for iteration, not absolutes. Thresholds live in constants below; tune them.
"""

from __future__ import annotations

from dataclasses import dataclass

from fth.session import SessionSummary

_HOT_TIRE_C = 100.0
_COLD_TIRE_C = 70.0
_BOTTOM_OUT_NORM = 0.97  # normalized suspension travel, 1.0 = fully compressed
_SOFT_SUSPENSION_NORM = 0.55
_MIN_SPEED_FOR_SUSP_RULE_KMH = 30.0  # ignore suspension while crawling/jumping
_REDLINE_HIGH_PCT = 40.0  # time spent >= 95% of max RPM
_REDLINE_LOW_PCT = 10.0
_BALANCE_TOLERANCE_PTS = 5.0
_LOCKUP_HIGH_PCT = 10.0  # % of samples braking with a wheel nearly stopped
_SPIN_HIGH_PCT = 10.0  # % of samples with driven-axle slip under power
_COAST_OVERSTEER_PCT = 10.0  # % of coasting samples with rear slip
_HS_LOSS_DIFF_PTS = 8.0  # high-speed grip-loss gap between axles -> aero
_AERO_MIN_SPEED_KMH = 150.0  # only advise wings once speeds get meaningful


@dataclass(slots=True)
class Suggestion:
    """One relative change to apply in FH6's tuning menu."""

    parameter: str
    change: str
    reason: str


def suggest(s: SessionSummary) -> list[Suggestion]:
    out: list[Suggestion] = []

    # --- Tires: pressure steers operating temperature ---
    for axle, avg in (
        ("front", s.tire_temp_front_avg_c),
        ("rear", s.tire_temp_rear_avg_c),
    ):
        if avg >= _HOT_TIRE_C:
            out.append(
                Suggestion(
                    f"Tire pressure ({axle})",
                    "-2 psi",
                    f"avg {axle} tire temp {avg:.0f} C is above {_HOT_TIRE_C:.0f} C",
                )
            )
        elif 0 < avg <= _COLD_TIRE_C:
            out.append(
                Suggestion(
                    f"Tire pressure ({axle})",
                    "+2 psi",
                    f"avg {axle} tire temp {avg:.0f} C never reaches {_COLD_TIRE_C:.0f} C",
                )
            )

    # --- Alignment & anti-roll bars: fix handling balance ---
    if s.grip_loss_front_pct - s.grip_loss_rear_pct > _BALANCE_TOLERANCE_PTS:
        out.append(
            Suggestion(
                "Anti-roll bar (front)",
                "-2",
                f"excess front grip loss ({s.grip_loss_front_pct:.0f}%"
                f" vs {s.grip_loss_rear_pct:.0f}% rear)",
            )
        )
        out.append(Suggestion("Camber (front)", "+0.3 deg", "front axle slides before the rear"))
    elif s.grip_loss_rear_pct - s.grip_loss_front_pct > _BALANCE_TOLERANCE_PTS:
        out.append(
            Suggestion(
                "Anti-roll bar (rear)",
                "-2",
                f"excess rear grip loss ({s.grip_loss_rear_pct:.0f}%"
                f" vs {s.grip_loss_front_pct:.0f}% front)",
            )
        )
        out.append(Suggestion("Camber (rear)", "+0.3 deg", "rear axle slides before the front"))

    # --- Suspension: spring stiffness from observed travel usage ---
    for axle, peak in (
        ("front", s.susp_travel_front_max_norm),
        ("rear", s.susp_travel_rear_max_norm),
    ):
        if peak >= _BOTTOM_OUT_NORM:
            out.append(
                Suggestion(
                    f"Spring stiffness ({axle})",
                    "+stiffen",
                    f"{axle} suspension bottoms out (travel peaked at {peak * 100:.0f}%)",
                )
            )
        elif 0 < peak <= _SOFT_SUSPENSION_NORM and s.avg_speed_kmh >= _MIN_SPEED_FOR_SUSP_RULE_KMH:
            out.append(
                Suggestion(
                    f"Spring stiffness ({axle})",
                    "-soften",
                    f"{axle} suspension barely used (travel peaked at {peak * 100:.0f}%)",
                )
            )

    # --- Gearing: final drive vs time spent on the limiter ---
    if s.redline_pct >= _REDLINE_HIGH_PCT:
        out.append(
            Suggestion(
                "Final drive",
                "-lower number (longer)",
                f"on the limiter {s.redline_pct:.0f}% of the session",
            )
        )
    elif s.redline_pct <= _REDLINE_LOW_PCT and s.avg_speed_kmh >= 50:
        out.append(
            Suggestion(
                "Final drive",
                "+higher number (shorter)",
                f"engine rarely stretched ({s.redline_pct:.0f}% at redline,"
                f" avg {s.avg_speed_kmh:.0f} km/h)",
            )
        )

    # --- Brakes: bias/pressure from wheel lockup ---
    if s.lockup_front_pct >= _LOCKUP_HIGH_PCT and s.lockup_front_pct > s.lockup_rear_pct:
        out.append(
            Suggestion(
                "Brake pressure",
                "-reduce",
                f"front wheels lock under braking ({s.lockup_front_pct:.0f}% of samples)",
            )
        )
        out.append(Suggestion("Brake balance", "-rearward", "front axle locks first"))
    elif s.lockup_rear_pct >= _LOCKUP_HIGH_PCT and s.lockup_rear_pct > s.lockup_front_pct:
        out.append(
            Suggestion(
                "Brake balance",
                "+forward",
                f"rear wheels lock first ({s.lockup_rear_pct:.0f}% of samples)",
            )
        )

    # --- Differential: acceleration locking from driven-wheel spin ---
    if s.wheelspin_pct >= _SPIN_HIGH_PCT:
        out.append(
            Suggestion(
                "Differential (acceleration)",
                "+stiffen",
                f"driven wheels spin under power {s.wheelspin_pct:.0f}% of the session",
            )
        )

    # --- Differential: too much decel locking makes the rear step out on lift ---
    if s.coast_oversteer_pct >= _COAST_OVERSTEER_PCT:
        out.append(
            Suggestion(
                "Differential (deceleration)",
                "soften",
                f"rear slides while off throttle ({s.coast_oversteer_pct:.0f}% of samples)",
            )
        )

    # --- Aero: downforce where the car runs out of grip at high speed ---
    if s.max_speed_kmh >= _AERO_MIN_SPEED_KMH:
        if s.hs_grip_loss_front_pct - s.hs_grip_loss_rear_pct >= _HS_LOSS_DIFF_PTS:
            out.append(
                Suggestion(
                    "Aero (front)",
                    "+downforce",
                    f"front loses grip at speed ({s.hs_grip_loss_front_pct:.0f}%"
                    f" vs {s.hs_grip_loss_rear_pct:.0f}% rear)",
                )
            )
        elif s.hs_grip_loss_rear_pct - s.hs_grip_loss_front_pct >= _HS_LOSS_DIFF_PTS:
            out.append(
                Suggestion(
                    "Aero (rear)",
                    "+downforce",
                    f"rear loses grip at speed ({s.hs_grip_loss_rear_pct:.0f}%"
                    f" vs {s.hs_grip_loss_front_pct:.0f}% front)",
                )
            )

    return out


def format_suggestions(items: list[Suggestion]) -> str:
    if not items:
        return "=== Suggested tuning changes ===\nnone — setup looks balanced for this session."
    lines = ["=== Suggested tuning changes (relative to your current setup) ==="]
    lines += [f"* {it.parameter}: {it.change}\n    reason: {it.reason}" for it in items]
    return "\n".join(lines)
