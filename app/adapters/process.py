"""Operating-system process boundary for UI and maintainer commands."""

from __future__ import annotations

import subprocess
from typing import IO, Mapping


PIPE = subprocess.PIPE


def start_process(
    command: list[str],
    *,
    stdout: IO[str] | int | None = None,
    stderr: IO[str] | int | None = None,
    text: bool = True,
    env: Mapping[str, str] | None = None,
    bufsize: int = -1,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command,
        stdout=stdout,
        stderr=stderr,
        text=text,
        env=dict(env) if env is not None else None,
        bufsize=bufsize,
    )


def run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)
