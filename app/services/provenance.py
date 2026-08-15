"""Run-manifest identity and runtime provenance persistence."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from app.adapters.process import run_capture


def git_revision() -> str:
    repository_root = Path(__file__).resolve().parents[2]
    if not (repository_root / ".git").exists():
        return "unknown"
    try:
        process = run_capture(["git", "-C", str(repository_root), "rev-parse", "HEAD"])
        if process.returncode != 0:
            return "unknown"
        revision = process.stdout.strip()
        dirty = run_capture(["git", "-C", str(repository_root), "status", "--porcelain"])
        if dirty.returncode == 0 and (dirty.stdout or "").strip():
            revision += "+dirty"
        return revision
    except OSError:
        return "unknown"


def sha256_path(path: str) -> str:
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest_payload(config_path: str, resolved_config: dict[str, Any]) -> dict[str, Any]:
    reference_provenance = dict(resolved_config.get("reference_provenance") or {})
    reference_provenance.pop("requested_preset", None)
    payload = {
        "schema_version": 1,
        "config_sha256": sha256_path(config_path),
        "samples_sha256": "",
        "input": resolved_config.get("input"),
        "engine": resolved_config.get("engine"),
        "threads": resolved_config.get("threads"),
        "align": resolved_config.get("align"),
        "species": resolved_config.get("species"),
        "library_protocol": resolved_config.get("library_protocol"),
        "ref": resolved_config.get("ref"),
        "ref_preset": resolved_config.get("ref_preset"),
        "ref_release": resolved_config.get("ref_release"),
        "ref_manifest": resolved_config.get("ref_manifest"),
        "reference_provenance": reference_provenance or None,
        "analysis_plan": resolved_config.get("analysis_plan"),
        "contrast_mode": resolved_config.get("contrast_mode"),
        "contrast_ref": resolved_config.get("contrast_ref"),
        "contrast_pairs": resolved_config.get("contrast_pairs"),
        "contrasts": resolved_config.get("contrasts"),
        "enrichment": resolved_config.get("enrichment"),
        "git_rev": git_revision(),
    }
    sample_table = resolved_config.get("sample_table")
    if sample_table:
        payload["samples_sha256"] = sha256_path(sample_table)
    return payload


def manifest_run_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _capture_version(arguments: list[str]) -> str:
    try:
        process = run_capture(arguments)
        output = (process.stdout or process.stderr).strip().splitlines()
        return output[0] if output else "unknown"
    except OSError:
        return "unknown"


def write_run_provenance(
    output_dir: str,
    command: list[str],
    resolved_config: dict[str, Any],
    config_path: str,
    *,
    run_id_override: str = "",
    warning_sink: Callable[[str], None] | None = None,
) -> str:
    run_dir = Path(output_dir) / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
    (run_dir / "config_resolved.yaml").write_text(
        yaml.safe_dump(resolved_config, sort_keys=False),
        encoding="utf-8",
    )
    versions = {
        "python": _capture_version([sys.executable, "--version"]),
        "snakemake": _capture_version([sys.executable, "-m", "snakemake", "--version"]),
        "fastp": _capture_version(["fastp", "--version"]),
        "salmon": _capture_version(["salmon", "--version"]),
        "R": _capture_version(["Rscript", "--version"]),
    }
    reference = resolved_config.get("ref") if isinstance(resolved_config, dict) else {}
    if isinstance(reference, dict):
        for key in ("transcripts_fasta", "genome_fasta", "gtf"):
            reference_path = reference.get(key)
            if not reference_path:
                continue
            path = Path(reference_path)
            versions[f"ref.{key}.sha256"] = sha256_path(str(path)) if path.exists() and path.is_file() else "missing"
    os_release = Path("/etc/os-release")
    versions["os_release"] = (
        os_release.read_text(encoding="utf-8", errors="ignore").replace("\n", "\\n")
        if os_release.exists()
        else "missing"
    )
    with (run_dir / "versions.tsv").open("w", encoding="utf-8") as handle:
        handle.write("key\tvalue\n")
        for key, value in versions.items():
            handle.write(f"{key}\t{value}\n")
    with (run_dir / "pip_freeze.txt").open("w", encoding="utf-8") as handle:
        try:
            process = run_capture([sys.executable, "-m", "pip", "freeze"])
            handle.write(process.stdout or process.stderr or "unavailable\n")
        except OSError as exc:
            handle.write(f"missing ({exc})\n")
    with (run_dir / "sessionInfo.txt").open("w", encoding="utf-8") as handle:
        try:
            process = run_capture(["Rscript", "-e", "sessionInfo()"])
            handle.write(process.stdout or process.stderr or "unavailable\n")
        except OSError as exc:
            handle.write(f"missing ({exc})\n")
    (run_dir / "git_rev.txt").write_text(git_revision() + "\n", encoding="utf-8")

    payload = build_manifest_payload(config_path, resolved_config)
    computed_run_id = manifest_run_id(payload)
    run_id = run_id_override or computed_run_id
    if run_id_override and run_id_override != computed_run_id and warning_sink:
        warning_sink(f"Warning: provided run_id {run_id_override} != computed {computed_run_id}")
    manifest = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return run_id
