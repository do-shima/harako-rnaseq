from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.ui.error_messages import extract_incomplete_files


def shell_join_cmd(cmd: list[str]) -> str:
    return shlex.join([str(item) for item in cmd])


def extract_run_dir_from_cmd(cmd: list[str]) -> Path | None:
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
        str(run_dir),
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

    def _add(path: Path) -> None:
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
        collected.append({"path": path, "size": size})

    snk_logs = sorted((run_dir / ".snakemake" / "log").glob("*.snakemake.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in snk_logs[:1]:
        _add(p)

    rule_logs = sorted((run_dir / "logs").glob("**/*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in rule_logs:
        if len(collected) >= limit:
            break
        _add(p)

    salmon_files = sorted((run_dir / "salmon").glob("**/*"), key=lambda p: p.stat().st_mtime, reverse=True) if (run_dir / "salmon").exists() else []
    for p in salmon_files:
        if len(collected) >= limit:
            break
        if p.is_file():
            _add(p)

    primary = collected[0] if collected else None
    return {"primary": primary, "candidates": collected[:limit]}


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
    return [
        f"ls -lah {p}/.snakemake/log | tail -n 50",
        f"tail -n 200 {p}/.snakemake/log/*.snakemake.log",
        f"find {p}/logs -type f -maxdepth 3 -name \"*.log\" -print",
        "python -m snakemake --snakefile /app/workflow/Snakefile -n -p --show-failed-logs "
        f"--configfiles /output/config.yaml --config input=/input output={p}",
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
