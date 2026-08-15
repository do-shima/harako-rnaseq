"""Small filesystem mutation boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path


def write_json(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def directory_is_writable(path: Path) -> bool:
    test_path = path / ".write_test"
    try:
        test_path.write_text("ok\n", encoding="utf-8")
        return True
    except Exception:
        return False
    finally:
        try:
            test_path.unlink()
        except Exception:
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
