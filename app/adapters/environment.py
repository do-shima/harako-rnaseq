"""Host-tool probes used by validation and provenance services."""

from __future__ import annotations

import shutil
import subprocess
import os
from pathlib import Path


UNLIMITED_MEMORY_THRESHOLD = 1 << 60


def format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def normalize_memory_bytes(raw_value):
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value * (1024**2) if value <= 10_000_000 else value


def memory_limit_display_info(raw_value) -> dict[str, object]:
    normalized = normalize_memory_bytes(raw_value)
    if normalized is None:
        return {"bytes": None, "display": "-", "kind": "unknown", "approximate": False}
    if normalized >= UNLIMITED_MEMORY_THRESHOLD:
        return {"bytes": None, "display": "unlimited", "kind": "unlimited", "approximate": False}
    approximate = int(raw_value) <= 10_000_000
    label = f"detected {format_bytes(normalized)}"
    if approximate:
        label += " (approx.)"
    return {"bytes": normalized, "display": label, "kind": "limit", "approximate": approximate}


def _read_first_line(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def detect_cpu_limit() -> int:
    cpu_count = os.cpu_count() or 1
    cpu_max = Path("/sys/fs/cgroup/cpu.max")
    if cpu_max.exists():
        parts = _read_first_line(cpu_max).split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota, period = int(parts[0]), int(parts[1])
                if quota > 0 and period > 0:
                    return max(1, int(quota / period))
            except ValueError:
                pass
    quota_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if quota_path.exists() and period_path.exists():
        try:
            quota = int(_read_first_line(quota_path))
            period = int(_read_first_line(period_path))
            if quota > 0 and period > 0:
                return max(1, int(quota / period))
        except ValueError:
            pass
    return cpu_count


def detect_memory_limit() -> dict[str, object]:
    memory_max = Path("/sys/fs/cgroup/memory.max")
    if memory_max.exists():
        raw = _read_first_line(memory_max)
        if raw == "max":
            return {"bytes": None, "display": "unlimited", "kind": "unlimited", "approximate": False}
        try:
            info = memory_limit_display_info(int(raw))
            if info["kind"] in ("limit", "unlimited"):
                return info
        except ValueError:
            pass
    memory_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if memory_limit.exists():
        try:
            info = memory_limit_display_info(int(_read_first_line(memory_limit)))
            if info["kind"] in ("limit", "unlimited"):
                return info
        except ValueError:
            pass
    return memory_limit_display_info(None)


def tool_check_errors(skip: bool = False) -> list[str]:
    if skip:
        return []
    errors: list[str] = []
    for tool in ("fastp", "salmon", "Rscript"):
        if shutil.which(tool) is None:
            errors.append(f"Required tool not found in PATH: {tool}")
    if shutil.which("Rscript"):
        probe = subprocess.run(
            ["Rscript", "-e", "library(DESeq2); library(tximport)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode != 0:
            errors.append("R packages missing: DESeq2 and/or tximport (install inside container).")
    return errors
