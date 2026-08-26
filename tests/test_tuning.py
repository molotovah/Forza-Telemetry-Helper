from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket
from fth.session import summarize
from fth.tuning import Suggestion, format_suggestions, suggest


def _summary(**overrides) -> object:
    """One-packet session; every metric overridable via packet fields."""
    defaults = {
        "speed": 60.0,
        "tire_temp_front_left": 85.0,
        "tire_temp_front_right": 85.0,
        "tire_temp_rear_left": 85.0,
        "tire_temp_rear_right": 85.0,
        "normalized_suspension_travel_front_left": 0.7,
        "normalized_suspension_travel_rear_left": 0.7,
        "engine_max_rpm": 8000.0,
        "current_engine_rpm": 5000.0,
        "current_race_time": 5.0,
    }
    return summarize([TelemetryPacket.from_bytes(make_packet(**{**defaults, **overrides}))])


def _parameters(items: list[Suggestion]) -> dict[str, str]:
    return {it.parameter: it.change for it in items}


def test_hot_tires_drop_pressure():
    s = _summary(tire_temp_rear_left=110.0, tire_temp_rear_right=105.0)
    changes = _parameters(suggest(s))
    assert "Tire pressure (rear)" in changes
    assert changes["Tire pressure (rear)"] == "-0.1 bar"  # units="metric" default
    assert "Tire pressure (front)" not in changes


def test_cold_tires_raise_pressure():
    s = _summary(tire_temp_front_left=40.0, tire_temp_front_right=45.0)
    assert _parameters(suggest(s))["Tire pressure (front)"] == "+0.1 bar"


def test_pressure_step_follows_units_not_lang():
    # units is independent of lang: English text + metric bar is a valid combo.
    s = _summary(tire_temp_rear_left=110.0, tire_temp_rear_right=105.0)
    changes = _parameters(suggest(s, lang="en", units="imperial"))
    assert changes["Tire pressure (rear)"] == "-2 psi"
    changes = _parameters(suggest(s, lang="fr", units="imperial"))
    assert changes["Pression des pneus (arrière)"] == "-2 psi"


def test_understeer_softens_front_bar():
    s = _summary(tire_combined_slip_front_left=1.6, tire_combined_slip_rear_left=0.2)
    changes = _parameters(suggest(s))
    assert changes["Anti-roll bar (front)"] == "-2"
    assert changes["Camber (front)"] == "+0.3 deg"
    assert not any("rear" in p for p in changes)


def test_oversteer_softens_rear_bar():
    s = _summary(tire_combined_slip_front_left=0.2, tire_combined_slip_rear_left=1.6)
    changes = _parameters(suggest(s))
    assert changes["Anti-roll bar (rear)"] == "-2"
    assert "Anti-roll bar (front)" not in changes


def test_bottoming_out_stiffens_springs():
    s = _summary(normalized_suspension_travel_rear_left=1.0)
    assert _parameters(suggest(s))["Spring stiffness (rear)"] == "+stiffen"


def test_unused_suspension_softens_springs_only_at_speed():
    slow = suggest(_summary(speed=5.0, normalized_suspension_travel_front_left=0.1))
    fast = suggest(_summary(speed=50.0, normalized_suspension_travel_front_left=0.1))
    assert not any("Spring" in it.parameter for it in slow)
    assert _parameters(fast)["Spring stiffness (front)"] == "-soften"


def test_zero_travel_is_airborne_not_soft():
    s = suggest(_summary(speed=50.0))  # default travel is 0 -> wheels off the ground
    assert not any("Spring" in it.parameter for it in s)


def test_limiter_time_shortens_gearing():
    s = _summary(current_engine_rpm=7900.0)
    changes = _parameters(suggest(s))
    assert "Final drive" in changes
    assert "longer" in changes["Final drive"]


def test_balanced_session_suggests_nothing():
    s = _summary(speed=12.0)  # below the 50 km/h gearing-rule floor
    items = suggest(s)
    assert items == []
    assert "none" in format_suggestions(items)


def test_format_lists_reasons():
    text = format_suggestions([Suggestion("X", "+1", "because test")])
    assert "* X: +1" in text
    assert "because test" in text


def _multi_session(packet_overrides: list[dict]) -> object:
    base = {"speed": 45.0, "current_race_time": 5.0}
    return summarize(
        [TelemetryPacket.from_bytes(make_packet(**{**base, **o})) for o in packet_overrides]
    )


def test_front_lockup_reduces_pressure_and_moves_bias():
    s = _multi_session(
        [
            {
                "brake": 255,
                "accel": 0,
                "wheel_rotation_speed_front_left": 0.5,
                "wheel_rotation_speed_front_right": 150.0,
                "wheel_rotation_speed_rear_left": 200.0,
                "wheel_rotation_speed_rear_right": 200.0,
            },
            {
                "brake": 255,
                "accel": 0,
                "wheel_rotation_speed_front_left": 0.5,
                "wheel_rotation_speed_front_right": 150.0,
                "wheel_rotation_speed_rear_left": 200.0,
                "wheel_rotation_speed_rear_right": 200.0,
            },
            {"brake": 0, "accel": 0},
        ]
    )
    changes = _parameters(suggest(s))
    assert changes["Brake pressure"] == "-reduce"
    assert changes["Brake balance"] == "-rearward"


def test_rear_lockup_moves_balance_forward():
    s = _multi_session(
        [
            {
                "brake": 255,
                "accel": 0,
                "wheel_rotation_speed_front_left": 150.0,
                "wheel_rotation_speed_front_right": 150.0,
                "wheel_rotation_speed_rear_left": 0.5,
                "wheel_rotation_speed_rear_right": 200.0,
            },
            {"brake": 0, "accel": 0},
        ]
    )
    changes = _parameters(suggest(s))
    assert changes["Brake balance"] == "+forward"
    assert "Brake pressure" not in changes


def test_wheelspin_stiffens_diff_accel():
    s = _multi_session(
        [
            {
                "accel": 255,
                "tire_slip_ratio_rear_left": 0.9,
                "acceleration_z": 3.0,
                "drivetrain_type": 1,
            },
            {
                "accel": 255,
                "tire_slip_ratio_rear_left": 0.9,
                "acceleration_z": 3.0,
                "drivetrain_type": 1,
            },
            {"accel": 0, "drivetrain_type": 1},
        ]
    )
    changes = _parameters(suggest(s))
    assert changes["Differential (acceleration)"] == "+stiffen"


def test_no_wheelspin_on_coasting_axle():
    # spin on the NON-driven axle (FWD car) must not trigger the diff rule
    s = _multi_session(
        [
            {
                "accel": 255,
                "tire_slip_ratio_rear_left": 0.9,
                "acceleration_z": 3.0,
                "drivetrain_type": 0,
            },
            {
                "accel": 255,
                "tire_slip_ratio_rear_left": 0.9,
                "acceleration_z": 3.0,
                "drivetrain_type": 0,
            },
            {"accel": 0, "drivetrain_type": 0},
        ]
    )
    assert "Differential (acceleration)" not in _parameters(suggest(s))


def test_coast_oversteer_softens_diff_decel():
    s = _multi_session(
        [
            {"accel": 0, "tire_combined_slip_rear_left": 1.5},
            {"accel": 0, "tire_combined_slip_rear_left": 1.5},
            {"accel": 0},
        ]
    )
    changes = _parameters(suggest(s))
    assert changes["Differential (deceleration)"] == "soften"


def test_high_speed_imbalance_adds_aero():
    overrides = [{"tire_combined_slip_front_left": 1.5}] * 3 + [{}] * 3
    s = _multi_session(overrides)  # all at 162 km/h -> aero band
    changes = _parameters(suggest(s))
    assert changes["Aero (front)"] == "+downforce"


def test_no_aero_advice_below_band():
    slow = [{"speed": 20.0, "tire_combined_slip_front_left": 1.5}] * 6
    assert "Aero (front)" not in _parameters(suggest(_multi_session(slow)))


def test_bottoming_out_also_suggests_bump_damping():
    s = _summary(normalized_suspension_travel_rear_left=1.0)
    changes = _parameters(suggest(s))
    assert changes["Damping, bump (rear)"] == "+stiffen"


def test_unused_suspension_also_suggests_rebound_damping():
    s = _summary(speed=50.0, normalized_suspension_travel_front_left=0.1)
    changes = _parameters(suggest(s))
    assert changes["Damping, rebound (front)"] == "-soften"


def test_both_axles_bottoming_out_suggests_ride_height():
    s = _summary(
        normalized_suspension_travel_front_left=1.0, normalized_suspension_travel_rear_left=1.0
    )
    changes = _parameters(suggest(s))
    assert changes["Ride height"] == "+raise"


def test_one_axle_bottoming_out_does_not_suggest_ride_height():
    s = _summary(normalized_suspension_travel_rear_left=1.0)  # front left at default 0.7
    assert "Ride height" not in _parameters(suggest(s))


def test_awd_understeer_shifts_center_diff_rearward():
    s = _multi_session(
        [{"drivetrain_type": 2, "tire_combined_slip_front_left": 1.6}] * 3
        + [{"drivetrain_type": 2}] * 3
    )
    changes = _parameters(suggest(s))
    assert changes["Differential (center)"] == "-rearward bias"


def test_awd_oversteer_shifts_center_diff_forward():
    s = _multi_session(
        [{"drivetrain_type": 2, "tire_combined_slip_rear_left": 1.6}] * 3
        + [{"drivetrain_type": 2}] * 3
    )
    changes = _parameters(suggest(s))
    assert changes["Differential (center)"] == "+forward bias"


def test_non_awd_never_gets_center_diff_advice():
    s = _multi_session(
        [{"drivetrain_type": 1, "tire_combined_slip_front_left": 1.6}] * 3
        + [{"drivetrain_type": 1}] * 3
    )
    assert "Differential (center)" not in _parameters(suggest(s))


def test_french_translations():
    s = _summary(tire_temp_rear_left=110.0, tire_temp_rear_right=105.0)
    changes = _parameters(suggest(s, lang="fr"))
    assert changes["Pression des pneus (arrière)"] == "-0.1 bar"
    assert "Tire pressure" not in " ".join(changes)


def test_french_tire_pressure_uses_bar_not_psi():
    # France/metric convention: tire pressure is read in bar, never psi.
    s = _summary(tire_temp_front_left=40.0, tire_temp_front_right=45.0)
    changes = _parameters(suggest(s, lang="fr"))
    assert "bar" in changes["Pression des pneus (avant)"]
    assert "psi" not in changes["Pression des pneus (avant)"]


def test_french_reasons_and_header():
    s = _summary(tire_temp_rear_left=110.0, tire_temp_rear_right=105.0)
    items = suggest(s, lang="fr")
    text = format_suggestions(items, lang="fr")
    assert "Réglages suggérés" in text
    assert "raison :" in text
    assert "reason:" not in text


def test_french_empty_session_message():
    text = format_suggestions([], lang="fr")
    assert "aucun" in text


def test_unknown_lang_falls_back_to_english():
    s = _summary(tire_temp_rear_left=110.0, tire_temp_rear_right=105.0)
    changes = _parameters(suggest(s, lang="de"))
    assert "Tire pressure (rear)" in changes
