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
    return summarize(
        [TelemetryPacket.from_bytes(make_packet(**{**defaults, **overrides}))]
    )


def _parameters(items: list[Suggestion]) -> dict[str, str]:
    return {it.parameter: it.change for it in items}


def test_hot_tires_drop_pressure():
    s = _summary(tire_temp_rear_left=110.0, tire_temp_rear_right=105.0)
    changes = _parameters(suggest(s))
    assert "Tire pressure (rear)" in changes
    assert changes["Tire pressure (rear)"] == "-2 psi"
    assert "Tire pressure (front)" not in changes


def test_cold_tires_raise_pressure():
    s = _summary(tire_temp_front_left=40.0, tire_temp_front_right=45.0)
    assert _parameters(suggest(s))["Tire pressure (front)"] == "+2 psi"


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
