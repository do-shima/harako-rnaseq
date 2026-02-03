import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox


def _pick_dir(title):
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(title=title)
    root.destroy()
    return path


def main():
    if shutil.which("docker") is None:
        messagebox.showerror("Error", "Docker is not available on PATH.")
        return 2

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    input_dir = _pick_dir("Select input directory (host)")
    if not input_dir:
        messagebox.showinfo("Canceled", "Input directory not selected.")
        return 1
    output_dir = _pick_dir("Select output directory (host)")
    if not output_dir:
        messagebox.showinfo("Canceled", "Output directory not selected.")
        return 1

    cmd = [
        "docker", "run", "--rm",
        "-p", "127.0.0.1:8501:8501",
        "-v", f"{repo}:/app",
        "-v", f"{input_dir}:/input:ro",
        "-v", f"{output_dir}:/output",
        "rnaseq_pipeline",
        "bash", "-lc",
        "cd /app && streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501",
    ]

    messagebox.showinfo(
        "Starting UI",
        "Launching Streamlit UI at http://127.0.0.1:8501\n\n"
        "Close the terminal or stop the container to exit.",
    )
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
