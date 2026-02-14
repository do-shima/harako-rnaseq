from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_ui_event(output_root: Path, event: str, data: dict[str, Any] | None = None) -> None:
    try:
        log_dir = output_root / "run"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "ui_events.log"
        payload = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        payload.update(data or {})
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def log_debug(output_root: Path, event: str, before: dict[str, Any], after: dict[str, Any]) -> None:
    try:
        changed = sorted([k for k in set(before) | set(after) if before.get(k) != after.get(k)])
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "before": before,
            "after": after,
            "changed_keys": changed,
        }
        log_dir = output_root / "run"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "ui_debug.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False))
    except Exception:
        return


def append_ui_command(output_root: Path, cmd: list[str], work_id: str, label: str) -> None:
    try:
        log_dir = output_root / "run"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "ui_commands.log"
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "work_id": work_id,
            "label": label,
            "cmd": cmd,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return
