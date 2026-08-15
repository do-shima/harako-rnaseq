"""Immutable run configuration, metadata, identity, and compatibility services."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from app.core.analysis import AnalysisPlanError, resolve_analysis_plan


def load_json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_run_config_path(run_dir: Path) -> Path:
    direct_run_dir = Path(run_dir)
    direct_config = direct_run_dir / "run" / "config_resolved.yaml"
    if direct_config.exists():
        return direct_config

    raw_run_dir = str(run_dir)
    if "\\" in raw_run_dir:
        normalized_config = Path(raw_run_dir.replace("\\", "/")) / "run" / "config_resolved.yaml"
        if normalized_config.exists():
            return normalized_config
    raise FileNotFoundError(f"Missing run-local config: {direct_config}")


def metadata_path(run_dir: Path) -> Path:
    return Path(run_dir) / "run" / "metadata.json"


def write_run_metadata(run_dir: Path, metadata: dict[str, Any]) -> Path:
    path = metadata_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return path


def prepare_run_directory(mode: str, run_dir: Path, run_exists: bool) -> Path:
    if mode in ("resume", "open_existing") and run_exists:
        return run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_frozen_run_config(
    run_dir: Path,
    base_cfg: dict[str, Any],
    sample_table_source: Path | None = None,
) -> Path:
    run_dir = Path(run_dir)
    run_cfg = dict(base_cfg or {})
    run_cfg["output"] = str(run_dir)
    run_meta = run_dir / "run"
    run_meta.mkdir(parents=True, exist_ok=True)
    if sample_table_source is not None:
        sample_table_source = Path(sample_table_source)
        if not sample_table_source.exists():
            raise FileNotFoundError(f"Missing session sample table: {sample_table_source}")
        sample_table_dest = run_meta / "metadata" / "samples.tsv"
        sample_table_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample_table_source, sample_table_dest)
        run_cfg["sample_table"] = str(sample_table_dest)
    config_path = run_meta / "config_resolved.yaml"
    config_path.write_text(yaml.safe_dump(run_cfg, sort_keys=False), encoding="utf-8")
    return config_path


def update_run_metadata(run_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    path = metadata_path(run_dir)
    current = load_json_mapping(path)
    for key, value in (patch or {}).items():
        if key == "runtime_logs" and isinstance(value, dict):
            existing = current.get("runtime_logs") if isinstance(current.get("runtime_logs"), dict) else {}
            merged = dict(existing)
            merged.update({nested_key: nested_value for nested_key, nested_value in value.items() if nested_value not in ("", None)})
            current[key] = merged
            continue
        current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    return current


def runtime_paths_patch(
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    main_log_path: Path | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    runtime_logs = {}
    if stdout_path is not None:
        runtime_logs["stdout"] = str(stdout_path)
    if stderr_path is not None:
        runtime_logs["stderr"] = str(stderr_path)
    if main_log_path is not None:
        runtime_logs["main_log"] = str(main_log_path)
    if workdir is not None:
        runtime_logs["workdir"] = str(workdir)
    return {"runtime_logs": runtime_logs}


def record_runtime_log_paths(
    run_dir: Path,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    main_log_path: Path | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    patch = runtime_paths_patch(
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        main_log_path=main_log_path,
        workdir=workdir,
    )
    if not patch["runtime_logs"]:
        return load_json_mapping(metadata_path(run_dir))
    return update_run_metadata(run_dir, patch)


def available_run_modes(
    *,
    run_exists: bool,
    has_frozen_run: bool,
    has_report: bool,
    resume_allowed: bool = True,
) -> list[str]:
    if not run_exists:
        return ["start_new"]
    modes: list[str] = []
    if has_report:
        modes.append("open_existing")
    if has_frozen_run and resume_allowed:
        modes.append("resume")
    return modes or ["start_new"]


def _read_sample_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        peek = handle.read(2048)
        handle.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(peek, delimiters="\t,").delimiter
        except csv.Error:
            delimiter = "\t"
        return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]


def assess_frozen_analysis_plan(config_path: Path) -> dict[str, Any]:
    config_path = Path(config_path)
    config = load_yaml_mapping(config_path)
    sample_table = Path(str(config.get("sample_table") or ""))
    if not sample_table.is_absolute():
        sample_table = config_path.parent / sample_table
    if not sample_table.exists():
        return {
            "resume_allowed": False,
            "legacy": "analysis_plan" not in config,
            "error": f"Frozen sample table not found: {sample_table}",
        }
    rows = _read_sample_rows(sample_table)
    try:
        plan, legacy = resolve_analysis_plan(config.get("analysis_plan"), rows, legacy_frozen=True)
    except AnalysisPlanError as exc:
        return {"resume_allowed": False, "legacy": "analysis_plan" not in config, "error": str(exc)}
    return {"resume_allowed": True, "legacy": legacy, "plan": plan, "error": ""}


def load_run_record(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    config_path = resolve_run_config_path(run_dir)
    run_meta = run_dir / "run"
    manifest_path = run_meta / "manifest.json"
    run_metadata_path = run_meta / "metadata.json"
    return {
        "run_dir": run_dir,
        "config_path": config_path,
        "config": load_yaml_mapping(config_path),
        "manifest_path": manifest_path,
        "manifest": load_json_mapping(manifest_path),
        "metadata_path": run_metadata_path,
        "metadata": load_json_mapping(run_metadata_path),
        "analysis_compatibility": assess_frozen_analysis_plan(config_path),
    }


def normalize_project_slug(name: str, default_name: str) -> str:
    text = (name or "").strip().replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default_name


def build_run_dirname(run_config: dict[str, Any], run_id: str, default_project_name: str) -> str:
    slug = normalize_project_slug(str(run_config.get("project_name", "")), default_project_name)
    return f"{slug}_{run_id}"


def fingerprint_fastq(input_root: Path, fastq_relative_paths: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for relative in sorted(fastq_relative_paths):
        path = input_root / relative
        if not path.exists():
            items.append({"path": relative, "exists": False})
            continue
        stat = path.stat()
        items.append({"path": relative, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)})
    return items


def prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item_clean = prune_empty(item)
            if item_clean in ("", None, [], {}):
                continue
            cleaned[key] = item_clean
        return cleaned
    if isinstance(value, list):
        return [item for item in (prune_empty(item) for item in value) if item not in ("", None, [], {})]
    return value


def build_manifest_payload(
    payload: dict[str, Any],
    rows_raw: list[dict[str, Any]],
    fastq_rel: list[str],
    coerce_rows_raw: Callable[[list[dict[str, Any]]], list[dict[str, str]]],
    git_rev: str,
    input_root: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "config": prune_empty(dict(payload)),
        "samples": coerce_rows_raw(rows_raw),
        "fastq": fingerprint_fastq(input_root, fastq_rel),
        "git_rev": git_rev,
    }


def manifest_run_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_run_manifest(run_dir: Path, run_id: str, payload: dict[str, Any]) -> Path:
    run_meta = run_dir / "run"
    run_meta.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    manifest_path = run_meta / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path
