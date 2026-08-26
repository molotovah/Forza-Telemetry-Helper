"""Parser and UDP listener for the Forza Horizon 6 "Data Out" telemetry stream.

Protocol reference (official):
https://support.forza.net/hc/en-us/articles/51744149102611-Forza-Horizon-6-Data-Out-Documentation

One-way UDP traffic: a fixed 324-byte packet is sent to the configured
IP/port at the game's frame rate while the player is driving.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Iterator

PACKET_SIZE = 324

# Little-endian; the trailing "x" is one reserved padding byte documented only
# by the total packet size of 324 bytes (fields above sum to 323).
_CORNER = ("front_left", "front_right", "rear_left", "rear_right")
_SPEC = [
    ("is_race_on", "i"),
    ("timestamp_ms", "I"),
    ("engine_max_rpm", "f"),
    ("engine_idle_rpm", "f"),
    ("current_engine_rpm", "f"),
    *[("acceleration_" + a, "f") for a in ("x", "y", "z")],
    *[("velocity_" + a, "f") for a in ("x", "y", "z")],
    *[("angular_velocity_" + a, "f") for a in ("x", "y", "z")],
    *[(n, "f") for n in ("yaw", "pitch", "roll")],
    *[("normalized_suspension_travel_" + c, "f") for c in _CORNER],
    *[("tire_slip_ratio_" + c, "f") for c in _CORNER],
    *[("wheel_rotation_speed_" + c, "f") for c in _CORNER],
    *[("wheel_on_rumble_strip_" + c, "i") for c in _CORNER],
    *[("wheel_in_puddle_" + c, "i") for c in _CORNER],
    *[("surface_rumble_" + c, "f") for c in _CORNER],
    *[("tire_slip_angle_" + c, "f") for c in _CORNER],
    *[("tire_combined_slip_" + c, "f") for c in _CORNER],
    *[("suspension_travel_meters_" + c, "f") for c in _CORNER],
    ("car_ordinal", "i"),
    ("car_class", "i"),
    ("car_performance_index", "i"),
    ("drivetrain_type", "i"),
    ("num_cylinders", "i"),
    ("car_group", "I"),  # FH6-specific
    ("smashable_vel_diff", "f"),  # FH6-specific
    ("smashable_mass", "f"),  # FH6-specific
    *[("position_" + a, "f") for a in ("x", "y", "z")],
    ("speed", "f"),
    ("power", "f"),
    ("torque", "f"),
    *[("tire_temp_" + c, "f") for c in _CORNER],
    ("boost", "f"),
    ("fuel", "f"),
    ("distance_traveled", "f"),
    ("best_lap", "f"),
    ("last_lap", "f"),
    ("current_lap", "f"),
    ("current_race_time", "f"),
    ("lap_number", "H"),
    ("race_position", "B"),
    ("accel", "B"),
    ("brake", "B"),
    ("clutch", "B"),
    ("hand_brake", "B"),
    ("gear", "B"),
    ("steer", "b"),
    ("normalized_driving_line", "b"),
    ("normalized_ai_brake_difference", "b"),
]
_FORMAT = "<" + "".join(code for _, code in _SPEC) + "x"
_NAMES = tuple(name for name, _ in _SPEC)
_INT_NAMES = frozenset(name for name, code in _SPEC if code in "iIHbB")

assert struct.calcsize(_FORMAT) == PACKET_SIZE, "packet layout drift"


@dataclass(slots=True)
class TelemetryPacket:
    """One decoded Data Out packet, raw off the wire (not unit-normalized).

    Units follow the official documentation where it specifies them: speeds
    in m/s, power in W, torque in Nm, angles in radians — always, regardless
    of any in-game display/region/language setting. TireTemp* is undocumented
    there but is always Fahrenheit on the wire (confirmed by independent FH
    telemetry projects); see fth.session.normalize_units to convert it.
    """

    is_race_on: int
    timestamp_ms: int
    engine_max_rpm: float
    engine_idle_rpm: float
    current_engine_rpm: float
    acceleration_x: float
    acceleration_y: float
    acceleration_z: float
    velocity_x: float
    velocity_y: float
    velocity_z: float
    angular_velocity_x: float
    angular_velocity_y: float
    angular_velocity_z: float
    yaw: float
    pitch: float
    roll: float
    normalized_suspension_travel_front_left: float
    normalized_suspension_travel_front_right: float
    normalized_suspension_travel_rear_left: float
    normalized_suspension_travel_rear_right: float
    tire_slip_ratio_front_left: float
    tire_slip_ratio_front_right: float
    tire_slip_ratio_rear_left: float
    tire_slip_ratio_rear_right: float
    wheel_rotation_speed_front_left: float
    wheel_rotation_speed_front_right: float
    wheel_rotation_speed_rear_left: float
    wheel_rotation_speed_rear_right: float
    wheel_on_rumble_strip_front_left: int
    wheel_on_rumble_strip_front_right: int
    wheel_on_rumble_strip_rear_left: int
    wheel_on_rumble_strip_rear_right: int
    wheel_in_puddle_front_left: int
    wheel_in_puddle_front_right: int
    wheel_in_puddle_rear_left: int
    wheel_in_puddle_rear_right: int
    surface_rumble_front_left: float
    surface_rumble_front_right: float
    surface_rumble_rear_left: float
    surface_rumble_rear_right: float
    tire_slip_angle_front_left: float
    tire_slip_angle_front_right: float
    tire_slip_angle_rear_left: float
    tire_slip_angle_rear_right: float
    tire_combined_slip_front_left: float
    tire_combined_slip_front_right: float
    tire_combined_slip_rear_left: float
    tire_combined_slip_rear_right: float
    suspension_travel_meters_front_left: float
    suspension_travel_meters_front_right: float
    suspension_travel_meters_rear_left: float
    suspension_travel_meters_rear_right: float
    car_ordinal: int
    car_class: int
    car_performance_index: int
    drivetrain_type: int
    num_cylinders: int
    car_group: int
    smashable_vel_diff: float
    smashable_mass: float
    position_x: float
    position_y: float
    position_z: float
    speed: float
    power: float
    torque: float
    tire_temp_front_left: float
    tire_temp_front_right: float
    tire_temp_rear_left: float
    tire_temp_rear_right: float
    boost: float
    fuel: float
    distance_traveled: float
    best_lap: float
    last_lap: float
    current_lap: float
    current_race_time: float
    lap_number: int
    race_position: int
    accel: int
    brake: int
    clutch: int
    hand_brake: int
    gear: int
    steer: int
    normalized_driving_line: int
    normalized_ai_brake_difference: int

    @classmethod
    def from_bytes(cls, data: bytes) -> TelemetryPacket:
        if len(data) != PACKET_SIZE:
            raise ValueError(f"expected {PACKET_SIZE} bytes, got {len(data)}")
        return cls(*struct.unpack(_FORMAT, data))


def listen(host: str = "127.0.0.1", port: int = 20777) -> Iterator[TelemetryPacket]:
    """Yield decoded packets received on udp://host:port forever.

    Malformed datagrams (wrong size) are skipped so a stray packet never
    kills a live session. Avoid ports 5200-5300: the game binds its own
    outgoing socket there.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    try:
        while True:
            data, _ = sock.recvfrom(4096)
            if len(data) == PACKET_SIZE:
                yield TelemetryPacket.from_bytes(data)
    finally:
        sock.close()
