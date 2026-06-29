from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock


class AuditLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def write(self, event: str, **details: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "time": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **details,
        }
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def redact(text: str, secret: str | None) -> str:
    return text.replace(secret, "***") if secret else text
