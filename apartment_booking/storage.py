"""JSON file persistence for apartments and bookings."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def empty_state() -> dict:
    return {"next_apartment_id": 1, "next_booking_id": 1, "apartments": {}, "bookings": {}}


class JsonStorage:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return empty_state()
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, state: dict) -> None:
        # Write to a temp file and rename so a crash never leaves a half-written file.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


class MemoryStorage:
    """In-memory storage, used by tests."""

    def __init__(self):
        self.state = empty_state()

    def load(self) -> dict:
        return json.loads(json.dumps(self.state))

    def save(self, state: dict) -> None:
        self.state = json.loads(json.dumps(state))
