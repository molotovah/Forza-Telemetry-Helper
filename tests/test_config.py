"""Tests for the persistent settings store."""

import json

from fth import config


def test_save_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "config.json"))
    config.save(key="sk-or", model="stealth/ox-alpha")
    assert config.load() == {"key": "sk-or", "model": "stealth/ox-alpha"}


def test_empty_value_deletes_field(monkeypatch, tmp_path):
    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "config.json"))
    config.save(key="a", model="m")
    config.save(key="")
    assert config.load() == {"model": "m"}


def test_missing_or_corrupt_file_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "absent.json"))
    assert config.load() == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setenv("FTH_CONFIG", str(bad))
    assert config.load() == {}


def test_unknown_fields_ignored(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"key": "k", "evil": "x"}))
    monkeypatch.setenv("FTH_CONFIG", str(path))
    assert config.load() == {"key": "k"}
