"""Préréglages perso, stockés dans %APPDATA%\\DonoTranscode\\presets.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import APP_NAME


def _file() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base / "presets.json"


def _load() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict):
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_file())


def user_presets(tab_id: str) -> dict:
    return _load().get(tab_id, {})


def save_preset(tab_id: str, name: str, settings: dict):
    data = _load()
    data.setdefault(tab_id, {})[name] = settings
    _save(data)


def delete_preset(tab_id: str, name: str):
    data = _load()
    data.get(tab_id, {}).pop(name, None)
    _save(data)
