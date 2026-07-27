from __future__ import annotations

import hashlib
import csv
import json
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from app.run import snakemake_workdir
from app.ui.error_messages import extract_incomplete_files
from app.analysis_eligibility import AnalysisPlanError, resolve_analysis_plan

TRACEBACK_LINE_RE = re.compile(r"^\s*(Traceback \(most recent call last\):|File \".*\", line \d+|During handling of the above exception)")
PATH_TOKEN_RE = re.compile(r"([A-Za-z]:[\\/][^\s:]+|/[^\\\s:]+(?:/[^\s:]+)*)")


def shell_join_cmd(cmd: list[str]) -> str:
    return shlex.join([str(item) for item in cmd])


def extract_run_dir_from_cmd(cmd: list[str]) -> Path | None:
    for token in cmd:
        if isinstance(token, str) and token.startswith("output="):
            try:
                return Path(token.split("=", 1)[1])
            except Exception:
                return None
    for idx, token in enumerate(cmd):
        if token == "--directory" and idx + 1 < len(cmd):
            try:
                return Path(cmd[idx + 1])
            except Exception:
                return None
    return None


def snakemake_version_text() -> str:
    try:
        proc = subprocess.run(["python", "-m", "snakemake", "--version"], capture_output=True, text=True)
    except Exception:
        return "unknown"
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0].strip() if text else "unknown"


def write_snakemake_debug_files(run_dir: Path | None, cmd: list[str], stdout_text: str, stderr_text: str, version_text: str = "unknown") -> None:
    if run_dir is None:
        return
    try:
        run_meta = run_dir / "run"
        run_meta.mkdir(parents=True, exist_ok=True)
        cmd_line = shell_join_cmd(cmd)
        (run_meta / "snakemake_cmd.txt").write_text(cmd_line + "\n", encoding="utf-8")
        (run_meta / "snakemake_stdout.txt").write_text(stdout_text or "", encoding="utf-8")
        (run_meta / "snakemake_stderr.txt").write_text(stderr_text or "", encoding="utf-8")
        (run_meta / "snakemake_version.txt").write_text((version_text or "unknown") + "\n", encoding="utf-8")
        (run_meta / "snakemake.cmd.txt").write_text(cmd_line + "\n", encoding="utf-8")
        (run_meta / "snakemake.stdout.log").write_text(stdout_text or "", encoding="utf-8")
        (run_meta / "snakemake.stderr.log").write_text(stderr_text or "", encoding="utf-8")
        workdir = None
        for idx, token in enumerate(cmd):
            if token == "--directory" and idx + 1 < len(cmd):
                try:
                    workdir = Path(cmd[idx + 1])
                except Exception:
                    workdir = None
                break
        main_log_text = "\n".join(part for part in [stdout_text or "", stderr_text or ""] if part)
        main_log_path = None
        extracted = extract_snakemake_log_path(main_log_text)
        if extracted:
            try:
                main_log_path = Path(extracted)
            except Exception:
                main_log_path = None
        record_runtime_log_paths(
            run_dir,
            stdout_path=run_meta / "snakemake_stdout.txt",
            stderr_path=run_meta / "snakemake_stderr.txt",
            main_log_path=main_log_path,
            workdir=workdir,
        )
    except Exception:
        return


def run_cmd(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if any(str(part).lower() == "snakemake" for part in cmd):
        run_dir = extract_run_dir_from_cmd(cmd)
        write_snakemake_debug_files(run_dir, cmd, proc.stdout or "", proc.stderr or "", snakemake_version_text())
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output.strip()


def build_snakemake_base_cmd(run_dir: Path, config_path: Path, threads: int) -> list[str]:
    return [
        "python",
        "-m",
        "snakemake",
        "--directory",
        str(snakemake_workdir(str(run_dir))),
        "-s",
        "workflow/Snakefile",
        "--configfile",
        str(config_path),
        "--config",
        "input=/input",
        f"output={run_dir}",
        "--cores",
        str(int(threads)),
        "-p",
        "--show-failed-logs",
        "--latency-wait",
        "60",
    ]


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


def write_frozen_run_config(run_dir: Path, base_cfg: dict[str, Any], sample_table_source: Path | None = None) -> Path:
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
    cfg_path = run_meta / "config_resolved.yaml"
    cfg_path.write_text(yaml.safe_dump(run_cfg, sort_keys=False), encoding="utf-8")
    return cfg_path


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_yaml_file(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def update_run_metadata(run_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(run_dir)
    path = metadata_path(run_dir)
    current = _load_json_file(path)
    for key, value in (patch or {}).items():
        if key == "runtime_logs" and isinstance(value, dict):
            existing = current.get("runtime_logs") if isinstance(current.get("runtime_logs"), dict) else {}
            merged = dict(existing)
            merged.update({k: v for k, v in value.items() if v not in ("", None)})
            current[key] = merged
            continue
        current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    return current


def _runtime_paths_patch(stdout_path: Path | None = None, stderr_path: Path | None = None, main_log_path: Path | None = None, workdir: Path | None = None) -> dict[str, Any]:
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


def record_runtime_log_paths(run_dir: Path, stdout_path: Path | None = None, stderr_path: Path | None = None, main_log_path: Path | None = None, workdir: Path | None = None) -> dict[str, Any]:
    patch = _runtime_paths_patch(stdout_path=stdout_path, stderr_path=stderr_path, main_log_path=main_log_path, workdir=workdir)
    if not patch["runtime_logs"]:
        return _load_json_file(metadata_path(run_dir))
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
    config = _load_yaml_file(config_path)
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
        plan, legacy = resolve_analysis_plan(
            config.get("analysis_plan"),
            rows,
            legacy_frozen=True,
        )
    except AnalysisPlanError as exc:
        return {
            "resume_allowed": False,
            "legacy": "analysis_plan" not in config,
            "error": str(exc),
        }
    return {
        "resume_allowed": True,
        "legacy": legacy,
        "plan": plan,
        "error": "",
    }


def build_dev_summary(*, ui_session_id: str, run_id: str, session_config_path: Path, run_dir: Path | None, validation_state: dict[str, Any] | None) -> dict[str, Any]:
    summary = {
        "ui_session_id": str(ui_session_id or ""),
        "run_id": str(run_id or ""),
        "session_config_path": str(session_config_path),
        "validation": {
            "ok": bool((validation_state or {}).get("ok", False)),
            "detail": str((validation_state or {}).get("detail") or "").strip(),
            "ts": str((validation_state or {}).get("ts") or ""),
        },
    }
    if run_dir:
        summary["run_dir"] = str(run_dir)
        try:
            summary["run_local_config_path"] = str(resolve_run_config_path(run_dir))
        except FileNotFoundError:
            summary["run_local_config_path"] = ""
    else:
        summary["run_dir"] = ""
        summary["run_local_config_path"] = ""
    return summary


def format_public_path(path_like: str | Path, *, run_dir: Path | None = None, output_root: Path | None = None) -> str:
    text = str(path_like or "").strip()
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    run_dir_norm = str(Path(run_dir)).replace("\\", "/") if run_dir else ""
    output_root_norm = str(Path(output_root)).replace("\\", "/") if output_root else "/output"
    if run_dir_norm and normalized.startswith(run_dir_norm):
        suffix = normalized[len(run_dir_norm) :].lstrip("/")
        return f"run/{suffix}" if suffix else "run"
    if output_root_norm and normalized.startswith(output_root_norm):
        suffix = normalized[len(output_root_norm) :].lstrip("/")
        return f"/output/{suffix}" if suffix else "/output"
    return Path(normalized).name or normalized


def sanitize_public_text(text: str, *, run_dir: Path | None = None, output_root: Path | None = None) -> str:
    raw = text or ""
    if not raw:
        return ""

    def _replace(match: re.Match[str]) -> str:
        return format_public_path(match.group(0), run_dir=run_dir, output_root=output_root)

    return PATH_TOKEN_RE.sub(_replace, raw)


def format_public_error(text: str, *, run_dir: Path | None = None, output_root: Path | None = None, max_lines: int = 4) -> str:
    if not text:
        return ""
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if TRACEBACK_LINE_RE.match(line):
            continue
        if line.startswith("File ") and ", line " in line:
            continue
        lines.append(sanitize_public_text(line, run_dir=run_dir, output_root=output_root))
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)


def load_run_record(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    config_path = resolve_run_config_path(run_dir)
    run_meta = run_dir / "run"
    manifest_path = run_meta / "manifest.json"
    metadata_path = run_meta / "metadata.json"
    return {
        "run_dir": run_dir,
        "config_path": config_path,
        "config": _load_yaml_file(config_path),
        "manifest_path": manifest_path,
        "manifest": _load_json_file(manifest_path),
        "metadata_path": metadata_path,
        "metadata": _load_json_file(metadata_path),
        "analysis_compatibility": assess_frozen_analysis_plan(config_path),
    }


def pre_run_guard(
    run_dir: Path,
    config_path: Path,
    threads: int,
    work_id: str,
    run_cmd_logged: Callable[[list[str], str, str], tuple[int, str]],
) -> dict[str, Any]:
    base_cmd = build_snakemake_base_cmd(run_dir, config_path, threads)
    dry_cmd = base_cmd + ["-n", "--", "report"]
    code, output = run_cmd_logged(dry_cmd, work_id, "dry_run")
    if code == 0:
        return {"status": "ok", "output": output}

    text = output or ""
    if "Directory cannot be locked" in text or ".snakemake/lock" in text:
        unlock_cmd = base_cmd + ["--unlock"]
        run_cmd_logged(unlock_cmd, work_id, "unlock")
        code2, output2 = run_cmd_logged(dry_cmd, work_id, "dry_run_after_unlock")
        if code2 == 0:
            return {"status": "ok", "output": output2}
        return {"status": "lock", "output": output2 or output}

    if "IncompleteFilesException" in text or "Incomplete files" in text:
        files = extract_incomplete_files(text)
        return {"status": "incomplete", "output": text, "files": files}

    return {"status": "error", "output": text}


def normalize_project_slug(name: str, default_name: str) -> str:
    import re as _re

    text = (name or "").strip().replace(" ", "_")
    text = _re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    text = _re.sub(r"_+", "_", text).strip("_")
    return text or default_name


def build_run_dirname(run_config: dict[str, Any], run_id: str, default_project_name: str) -> str:
    slug = normalize_project_slug(str(run_config.get("project_name", "")), default_project_name)
    return f"{slug}_{run_id}"


def fingerprint_fastq(input_root: Path, fastq_rel: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for rel in sorted(fastq_rel):
        p = input_root / rel
        if not p.exists():
            items.append({"path": rel, "exists": False})
            continue
        stat = p.stat()
        items.append({"path": rel, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)})
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


def build_manifest_payload(payload: dict[str, Any], rows_raw: list[dict[str, Any]], fastq_rel: list[str], coerce_rows_raw: Callable[[list[dict[str, Any]]], list[dict[str, str]]], git_rev: str, input_root: Path) -> dict[str, Any]:
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


def snakemake_log_candidates(run_dir: Path, limit: int = 10) -> dict[str, Any]:
    if not run_dir or not run_dir.exists():
        return {"primary": None, "candidates": []}

    seen: set[str] = set()
    collected: list[dict[str, Any]] = []
    meta = _load_json_file(metadata_path(run_dir))
    runtime_logs = meta.get("runtime_logs") if isinstance(meta.get("runtime_logs"), dict) else {}

    def _add(path: Path, kind: str) -> None:
        try:
            p = path.resolve()
        except Exception:
            p = path
        key = str(p)
        if key in seen or not path.exists() or not path.is_file():
            return
        seen.add(key)
        try:
            size = int(path.stat().st_size)
        except Exception:
            size = 0
        collected.append({"path": path, "size": size, "kind": kind})

    for key, kind in (("main_log", "main"), ("stderr", "stderr"), ("stdout", "stdout")):
        value = runtime_logs.get(key)
        if value:
            _add(Path(str(value)), kind)

    workdir = Path(str(runtime_logs.get("workdir"))) if runtime_logs.get("workdir") else None
    snk_log_root = (workdir / ".snakemake" / "log") if workdir else (run_dir / ".snakemake" / "log")
    snk_logs = sorted(snk_log_root.glob("*.snakemake.log"), key=lambda p: p.stat().st_mtime, reverse=True) if snk_log_root.exists() else []
    for p in snk_logs[:1]:
        _add(p, "main")

    rule_logs = sorted((run_dir / "logs").glob("**/*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in rule_logs:
        if len(collected) >= limit:
            break
        _add(p, "rule")

    salmon_files = sorted((run_dir / "salmon").glob("**/*"), key=lambda p: p.stat().st_mtime, reverse=True) if (run_dir / "salmon").exists() else []
    for p in salmon_files:
        if len(collected) >= limit:
            break
        if p.is_file():
            _add(p, "salmon")

    primary = collected[0] if collected else None
    return {"primary": primary, "candidates": collected[:limit], "metadata": runtime_logs}


def summarize_failure(text: str) -> dict[str, str]:
    raw = text or ""
    if "MissingInputException" in raw:
        return {
            "cause": "Input files are missing (fastp outputs were not generated, were deleted, or naming is inconsistent).",
            "action": "Rerun from fastp and verify R1/R2 naming and report input synchronization.",
            "kind": "missing_input",
        }
    if "IncompleteFilesException" in raw:
        return {
            "cause": "Previous outputs are marked incomplete.",
            "action": "Delete incomplete outputs and continue, or rerun with --rerun-incomplete.",
            "kind": "incomplete",
        }
    if "UnicodeDecodeError" in raw and "0x8b" in raw:
        return {
            "cause": "A gzip file is being read as plain text.",
            "action": "Use gzip-aware preprocessing and re-run from fastp.",
            "kind": "gzip_decode",
        }
    if "CalledProcessError" in raw or "non-zero exit status" in raw:
        return {
            "cause": "An external command exited with a non-zero code.",
            "action": "Inspect the failed rule logs for exact command and stderr details.",
            "kind": "called_process",
        }
    return {
        "cause": "Snakemake failed before report completion.",
        "action": "Inspect the logs below and rerun after fixing the root cause.",
        "kind": "generic",
    }


def failure_debug_commands(run_dir: Path) -> list[str]:
    p = str(run_dir)
    meta = _load_json_file(metadata_path(run_dir))
    runtime_logs = meta.get("runtime_logs") if isinstance(meta.get("runtime_logs"), dict) else {}
    workdir = str(runtime_logs.get("workdir") or snakemake_workdir(p))
    try:
        config_path = str(resolve_run_config_path(run_dir))
    except FileNotFoundError:
        config_path = "<missing run/config_resolved.yaml>"
    return [
        f"find {p}/run -maxdepth 1 -type f -name \"snakemake*\" -print",
        f"find {p}/logs -type f -maxdepth 3 -name \"*.log\" -print",
        "python -m snakemake --snakefile /app/workflow/Snakefile "
        f"--directory {workdir} -n -p --show-failed-logs "
        f"--configfiles {config_path} --config input=/input output={p}",
    ]


def extract_snakemake_log_path(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"(/?\.snakemake[\\/]+log[\\/][^\s]+)", text)
    if match:
        return match.group(1)
    return ""


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
