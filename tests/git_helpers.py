from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


def tracked_paths(
    repository_root: Path,
    *pathspecs: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> list[str]:
    root = repository_root.resolve()
    command = [
        "git",
        "-c",
        f"safe.directory={root}",
        "-C",
        str(root),
        "ls-files",
        "--",
        *pathspecs,
    ]
    run = runner or subprocess.run
    try:
        result = run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "no Git diagnostic").strip()
        raise RuntimeError(f"git ls-files failed for the repository root: {detail}") from exc
    return result.stdout.splitlines()
