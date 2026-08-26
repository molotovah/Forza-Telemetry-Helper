import socket
import threading
import time
from dataclasses import fields
from struct import calcsize

import pytest

from fth.fixtures import make_packet
from fth.ingest import (
    _FORMAT,
    _NAMES,
    PACKET_SIZE,
    TelemetryPacket,
    listen,
)


def test_layout_matches_documented_size():
    assert calcsize(_FORMAT) == PACKET_SIZE == 324


def test_dataclass_fields_match_wire_order():
    assert tuple(f.name for f in fields(TelemetryPacket)) == _NAMES


def test_roundtrip():
    raw = make_packet(speed=42.5, gear=3, tire_temp_front_left=88.0)
    pkt = TelemetryPacket.from_bytes(raw)
    assert pkt.speed == pytest.approx(42.5)
    assert pkt.gear == 3
    assert pkt.tire_temp_front_left == pytest.approx(88.0)
    assert pkt.is_race_on == 1
    assert pkt.car_performance_index == 800


def test_wrong_size_raises():
    with pytest.raises(ValueError):
        TelemetryPacket.from_bytes(b"\x00" * 100)


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_listen_receives_decoded_packets():
    port = _free_udp_port()
    packets: list[TelemetryPacket] = []

    def run():
        for pkt in listen("127.0.0.1", port):
            packets.append(pkt)
            return  # stop after the first valid packet

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    deadline = time.time() + 2
    while not packets and time.time() < deadline:
        sender.sendto(make_packet(), ("127.0.0.1", port))
        sender.sendto(b"garbage", ("127.0.0.1", port))  # must be skipped silently
        threading.Event().wait(0.05)
    thread.join(timeout=2)

    assert len(packets) == 1
    assert packets[0].speed == pytest.approx(_DEFAULT_SPEED := 55.5)
