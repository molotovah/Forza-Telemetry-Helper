"""Rules-based setup advisor: maps session metrics to FH6 tuning-menu changes.

The Data Out stream is one-way — current tune values are unknown, so every
change is RELATIVE to the user's current setup. Steps are starting points
for iteration, not absolutes. Thresholds live in constants below; tune them.

Bilingual (en/fr): every Suggestion is built from a small per-language
template table (_T) so the parameter/change/reason text matches whichever
`lang` the caller asks for — same rule logic, just a different string table.
"""

from __future__ import annotations

from dataclasses import dataclass

from fth.session import SessionSummary, disp_temp, temp_unit

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
_DT_AWD = 2  # DrivetrainType per official FH6 docs

# --- Translation tables -----------------------------------------------------
# Keyed by lang -> key -> template ("{placeholders}" filled via .format()).
# Axle words are looked up separately (_AXLE) so the same template works for
# front/rear substitution without duplicating every reason string per axle.

_AXLE = {
    "en": {"front": "front", "rear": "rear"},
    "fr": {"front": "avant", "rear": "arrière"},
}

# Tire pressure step: tied to the `units` setting (metric/imperial), not
# `lang` — a driver can read French text and still prefer psi, or vice versa.
_PRESSURE_STEP = {
    "metric": {"hot": "-0.1 bar", "cold": "+0.1 bar"},
    "imperial": {"hot": "-2 psi", "cold": "+2 psi"},
}

_T = {
    "en": {
        "tire_pressure": "Tire pressure ({axle})",
        "tire_hot_reason": "avg {axle} tire temp {avg:.0f} {tu} is above {thresh:.0f} {tu}",
        "tire_cold_reason": "avg {axle} tire temp {avg:.0f} {tu} never reaches {thresh:.0f} {tu}",
        "arb": "Anti-roll bar ({axle})",
        "arb_change": "-2",
        "arb_front_reason": "excess front grip loss ({front:.0f}% vs {rear:.0f}% rear)",
        "arb_rear_reason": "excess rear grip loss ({rear:.0f}% vs {front:.0f}% front)",
        "camber": "Camber ({axle})",
        "camber_change": "+0.3 deg",
        "camber_front_reason": "front axle slides before the rear",
        "camber_rear_reason": "rear axle slides before the front",
        "spring": "Spring stiffness ({axle})",
        "spring_stiffen_change": "+stiffen",
        "spring_bottom_reason": "{axle} suspension bottoms out (travel peaked at {peak:.0f}%)",
        "spring_soften_change": "-soften",
        "spring_soft_reason": "{axle} suspension barely used (travel peaked at {peak:.0f}%)",
        "damping_bump": "Damping, bump ({axle})",
        "damping_bump_change": "+stiffen",
        "damping_bump_reason": (
            "{axle} suspension bottoms out (travel peaked at {peak:.0f}%) — bump damping "
            "resists the compression rate, springs alone may not be enough"
        ),
        "damping_rebound": "Damping, rebound ({axle})",
        "damping_rebound_change": "-soften",
        "damping_rebound_reason": (
            "{axle} suspension barely used (travel peaked at {peak:.0f}%) — softer rebound "
            "helps the tire stay planted through the same load transfer"
        ),
        "ride_height": "Ride height",
        "ride_height_change": "+raise",
        "ride_height_reason": (
            "both axles bottom out (front {front:.0f}%, rear {rear:.0f}%) — more static "
            "clearance may help alongside stiffer springs"
        ),
        "final_drive": "Final drive",
        "final_drive_lower_change": "-lower number (longer)",
        "final_drive_lower_reason": "on the limiter {pct:.0f}% of the session",
        "final_drive_higher_change": "+higher number (shorter)",
        "final_drive_higher_reason": (
            "engine rarely stretched ({pct:.0f}% at redline, avg {speed:.0f} km/h)"
        ),
        "brake_pressure": "Brake pressure",
        "brake_pressure_change": "-reduce",
        "brake_pressure_reason": "front wheels lock under braking ({pct:.0f}% of samples)",
        "brake_balance": "Brake balance",
        "brake_balance_rearward_change": "-rearward",
        "brake_balance_rearward_reason": "front axle locks first",
        "brake_balance_forward_change": "+forward",
        "brake_balance_forward_reason": "rear wheels lock first ({pct:.0f}% of samples)",
        "diff_accel": "Differential (acceleration)",
        "diff_accel_change": "+stiffen",
        "diff_accel_reason": "driven wheels spin under power {pct:.0f}% of the session",
        "diff_decel": "Differential (deceleration)",
        "diff_decel_change": "soften",
        "diff_decel_reason": "rear slides while off throttle ({pct:.0f}% of samples)",
        "diff_center": "Differential (center)",
        "diff_center_rear_change": "-rearward bias",
        "diff_center_front_change": "+forward bias",
        "diff_center_front_reason": (
            "AWD understeers (front grip loss {front:.0f}% vs {rear:.0f}% rear) — "
            "shift torque rearward"
        ),
        "diff_center_rear_reason": (
            "AWD oversteers (rear grip loss {rear:.0f}% vs {front:.0f}% front) — "
            "shift torque forward"
        ),
        "aero": "Aero ({axle})",
        "aero_change": "+downforce",
        "aero_front_reason": "front loses grip at speed ({front:.0f}% vs {rear:.0f}% rear)",
        "aero_rear_reason": "rear loses grip at speed ({rear:.0f}% vs {front:.0f}% front)",
        "none": "=== Suggested tuning changes ===\nnone — setup looks balanced for this session.",
        "header": "=== Suggested tuning changes (relative to your current setup) ===",
        "reason_line": "    reason: {reason}",
    },
    "fr": {
        "tire_pressure": "Pression des pneus ({axle})",
        "tire_hot_reason": "temp. pneu {axle} moy. {avg:.0f} {tu} au-dessus de {thresh:.0f} {tu}",
        "tire_cold_reason": (
            "temp. pneu {axle} moy. {avg:.0f} {tu} n'atteint jamais {thresh:.0f} {tu}"
        ),
        "arb": "Barre anti-roulis ({axle})",
        "arb_change": "-2",
        "arb_front_reason": (
            "perte d'adhérence avant excessive ({front:.0f}% contre {rear:.0f}% arrière)"
        ),
        "arb_rear_reason": (
            "perte d'adhérence arrière excessive ({rear:.0f}% contre {front:.0f}% avant)"
        ),
        "camber": "Carrossage ({axle})",
        "camber_change": "+0.3 deg",
        "camber_front_reason": "l'essieu avant glisse avant l'arrière",
        "camber_rear_reason": "l'essieu arrière glisse avant l'avant",
        "spring": "Raideur des ressorts ({axle})",
        "spring_stiffen_change": "+rigidifier",
        "spring_bottom_reason": "suspension {axle} talonne (débattement max {peak:.0f}%)",
        "spring_soften_change": "-assouplir",
        "spring_soft_reason": "suspension {axle} à peine sollicitée (débattement max {peak:.0f}%)",
        "damping_bump": "Amortissement, compression ({axle})",
        "damping_bump_change": "+rigidifier",
        "damping_bump_reason": (
            "suspension {axle} talonne (débattement max {peak:.0f}%) — l'amortissement de "
            "compression résiste à la vitesse de compression, les ressorts seuls "
            "peuvent ne pas suffire"
        ),
        "damping_rebound": "Amortissement, détente ({axle})",
        "damping_rebound_change": "-assouplir",
        "damping_rebound_reason": (
            "suspension {axle} à peine sollicitée (débattement max {peak:.0f}%) — une "
            "détente plus souple aide le pneu à rester au sol pendant le même "
            "transfert de charge"
        ),
        "ride_height": "Garde au sol",
        "ride_height_change": "+augmenter",
        "ride_height_reason": (
            "les deux essieux talonnent (avant {front:.0f}%, arrière {rear:.0f}%) — plus "
            "de garde au sol statique peut aider en complément de ressorts plus raides"
        ),
        "final_drive": "Rapport de pont",
        "final_drive_lower_change": "-diminuer (plus long)",
        "final_drive_lower_reason": "sur le limiteur {pct:.0f}% de la session",
        "final_drive_higher_change": "+augmenter (plus court)",
        "final_drive_higher_reason": (
            "moteur peu sollicité ({pct:.0f}% à la limite, moy. {speed:.0f} km/h)"
        ),
        "brake_pressure": "Pression de freinage",
        "brake_pressure_change": "-réduire",
        "brake_pressure_reason": "roues avant bloquent au freinage ({pct:.0f}% des échantillons)",
        "brake_balance": "Répartition de freinage",
        "brake_balance_rearward_change": "-vers l'arrière",
        "brake_balance_rearward_reason": "l'essieu avant bloque en premier",
        "brake_balance_forward_change": "+vers l'avant",
        "brake_balance_forward_reason": (
            "roues arrière bloquent en premier ({pct:.0f}% des échantillons)"
        ),
        "diff_accel": "Différentiel (accélération)",
        "diff_accel_change": "+rigidifier",
        "diff_accel_reason": ("roues motrices patinent à l'accélération {pct:.0f}% de la session"),
        "diff_decel": "Différentiel (décélération)",
        "diff_decel_change": "assouplir",
        "diff_decel_reason": "l'arrière glisse hors accélérateur ({pct:.0f}% des échantillons)",
        "diff_center": "Différentiel central",
        "diff_center_rear_change": "-vers l'arrière",
        "diff_center_front_change": "+vers l'avant",
        "diff_center_front_reason": (
            "AWD sous-vireur (perte d'adhérence avant {front:.0f}% contre {rear:.0f}% "
            "arrière) — envoyer plus de couple vers l'arrière"
        ),
        "diff_center_rear_reason": (
            "AWD survireur (perte d'adhérence arrière {rear:.0f}% contre {front:.0f}% "
            "avant) — envoyer plus de couple vers l'avant"
        ),
        "aero": "Aérodynamique ({axle})",
        "aero_change": "+appui",
        "aero_front_reason": (
            "l'avant perd l'adhérence à vitesse élevée ({front:.0f}% contre {rear:.0f}% arrière)"
        ),
        "aero_rear_reason": (
            "l'arrière perd l'adhérence à vitesse élevée ({rear:.0f}% contre {front:.0f}% avant)"
        ),
        "none": (
            "=== Réglages suggérés ===\naucun — le setup semble équilibré pour cette session."
        ),
        "header": "=== Réglages suggérés (relatifs à votre setup actuel) ===",
        "reason_line": "    raison : {reason}",
    },
}


def _lang(lang: str) -> str:
    return lang if lang in _T else "en"


@dataclass(slots=True)
class Suggestion:
    """One relative change to apply in FH6's tuning menu."""

    parameter: str
    change: str
    reason: str


def suggest(s: SessionSummary, lang: str = "en", units: str = "metric") -> list[Suggestion]:
    lang = _lang(lang)
    t = _T[lang]
    ax = _AXLE[lang]
    pstep = _PRESSURE_STEP.get(units, _PRESSURE_STEP["metric"])
    tu = temp_unit(units)
    out: list[Suggestion] = []

    # --- Tires: pressure steers operating temperature ---
    for axle, avg_c in (
        ("front", s.tire_temp_front_avg_c),
        ("rear", s.tire_temp_rear_avg_c),
    ):
        avg = disp_temp(avg_c, units)
        if avg_c >= _HOT_TIRE_C:
            out.append(
                Suggestion(
                    t["tire_pressure"].format(axle=ax[axle]),
                    pstep["hot"],
                    t["tire_hot_reason"].format(
                        axle=ax[axle], avg=avg, thresh=disp_temp(_HOT_TIRE_C, units), tu=tu
                    ),
                )
            )
        elif 0 < avg_c <= _COLD_TIRE_C:
            out.append(
                Suggestion(
                    t["tire_pressure"].format(axle=ax[axle]),
                    pstep["cold"],
                    t["tire_cold_reason"].format(
                        axle=ax[axle], avg=avg, thresh=disp_temp(_COLD_TIRE_C, units), tu=tu
                    ),
                )
            )

    # --- Alignment & anti-roll bars: fix handling balance ---
    if s.grip_loss_front_pct - s.grip_loss_rear_pct > _BALANCE_TOLERANCE_PTS:
        out.append(
            Suggestion(
                t["arb"].format(axle=ax["front"]),
                t["arb_change"],
                t["arb_front_reason"].format(
                    front=s.grip_loss_front_pct, rear=s.grip_loss_rear_pct
                ),
            )
        )
        out.append(
            Suggestion(
                t["camber"].format(axle=ax["front"]),
                t["camber_change"],
                t["camber_front_reason"],
            )
        )
    elif s.grip_loss_rear_pct - s.grip_loss_front_pct > _BALANCE_TOLERANCE_PTS:
        out.append(
            Suggestion(
                t["arb"].format(axle=ax["rear"]),
                t["arb_change"],
                t["arb_rear_reason"].format(front=s.grip_loss_front_pct, rear=s.grip_loss_rear_pct),
            )
        )
        out.append(
            Suggestion(
                t["camber"].format(axle=ax["rear"]),
                t["camber_change"],
                t["camber_rear_reason"],
            )
        )

    # --- Suspension: spring stiffness / damping from observed travel usage ---
    bottomed = {"front": False, "rear": False}
    for axle, peak in (
        ("front", s.susp_travel_front_max_norm),
        ("rear", s.susp_travel_rear_max_norm),
    ):
        if peak >= _BOTTOM_OUT_NORM:
            bottomed[axle] = True
            out.append(
                Suggestion(
                    t["spring"].format(axle=ax[axle]),
                    t["spring_stiffen_change"],
                    t["spring_bottom_reason"].format(axle=ax[axle], peak=peak * 100),
                )
            )
            out.append(
                Suggestion(
                    t["damping_bump"].format(axle=ax[axle]),
                    t["damping_bump_change"],
                    t["damping_bump_reason"].format(axle=ax[axle], peak=peak * 100),
                )
            )
        elif 0 < peak <= _SOFT_SUSPENSION_NORM and s.avg_speed_kmh >= _MIN_SPEED_FOR_SUSP_RULE_KMH:
            out.append(
                Suggestion(
                    t["spring"].format(axle=ax[axle]),
                    t["spring_soften_change"],
                    t["spring_soft_reason"].format(axle=ax[axle], peak=peak * 100),
                )
            )
            out.append(
                Suggestion(
                    t["damping_rebound"].format(axle=ax[axle]),
                    t["damping_rebound_change"],
                    t["damping_rebound_reason"].format(axle=ax[axle], peak=peak * 100),
                )
            )

    # --- Ride height: both axles bottoming out is a static-clearance problem too ---
    if bottomed["front"] and bottomed["rear"]:
        out.append(
            Suggestion(
                t["ride_height"],
                t["ride_height_change"],
                t["ride_height_reason"].format(
                    front=s.susp_travel_front_max_norm * 100,
                    rear=s.susp_travel_rear_max_norm * 100,
                ),
            )
        )

    # --- Gearing: final drive vs time spent on the limiter ---
    if s.redline_pct >= _REDLINE_HIGH_PCT:
        out.append(
            Suggestion(
                t["final_drive"],
                t["final_drive_lower_change"],
                t["final_drive_lower_reason"].format(pct=s.redline_pct),
            )
        )
    elif s.redline_pct <= _REDLINE_LOW_PCT and s.avg_speed_kmh >= 50:
        out.append(
            Suggestion(
                t["final_drive"],
                t["final_drive_higher_change"],
                t["final_drive_higher_reason"].format(pct=s.redline_pct, speed=s.avg_speed_kmh),
            )
        )

    # --- Brakes: bias/pressure from wheel lockup ---
    if s.lockup_front_pct >= _LOCKUP_HIGH_PCT and s.lockup_front_pct > s.lockup_rear_pct:
        out.append(
            Suggestion(
                t["brake_pressure"],
                t["brake_pressure_change"],
                t["brake_pressure_reason"].format(pct=s.lockup_front_pct),
            )
        )
        out.append(
            Suggestion(
                t["brake_balance"],
                t["brake_balance_rearward_change"],
                t["brake_balance_rearward_reason"],
            )
        )
    elif s.lockup_rear_pct >= _LOCKUP_HIGH_PCT and s.lockup_rear_pct > s.lockup_front_pct:
        out.append(
            Suggestion(
                t["brake_balance"],
                t["brake_balance_forward_change"],
                t["brake_balance_forward_reason"].format(pct=s.lockup_rear_pct),
            )
        )

    # --- Differential: acceleration locking from driven-wheel spin ---
    if s.wheelspin_pct >= _SPIN_HIGH_PCT:
        out.append(
            Suggestion(
                t["diff_accel"],
                t["diff_accel_change"],
                t["diff_accel_reason"].format(pct=s.wheelspin_pct),
            )
        )

    # --- Differential: too much decel locking makes the rear step out on lift ---
    if s.coast_oversteer_pct >= _COAST_OVERSTEER_PCT:
        out.append(
            Suggestion(
                t["diff_decel"],
                t["diff_decel_change"],
                t["diff_decel_reason"].format(pct=s.coast_oversteer_pct),
            )
        )

    # --- Differential (center, AWD only): front/rear torque split from balance ---
    if s.drivetrain_type == _DT_AWD:
        if s.grip_loss_front_pct - s.grip_loss_rear_pct > _BALANCE_TOLERANCE_PTS:
            out.append(
                Suggestion(
                    t["diff_center"],
                    t["diff_center_rear_change"],
                    t["diff_center_front_reason"].format(
                        front=s.grip_loss_front_pct, rear=s.grip_loss_rear_pct
                    ),
                )
            )
        elif s.grip_loss_rear_pct - s.grip_loss_front_pct > _BALANCE_TOLERANCE_PTS:
            out.append(
                Suggestion(
                    t["diff_center"],
                    t["diff_center_front_change"],
                    t["diff_center_rear_reason"].format(
                        front=s.grip_loss_front_pct, rear=s.grip_loss_rear_pct
                    ),
                )
            )

    # --- Aero: downforce where the car runs out of grip at high speed ---
    if s.max_speed_kmh >= _AERO_MIN_SPEED_KMH:
        if s.hs_grip_loss_front_pct - s.hs_grip_loss_rear_pct >= _HS_LOSS_DIFF_PTS:
            out.append(
                Suggestion(
                    t["aero"].format(axle=ax["front"]),
                    t["aero_change"],
                    t["aero_front_reason"].format(
                        front=s.hs_grip_loss_front_pct, rear=s.hs_grip_loss_rear_pct
                    ),
                )
            )
        elif s.hs_grip_loss_rear_pct - s.hs_grip_loss_front_pct >= _HS_LOSS_DIFF_PTS:
            out.append(
                Suggestion(
                    t["aero"].format(axle=ax["rear"]),
                    t["aero_change"],
                    t["aero_rear_reason"].format(
                        front=s.hs_grip_loss_front_pct, rear=s.hs_grip_loss_rear_pct
                    ),
                )
            )

    return out


def format_suggestions(items: list[Suggestion], lang: str = "en") -> str:
    t = _T[_lang(lang)]
    if not items:
        return t["none"]
    lines = [t["header"]]
    lines += [
        f"* {it.parameter}: {it.change}\n{t['reason_line'].format(reason=it.reason)}"
        for it in items
    ]
    return "\n".join(lines)
