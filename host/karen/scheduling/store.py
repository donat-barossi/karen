"""Persistenza sveglie e timer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DATA: dict[str, Any] = {"alarms": [], "timers": []}


class ScheduleStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return json.loads(json.dumps(DEFAULT_DATA))
        try:
            with open(self._path) as f:
                data = json.load(f)
            data.setdefault("alarms", [])
            data.setdefault("timers", [])
            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Store corrotto (%s), reset", e)
            return json.loads(json.dumps(DEFAULT_DATA))

    def save(self, data: dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(self._path)
