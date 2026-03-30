import subprocess
import sys
from pathlib import Path

from app.cli import _filter_snakemake_flags
from app.run import RunArgs, build_snakemake_cmd, snakemake_workdir
from app.ui.run import build_snakemake_base_cmd


def _assert(condition: bool, message: str):
    if not condition:
        raise SystemExit(message)


def _test_cli_cmd_has_no_reason_flag():
    args = RunArgs(
        input="/input",
        output="/output",
        config="/output/config.yaml",
        align="none",
        engine="real",
        threads="1",
    )
    cmd = build_snakemake_cmd(args)
    _filter_snakemake_flags(
        cmd,
        printshellcmds=True,
        latency_wait=60,
        rerun_incomplete=True,
        quiet_categories=["reason"],
    )
    _assert("--reason" not in cmd, f"Unexpected --reason in command: {' '.join(cmd)}")
    _assert("--quiet" in cmd, f"Missing --quiet in command: {' '.join(cmd)}")
    qidx = cmd.index("--quiet")
    _assert("reason" in cmd[qidx + 1 :], f"Missing quiet category 'reason' in command: {' '.join(cmd)}")


def _test_ui_source_has_no_reason_flag():
    repo_root = Path(__file__).resolve().parents[1]
    ui_path = repo_root / "app" / "ui" / "app_ui.py"
    text = ui_path.read_text(encoding="utf-8")
    _assert("--reason" not in text, f"app_ui.py still contains --reason: {ui_path}")


def _test_real_engine_uses_separate_workdir():
    args = RunArgs(
        input="/input",
        output="/output",
        config="/output/config.yaml",
        align="none",
        engine="real",
        threads="1",
    )
    cmd = build_snakemake_cmd(args)
    _assert("--directory" in cmd, f"Missing --directory in command: {' '.join(cmd)}")
    workdir = cmd[cmd.index("--directory") + 1]
    _assert(workdir != "/output", f"Snakemake workdir must not be the bind-mounted output: {' '.join(cmd)}")
    _assert(workdir == snakemake_workdir("/output"), f"Unexpected Snakemake workdir: {' '.join(cmd)}")


def _test_ui_base_cmd_uses_separate_workdir():
    run_dir = Path("/output/data_out/demo")
    cmd = build_snakemake_base_cmd(run_dir, Path("/output/config.yaml"), 1)
    _assert("--directory" in cmd, f"Missing --directory in UI command: {' '.join(cmd)}")
    workdir = cmd[cmd.index("--directory") + 1]
    _assert(workdir != str(run_dir), f"UI Snakemake workdir must not equal run_dir: {' '.join(cmd)}")
    _assert(workdir == snakemake_workdir(str(run_dir)), f"Unexpected UI Snakemake workdir: {' '.join(cmd)}")


def _test_snakemake_help():
    proc = subprocess.run([sys.executable, "-m", "snakemake", "--help"], capture_output=True, text=True)
    _assert(proc.returncode == 0, f"python -m snakemake --help failed: {(proc.stderr or proc.stdout)}")


def main():
    _test_cli_cmd_has_no_reason_flag()
    _test_ui_source_has_no_reason_flag()
    _test_real_engine_uses_separate_workdir()
    _test_ui_base_cmd_uses_separate_workdir()
    _test_snakemake_help()


if __name__ == "__main__":
    main()
