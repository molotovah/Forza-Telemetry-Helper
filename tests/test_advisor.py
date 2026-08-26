"""Tests for the AI advisor layer (env gating, HTTP call, fallback)."""

import io
import json
import urllib.error

import pytest

from fth.advisor import advise
from fth.fixtures import make_packet
from fth.ingest import TelemetryPacket
from fth.session import summarize


@pytest.fixture(autouse=True)
def _no_ai_env(monkeypatch):
    for name in (
        "FTH_AI_URL",
        "FTH_AI_KEY",
        "FTH_AI_MODEL",
        "FTH_AI_TIMEOUT",
        "FTH_AI_REASONING",
    ):
        monkeypatch.delenv(name, raising=False)


def _packets() -> list[TelemetryPacket]:
    return [
        TelemetryPacket.from_bytes(
            make_packet(
                speed=50.0,
                current_race_time=float(i),
                tire_combined_slip_front_left=1.5,
                tire_combined_slip_rear_left=0.2,
                engine_max_rpm=8000.0,
                current_engine_rpm=5000.0,
            )
        )
        for i in range(4)
    ]


class _FakeResponse(io.BytesIO):
    pass


def test_no_env_falls_back_to_rules():
    out = advise(summarize(_packets()))
    assert "Suggested tuning changes" in out


def test_ai_call_and_response(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["payload"] = json.loads(req.data)
        return _FakeResponse(
            json.dumps({"choices": [{"message": {"content": "1. Soften front ARB"}}]}).encode()
        )

    monkeypatch.setenv("FTH_AI_KEY", "secret")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    out = advise(summarize(_packets()))
    assert out == "1. Soften front ARB"
    # OpenRouter defaults with only a key set
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    assert captured["payload"]["model"] == "stealth/ox-alpha"
    system = next(m for m in captured["payload"]["messages"] if m["role"] == "system")
    assert "race engineer" in system["content"]
    assert "tuning menu" in system["content"]
    user = next(m for m in captured["payload"]["messages"] if m["role"] == "user")
    assert "Session telemetry summary" in user["content"]
    assert "reasoning_effort" not in captured["payload"]  # opt-in only


def test_reasoning_effort_opt_in(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["payload"] = json.loads(req.data)
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setenv("FTH_AI_KEY", "secret")
    monkeypatch.setenv("FTH_AI_REASONING", "low")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    advise(summarize(_packets()))
    assert captured["payload"]["reasoning_effort"] == "low"


def test_config_file_provides_credentials(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["auth"] = req.get_header("Authorization")
        captured["payload"] = json.loads(req.data)
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    (tmp_path / "config.json").write_text(json.dumps({"key": "file-key", "model": "vendor/other"}))
    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    out = advise(summarize(_packets()))
    assert out == "ok"
    assert captured["auth"] == "Bearer file-key"
    assert captured["payload"]["model"] == "vendor/other"


def test_env_overrides_config_file(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    (tmp_path / "config.json").write_text(json.dumps({"key": "file-key"}))
    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("FTH_AI_KEY", "env-key")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    advise(summarize(_packets()))
    assert captured["auth"] == "Bearer env-key"


def test_http_error_falls_back_to_rules(monkeypatch, capsys):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setenv("FTH_AI_KEY", "secret")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    out = advise(summarize(_packets()))
    assert "Suggested tuning changes" in out
    assert "AI advisor unavailable" in capsys.readouterr().err


def test_timeout_env_var(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["timeout"] = timeout
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setenv("FTH_AI_URL", "https://ai.example/v1/chat/completions")
    monkeypatch.setenv("FTH_AI_KEY", "secret")
    monkeypatch.setenv("FTH_AI_TIMEOUT", "7")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    advise(summarize(_packets()))
    assert seen["timeout"] == 7


def test_prompt_includes_per_lap_breakdown(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["prompt"] = json.loads(req.data)["messages"][1]["content"]
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    monkeypatch.setenv("FTH_AI_URL", "https://ai.example/v1/chat/completions")
    monkeypatch.setenv("FTH_AI_KEY", "secret")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    ps = [
        TelemetryPacket.from_bytes(make_packet(current_race_time=float(i), lap_number=i // 2))
        for i in range(4)
    ]
    advise(summarize(ps), packets=ps)
    assert "Per-lap breakdown" in captured["prompt"]

    # aggregates only when no packets are passed
    advise(summarize(_packets()))
    assert "Per-lap breakdown" not in captured["prompt"]


def test_lang_fr_directs_model(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["payload"] = json.loads(req.data)
        return _FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

    (tmp_path / "config.json").write_text(json.dumps({"key": "file-key", "lang": "fr"}))
    monkeypatch.setenv("FTH_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    advise(summarize(_packets()))
    system = next(m for m in captured["payload"]["messages"] if m["role"] == "system")
    assert "Reply in French" in system["content"]
