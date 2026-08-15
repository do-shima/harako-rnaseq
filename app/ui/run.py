"""UI workflow helpers and compatibility exports for the shared run contract."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Callable

from app.adapters.snakemake import (
    build_ui_snakemake_cmd,
    run_capture,
    snakemake_version_text as adapter_snakemake_version_text,
    snakemake_workdir,
)
from app.services.run_contract import (
    assess_frozen_analysis_plan,
    available_run_modes,
    build_manifest_payload,
    build_run_dirname,
    fingerprint_fastq,
    load_json_mapping,
    load_run_record,
    load_yaml_mapping,
    manifest_run_id,
    metadata_path,
    normalize_project_slug,
    prune_empty,
    record_runtime_log_paths,
    resolve_run_config_path,
    update_run_metadata,
    write_frozen_run_config,
    write_run_manifest,
)
from app.ui.error_messages import extract_incomplete_files


TRACEBACK_LINE_RE = re.compile(
    r'^\s*(Traceback \(most recent call last\):|File ".*", line \d+|During handling of the above exception)'
)
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
    for index, token in enumerate(cmd):
        if token == "--directory" and index + 1 < len(cmd):
            try:
                return Path(cmd[index + 1])
            except Exception:
                return None
    return None


def snakemake_version_text() -> str:
    return adapter_snakemake_version_text()


def write_snakemake_debug_files(
    run_dir: Path | None,
    cmd: list[str],
    stdout_text: str,
    stderr_text: str,
    version_text: str = "unknown",
) -> None:
    if run_dir is None:
        return
    try:
        run_meta = run_dir / "run"
        run_meta.mkdir(parents=True, exist_ok=True)
        command_line = shell_join_cmd(cmd)
        (run_meta / "snakemake_cmd.txt").write_text(command_line + "\n", encoding="utf-8")
        (run_meta / "snakemake_stdout.txt").write_text(stdout_text or "", encoding="utf-8")
        (run_meta / "snakemake_stderr.txt").write_text(stderr_text or "", encoding="utf-8")
        (run_meta / "snakemake_version.txt").write_text((version_text or "unknown") + "\n", encoding="utf-8")
        (run_meta / "snakemake.cmd.txt").write_text(command_line + "\n", encoding="utf-8")
        (run_meta / "snakemake.stdout.log").write_text(stdout_text or "", encoding="utf-8")
        (run_meta / "snakemake.stderr.log").write_text(stderr_text or "", encoding="utf-8")
        workdir = None
        for index, token in enumerate(cmd):
            if token == "--directory" and index + 1 < len(cmd):
                try:
                    workdir = Path(cmd[index + 1])
                except Exception:
                    workdir = None
                break
        combined_log = "\n".join(part for part in [stdout_text or "", stderr_text or ""] if part)
        main_log_path = None
        extracted = extract_snakemake_log_path(combined_log)
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
    process = run_capture(cmd)
    if any(str(part).lower() == "snakemake" for part in cmd):
        run_dir = extract_run_dir_from_cmd(cmd)
        write_snakemake_debug_files(
            run_dir,
            cmd,
            process.stdout or "",
            process.stderr or "",
            snakemake_version_text(),
        )
    output = (process.stdout or "") + ("\n" + process.stderr if process.stderr else "")
    return process.returncode, output.strip()


def build_snakemake_base_cmd(run_dir: Path, config_path: Path, threads: int) -> list[str]:
    return build_ui_snakemake_cmd(run_dir, config_path, threads)


def build_dev_summary(
    *,
    ui_session_id: str,
    run_id: str,
    session_config_path: Path,
    run_dir: Path | None,
    validation_state: dict[str, Any] | None,
) -> dict[str, Any]:
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


def format_public_path(
    path_like: str | Path,
    *,
    run_dir: Path | None = None,
    output_root: Path | None = None,
) -> str:
    text = str(path_like or "").strip()
    if not text:
        return ""
    normalized = text.replace("\\", "/")
    run_dir_normalized = str(Path(run_dir)).replace("\\", "/") if run_dir else ""
    output_root_normalized = str(Path(output_root)).replace("\\", "/") if output_root else "/output"
    if run_dir_normalized and normalized.startswith(run_dir_normalized):
        suffix = normalized[len(run_dir_normalized) :].lstrip("/")
        return f"run/{suffix}" if suffix else "run"
    if output_root_normalized and normalized.startswith(output_root_normalized):
        suffix = normalized[len(output_root_normalized) :].lstrip("/")
        return f"/output/{suffix}" if suffix else "/output"
    return Path(normalized).name or normalized


def sanitize_public_text(
    text: str,
    *,
    run_dir: Path | None = None,
    output_root: Path | None = None,
) -> str:
    if not text:
        return ""

    def replace_path(match: re.Match[str]) -> str:
        return format_public_path(match.group(0), run_dir=run_dir, output_root=output_root)

    return PATH_TOKEN_RE.sub(replace_path, text)


def format_public_error(
    text: str,
    *,
    run_dir: Path | None = None,
    output_root: Path | None = None,
    max_lines: int = 4,
) -> str:
    if not text:
        return ""
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or TRACEBACK_LINE_RE.match(line) or (line.startswith("File ") and ", line " in line):
            continue
        lines.append(sanitize_public_text(line, run_dir=run_dir, output_root=output_root))
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)


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
        run_cmd_logged(base_cmd + ["--unlock"], work_id, "unlock")
        second_code, second_output = run_cmd_logged(dry_cmd, work_id, "dry_run_after_unlock")
        if second_code == 0:
            return {"status": "ok", "output": second_output}
        return {"status": "lock", "output": second_output or output}
    if "IncompleteFilesException" in text or "Incomplete files" in text:
        return {"status": "incomplete", "output": text, "files": extract_incomplete_files(text)}
    return {"status": "error", "output": text}


def snakemake_log_candidates(run_dir: Path, limit: int = 10) -> dict[str, Any]:
    if not run_dir or not run_dir.exists():
        return {"primary": None, "candidates": []}

    seen: set[str] = set()
    collected: list[dict[str, Any]] = []
    metadata = load_json_mapping(metadata_path(run_dir))
    runtime_logs = metadata.get("runtime_logs") if isinstance(metadata.get("runtime_logs"), dict) else {}

    def add(path: Path, kind: str) -> None:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        key = str(resolved)
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
            add(Path(str(value)), kind)

    workdir = Path(str(runtime_logs.get("workdir"))) if runtime_logs.get("workdir") else None
    snakemake_log_root = (workdir / ".snakemake" / "log") if workdir else (run_dir / ".snakemake" / "log")
    snakemake_logs = (
        sorted(snakemake_log_root.glob("*.snakemake.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if snakemake_log_root.exists()
        else []
    )
    for path in snakemake_logs[:1]:
        add(path, "main")
    for path in sorted((run_dir / "logs").glob("**/*.log"), key=lambda item: item.stat().st_mtime, reverse=True):
        if len(collected) >= limit:
            break
        add(path, "rule")
    salmon_files = (
        sorted((run_dir / "salmon").glob("**/*"), key=lambda item: item.stat().st_mtime, reverse=True)
        if (run_dir / "salmon").exists()
        else []
    )
    for path in salmon_files:
        if len(collected) >= limit:
            break
        if path.is_file():
            add(path, "salmon")
    return {
        "primary": collected[0] if collected else None,
        "candidates": collected[:limit],
        "metadata": runtime_logs,
    }


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
    run_path = str(run_dir)
    metadata = load_json_mapping(metadata_path(run_dir))
    runtime_logs = metadata.get("runtime_logs") if isinstance(metadata.get("runtime_logs"), dict) else {}
    workdir = str(runtime_logs.get("workdir") or snakemake_workdir(run_path))
    try:
        config_path = str(resolve_run_config_path(run_dir))
    except FileNotFoundError:
        config_path = "<missing run/config_resolved.yaml>"
    return [
        f'find {run_path}/run -maxdepth 1 -type f -name "snakemake*" -print',
        f'find {run_path}/logs -type f -maxdepth 3 -name "*.log" -print',
        "python -m snakemake --snakefile /app/workflow/Snakefile "
        f"--directory {workdir} -n -p --show-failed-logs "
        f"--configfiles {config_path} --config input=/input output={run_path}",
    ]


def extract_snakemake_log_path(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"(/?\.snakemake[\\/]+log[\\/][^\s]+)", text)
    return match.group(1) if match else ""


# Private compatibility names used by older UI code and focused tests.
_load_json_file = load_json_mapping
_load_yaml_file = load_yaml_mapping
