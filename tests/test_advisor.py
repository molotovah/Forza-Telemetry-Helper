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
    for name in ("FTH_AI_URL", "FTH_AI_KEY", "FTH_AI_MODEL"):
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

    monkeypatch.setenv("FTH_AI_URL", "https://ai.example/v1/chat/completions")
    monkeypatch.setenv("FTH_AI_KEY", "secret")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    out = advise(summarize(_packets()))
    assert out == "1. Soften front ARB"
    assert captured["url"] == "https://ai.example/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    assert captured["payload"]["model"] == "ox-alpha"
    assert any(m["role"] == "system" for m in captured["payload"]["messages"])
    assert "Session telemetry summary" in captured["payload"]["messages"][1]["content"]


def test_http_error_falls_back_to_rules(monkeypatch, capsys):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setenv("FTH_AI_URL", "https://ai.example/v1/chat/completions")
    monkeypatch.setenv("FTH_AI_KEY", "secret")
    monkeypatch.setattr("fth.advisor.urllib.request.urlopen", fake_urlopen)

    out = advise(summarize(_packets()))
    assert "Suggested tuning changes" in out
    assert "AI advisor unavailable" in capsys.readouterr().err
