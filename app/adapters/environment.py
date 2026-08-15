"""Host-tool probes used by validation and provenance services."""

from __future__ import annotations

import shutil
import subprocess


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
