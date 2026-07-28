#!/usr/bin/env python3
"""Create the ignored maintainer-approval record without overwriting decisions."""

from __future__ import annotations

import argparse
import pathlib
import shutil


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLE = ROOT / "config/release-approvals.example.json"
DEFAULT_OUTPUT = ROOT / "output/release-audit/maintainer-approvals.json"


def create_template(example: pathlib.Path, output: pathlib.Path) -> bool:
    if output.exists():
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    shutil.copyfile(example, temporary)
    temporary.replace(output)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--example", type=pathlib.Path, default=DEFAULT_EXAMPLE)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    created = create_template(args.example.resolve(), args.output.resolve())
    print("created" if created else "preserved existing approval file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
