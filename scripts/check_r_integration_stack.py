from __future__ import annotations

import argparse
import functools
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence


REQUIRED_R_PACKAGES = (
    "DESeq2",
    "dplyr",
    "ggplot2",
    "jsonlite",
    "readr",
    "rmarkdown",
    "yaml",
)
HOST_SKIP_REASON = (
    "Real DESeq2 integration requires Rscript and the declared R package stack; "
    "validated in Docker CI."
)


@dataclass(frozen=True)
class RIntegrationStack:
    available: bool
    reason_code: str
    rscript: str | None
    required_packages: tuple[str, ...] = REQUIRED_R_PACKAGES


def probe_r_integration_stack(
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> RIntegrationStack:
    rscript = which("Rscript")
    if not rscript:
        return RIntegrationStack(False, "rscript_missing", None)

    quoted = ", ".join(f'"{package}"' for package in REQUIRED_R_PACKAGES)
    expression = (
        f"packages <- c({quoted}); "
        "missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly=TRUE)]; "
        "if (length(missing)) quit(status=2)"
    )
    result = runner(
        [rscript, "-e", expression],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return RIntegrationStack(False, "r_packages_missing", rscript)
    return RIntegrationStack(True, "available", rscript)


@functools.cache
def r_integration_stack() -> RIntegrationStack:
    return probe_r_integration_stack()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the R stack required by real DESeq2 integration tests."
    )
    parser.parse_args(argv)
    status = r_integration_stack()
    if status.available:
        print(
            "Real DESeq2 integration stack available: "
            + ", ".join(status.required_packages)
        )
        return 0
    print(f"Real DESeq2 integration stack unavailable: {status.reason_code}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
