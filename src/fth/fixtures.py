"""Synthetic Data Out packets for tests and offline demos."""

from __future__ import annotations

import struct

from fth.ingest import _FORMAT, _NAMES, PACKET_SIZE

# Plausible mid-corner values for a quick sanity demo.
_DEFAULTS: dict[str, float | int] = {
    "is_race_on": 1,
    "timestamp_ms": 123456,
    "engine_max_rpm": 7500.0,
    "engine_idle_rpm": 900.0,
    "current_engine_rpm": 5200.0,
    "car_ordinal": 2027,
    "car_class": 5,
    "car_performance_index": 800,
    "drivetrain_type": 1,  # RWD
    "num_cylinders": 8,
    "speed": 55.5,
    "power": 300000.0,
    "torque": 450.0,
    "gear": 4,
    "accel": 200,
    "brake": 0,
    "steer": -30,
}


def make_packet(**overrides: float | int) -> bytes:
    """Build a synthetic 324-byte packet; any documented field can be overridden."""
    values = {name: _DEFAULTS.get(name, 0) for name in _NAMES}
    unknown = set(overrides) - set(_NAMES)
    if unknown:
        raise KeyError(f"unknown fields: {sorted(unknown)}")
    values.update(overrides)
    data = struct.pack(_FORMAT, *(values[name] for name in _NAMES))
    assert len(data) == PACKET_SIZE
    return data
