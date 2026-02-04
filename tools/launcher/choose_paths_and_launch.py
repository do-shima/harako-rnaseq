import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from urllib.parse import urlencode


LAUNCHER_PORT = 8601
IMAGE = "rnaseq_pipeline"
LAUNCHER_CMD = (
    "cd /app && streamlit run app/ui/launcher_ui.py "
    "--server.address 0.0.0.0 --server.port 8601 "
    "--server.headless true --browser.gatherUsageStats false --logger.level=warning"
)


def _show(kind: str, title: str, text: str):
    root = tk.Tk()
    root.withdraw()
    if kind == "error":
        messagebox.showerror(title, text)
    elif kind == "warning":
        messagebox.showwarning(title, text)
    else:
        messagebox.showinfo(title, text)
    root.destroy()


def _pick_dir(title: str, initialdir: str):
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(title=title, initialdir=initialdir, mustexist=True)
    root.destroy()
    return path


def _check_docker():
    if shutil.which("docker") is None:
        return False, "Docker command is not available on PATH."
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, text=True)
    except OSError as exc:
        return False, str(exc)
    if probe.returncode != 0:
        details = (probe.stderr or probe.stdout or "").strip()
        return False, details or "Docker is not running."
    return True, ""


def _repo_root():
    return Path(__file__).resolve().parents[2]


def main():
    ok, detail = _check_docker()
    if not ok:
        _show(
            "error",
            "Docker unavailable",
            "Docker Desktop must be running before launch.\n\n"
            + detail
            + "\n\nOn Windows also confirm drive sharing is enabled for selected folders.",
        )
        return 2

    repo_default = str(_repo_root())
    repo_path = _pick_dir("Select repository directory (contains justfile)", repo_default)
    if not repo_path:
        _show("info", "Canceled", "Repository directory was not selected.")
        return 1

    input_path = _pick_dir("Select input directory (host path mounted to /input)", repo_path)
    if not input_path:
        _show("info", "Canceled", "Input directory was not selected.")
        return 1

    out_path = _pick_dir("Select output directory (host path mounted to /output)", input_path)
    if not out_path:
        _show("info", "Canceled", "Output directory was not selected.")
        return 1

    cmd = [
        "docker",
        "run",
        "--rm",
        "-p",
        f"127.0.0.1:{LAUNCHER_PORT}:{LAUNCHER_PORT}",
        "-v",
        f"{repo_path}:/app",
        IMAGE,
        "bash",
        "-lc",
        LAUNCHER_CMD,
    ]

    proc = subprocess.Popen(cmd)
    time.sleep(1.5)
    if proc.poll() is not None and proc.returncode != 0:
        _show(
            "error",
            "Launcher failed",
            "Docker launcher exited immediately.\n\n"
            "Check Docker logs in this terminal.\n"
            "On Windows ensure Docker Desktop drive sharing allows the selected repository path.",
        )
        return proc.returncode

    os_param = "powershell" if os.name == "nt" else "bash"
    query = urlencode(
        {
            "repo": repo_path,
            "input": input_path,
            "out": out_path,
            "os": os_param,
            "use_just": "true",
        }
    )
    webbrowser.open(f"http://127.0.0.1:{LAUNCHER_PORT}/?{query}")
    _show(
        "info",
        "Launcher started",
        "Opened http://127.0.0.1:8601 with selected paths.\n"
        "Keep this terminal open while using the launcher.",
    )
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
