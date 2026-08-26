"""Persistent user settings for the AI advisor, stored in ~/.fth/config.json.

Resolution order everywhere: defaults <- this file <- environment variables.
Override the file location with FTH_CONFIG (used by tests).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_FIELDS = ("key", "url", "model", "reasoning", "timeout", "lang", "provider")


def _path() -> Path:
    return Path(os.environ.get("FTH_CONFIG", Path.home() / ".fth" / "config.json"))


def load() -> dict[str, str]:
    """Stored settings; unknown/corrupt file yields {}."""
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}
    return {k: str(v) for k, v in data.items() if k in _FIELDS and v}


def save(**fields: str) -> dict[str, str]:
    """Merge fields into the stored config (empty string deletes a field)."""
    current = load()
    for name in _FIELDS:
        if name in fields:
            if fields[name]:
                current[name] = str(fields[name])
            else:
                current.pop(name, None)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2))
    return current
