"""Named capture storage: save/list/load/import recorded sessions as CSV.

Each capture is one CSV file at ~/.fth/captures/<name>.csv, using the same
format CsvRecorder/load_csv already produce/consume — a saved capture is
directly openable via `fth dashboard <path>`. Override the directory with
FTH_CAPTURES_DIR (used by tests).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from fth.ingest import _NAMES, TelemetryPacket
from fth.session import CsvRecorder, load_csv

_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,80}$")


class InvalidName(ValueError):
    pass


def _dir() -> Path:
    d = Path(os.environ.get("FTH_CAPTURES_DIR", Path.home() / ".fth" / "captures"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(name: str) -> Path:
    if not _NAME_RE.match(name):
        raise InvalidName(f"invalid capture name: {name!r}")
    return _dir() / f"{name}.csv"


def save(name: str, packets: Iterable[TelemetryPacket]) -> Path:
    path = _path(name)
    with open(path, "w", newline="") as stream:
        recorder = CsvRecorder(stream)
        for pkt in packets:
            recorder.write(pkt)
        recorder.flush()
    return path


def load(name: str) -> list[TelemetryPacket]:
    with open(_path(name), newline="") as stream:
        return list(load_csv(stream))


def import_csv(name: str, text: str) -> Path:
    header = text.splitlines()[0].split(",") if text else []
    if header != list(_NAMES):
        raise InvalidName("CSV header does not match a Forza Telemetry Helper capture")
    path = _path(name)
    path.write_text(text)
    return path


def delete(name: str) -> None:
    path = _path(name)
    try:
        path.unlink()
    except FileNotFoundError:
        raise InvalidName(f"no such capture: {name!r}") from None


def list_captures() -> list[dict]:
    out = []
    for path in sorted(_dir().glob("*.csv")):
        stat = path.stat()
        with open(path, newline="") as stream:
            samples = sum(1 for _ in load_csv(stream))
        out.append(
            {
                "name": path.stem,
                "samples": samples,
                "saved_at": stat.st_mtime,
                "size_bytes": stat.st_size,
            }
        )
    return out
