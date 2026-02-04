#!/usr/bin/env python3
import argparse
import os
import platform
import subprocess
from pathlib import Path

import yaml


def _run(argv):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        return f"missing ({exc})"
    output = (proc.stdout or proc.stderr or "").strip()
    if not output:
        return f"exit={proc.returncode}"
    return output.splitlines()[0]


def _run_multiline(argv):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        return f"missing ({exc})\n"
    output = (proc.stdout or proc.stderr or "").strip()
    if not output:
        output = f"exit={proc.returncode}"
    return output + "\n"


def _sha256(path: Path):
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ref_hash_rows(config_path: Path):
    rows = []
    if not config_path.exists():
        return rows
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return rows
    ref = cfg.get("ref") or {}
    for key in ("transcripts_fasta", "genome_fasta", "gtf"):
        value = ref.get(key)
        if not value:
            continue
        path = Path(value)
        if path.exists() and path.is_file():
            rows.append((f"ref.{key}.sha256", _sha256(path)))
        else:
            rows.append((f"ref.{key}.sha256", "missing"))
    return rows


def main():
    parser = argparse.ArgumentParser(description="Write run version manifest.")
    parser.add_argument("--outdir", required=True, help="Pipeline output directory")
    parser.add_argument("--config", required=True, help="Resolved config path")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    run_dir = outdir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = Path(args.config)

    versions_path = run_dir / "versions.tsv"
    rows = [
        ("python", _run(["python", "--version"])),
        ("pip_freeze_count", _run(["python", "-c", "import pkg_resources; print(len(list(pkg_resources.working_set)))"])),
        ("snakemake", _run(["python", "-m", "snakemake", "--version"])),
        ("salmon", _run(["salmon", "--version"])),
        ("fastp", _run(["fastp", "--version"])),
        ("R", _run(["R", "--version"])),
        ("platform", platform.platform()),
    ]
    rows.extend(_ref_hash_rows(config_path))

    os_release = Path("/etc/os-release")
    if os_release.exists():
        rows.append(("os_release", os_release.read_text(encoding="utf-8", errors="ignore").replace("\n", "\\n")))
    else:
        rows.append(("os_release", "missing"))

    with versions_path.open("w", encoding="utf-8") as handle:
        handle.write("key\tvalue\n")
        for key, value in rows:
            handle.write(f"{key}\t{str(value).strip()}\n")

    session_info_path = run_dir / "sessionInfo.txt"
    session_info_path.write_text(
        _run_multiline(["Rscript", "-e", "sessionInfo()"]),
        encoding="utf-8",
    )

    pip_freeze_path = run_dir / "pip_freeze.txt"
    pip_freeze_path.write_text(
        _run_multiline(["python", "-m", "pip", "freeze"]),
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
