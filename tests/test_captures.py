"""Tests for named capture storage (save/load/import/list)."""

import pytest

from fth import captures
from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket
from fth.session import CsvRecorder


@pytest.fixture(autouse=True)
def _captures_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("FTH_CAPTURES_DIR", str(tmp_path / "captures"))


def _packets(n: int) -> list[TelemetryPacket]:
    return [
        TelemetryPacket.from_bytes(make_packet(speed=40.0 + i, current_race_time=float(i)))
        for i in range(n)
    ]


def test_save_load_roundtrip():
    captures.save("lap1", _packets(3))
    loaded = captures.load("lap1")
    assert len(loaded) == 3
    assert loaded[0].speed == 40.0


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "", "x" * 81])
def test_invalid_names_rejected(name):
    with pytest.raises(captures.InvalidName):
        captures.save(name, _packets(1))


def test_list_captures_reflects_saved_files():
    captures.save("lap1", _packets(3))
    captures.save("lap2", _packets(5))
    listed = {c["name"]: c for c in captures.list_captures()}
    assert listed["lap1"]["samples"] == 3
    assert listed["lap2"]["samples"] == 5
    assert listed["lap1"]["size_bytes"] > 0
    assert listed["lap1"]["saved_at"] > 0


def test_import_csv_rejects_bad_header():
    with pytest.raises(captures.InvalidName):
        captures.import_csv("bad", "not,a,valid,header\n1,2,3,4\n")


def test_import_csv_roundtrips_valid_content(tmp_path):
    path = tmp_path / "src.csv"
    with open(path, "w", newline="") as stream:
        recorder = CsvRecorder(stream)
        for pkt in _packets(4):
            recorder.write(pkt)
        recorder.flush()

    captures.import_csv("imported", path.read_text())
    loaded = captures.load("imported")
    assert len(loaded) == 4
    assert loaded[0].speed == 40.0
