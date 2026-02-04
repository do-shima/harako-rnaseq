import platform
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk


APP_CMD = (
    "streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501 "
    "--server.headless true --browser.gatherUsageStats false --logger.level=warning"
)


def _normalize_path(path_value: str, windows: bool):
    value = (path_value or "").strip()
    if not value:
        return ""
    if windows:
        value = value.replace("/", "\\")
        if re.match(r"^[A-Za-z]:[\\/]?$", value):
            return value[0:2] + "\\"
        if re.match(r"^\\\\[^\\]+\\[^\\]+\\?$", value):
            return value.rstrip("\\")
        return value.rstrip("\\/")
    if value == "/":
        return value
    return value.rstrip("/")


def _q(value: str):
    return '"' + value.replace('"', '\\"') + '"'


def _powershell_just(repo_path: str, input_path: str, out_path: str, embed_paths: bool):
    lines = [f"Set-Location {_q(repo_path)}"]
    if embed_paths:
        lines.append(f"$env:INPUT={_q(input_path)}; $env:OUT={_q(out_path)}; just ui")
    else:
        lines.extend(
            [
                f"$env:INPUT={_q(input_path)}",
                f"$env:OUT={_q(out_path)}",
                "just ui",
            ]
        )
    return "\n".join(lines)


def _powershell_docker(repo_path: str, input_path: str, out_path: str, image: str, port: int, embed_paths: bool):
    if embed_paths:
        return (
            f"docker run --rm -p 127.0.0.1:{port}:8501 "
            f'-v "{repo_path}:/app" -v "{input_path}:/input:ro" -v "{out_path}:/output" '
            f"{image} bash -lc 'cd /app && {APP_CMD}'"
        )
    return "\n".join(
        [
            f"$env:REPO={_q(repo_path)}",
            f"$env:INPUT={_q(input_path)}",
            f"$env:OUT={_q(out_path)}",
            (
                f"docker run --rm -p 127.0.0.1:{port}:8501 "
                f'-v "${{env:REPO}}:/app" -v "${{env:INPUT}}:/input:ro" -v "${{env:OUT}}:/output" '
                f"{image} bash -lc 'cd /app && {APP_CMD}'"
            ),
        ]
    )


def _bash_just(repo_path: str, input_path: str, out_path: str, embed_paths: bool):
    lines = [f"cd {_q(repo_path)}"]
    if embed_paths:
        lines.append(f"INPUT={_q(input_path)} OUT={_q(out_path)} just ui")
    else:
        lines.extend(
            [
                f"export INPUT={_q(input_path)}",
                f"export OUT={_q(out_path)}",
                "just ui",
            ]
        )
    return "\n".join(lines)


def _bash_docker(repo_path: str, input_path: str, out_path: str, image: str, port: int, embed_paths: bool):
    if embed_paths:
        return (
            f"docker run --rm -p 127.0.0.1:{port}:8501 "
            f'-v "{repo_path}:/app" -v "{input_path}:/input:ro" -v "{out_path}:/output" '
            f"{image} bash -lc 'cd /app && {APP_CMD}'"
        )
    return "\n".join(
        [
            f"REPO={_q(repo_path)}",
            f"INPUT={_q(input_path)}",
            f"OUT={_q(out_path)}",
            (
                f"docker run --rm -p 127.0.0.1:{port}:8501 "
                f'-v "$REPO:/app" -v "$INPUT:/input:ro" -v "$OUT:/output" '
                f"{image} bash -lc 'cd /app && {APP_CMD}'"
            ),
        ]
    )


class LauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RNA-seq Launcher (Path Picker)")
        self.geometry("980x760")
        self.minsize(900, 660)

        self.system_name = platform.system()
        self.repo_default = str(Path(__file__).resolve().parents[2])
        self.port_default = "8501"
        self.image_default = "rnaseq_pipeline"

        default_shell = "powershell" if self.system_name == "Windows" else "bash"
        self.shell_var = tk.StringVar(value=default_shell)
        self.repo_var = tk.StringVar(value=self.repo_default)
        self.input_var = tk.StringVar(value="")
        self.out_var = tk.StringVar(value="")
        self.port_var = tk.StringVar(value=self.port_default)
        self.image_var = tk.StringVar(value=self.image_default)
        self.embed_var = tk.BooleanVar(value=True)

        self.just_text = None
        self.docker_text = None
        self.status_var = tk.StringVar(value="Select folders, then click Generate commands.")
        self._build_ui()

    def _build_ui(self):
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text=f"Detected OS: {self.system_name}. This tool only generates commands (it does not run Docker).",
        ).pack(anchor="w")

        shell_row = ttk.Frame(frame)
        shell_row.pack(fill="x", pady=(10, 6))
        ttk.Label(shell_row, text="Shell:").pack(side="left")
        ttk.Radiobutton(shell_row, text="PowerShell", value="powershell", variable=self.shell_var).pack(side="left", padx=(10, 6))
        ttk.Radiobutton(shell_row, text="bash/zsh", value="bash", variable=self.shell_var).pack(side="left")

        ttk.Checkbutton(
            frame,
            text="Embed INPUT/OUT paths directly (recommended for beginners)",
            variable=self.embed_var,
        ).pack(anchor="w", pady=(0, 8))

        self._path_row(frame, "Repo path", self.repo_var, "Select repository directory")
        self._path_row(frame, "Input path", self.input_var, "Select input directory (mounted to /input)")
        self._path_row(frame, "Output path", self.out_var, "Select output directory (mounted to /output)")

        opts = ttk.Frame(frame)
        opts.pack(fill="x", pady=(4, 8))
        ttk.Label(opts, text="Port:").pack(side="left")
        ttk.Entry(opts, textvariable=self.port_var, width=8).pack(side="left", padx=(6, 16))
        ttk.Label(opts, text="Image:").pack(side="left")
        ttk.Entry(opts, textvariable=self.image_var, width=24).pack(side="left", padx=(6, 10))

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(2, 8))
        ttk.Button(btns, text="Generate commands", command=self._generate).pack(side="left")
        ttk.Button(btns, text="Copy just ui command", command=lambda: self._copy_from(self.just_text)).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Copy docker command", command=lambda: self._copy_from(self.docker_text)).pack(side="left", padx=(8, 0))

        ttk.Label(frame, text="Recommended: just ui command").pack(anchor="w")
        self.just_text = scrolledtext.ScrolledText(frame, height=8, wrap="word")
        self.just_text.pack(fill="x", pady=(2, 8))

        ttk.Label(frame, text="Optional: direct docker run command").pack(anchor="w")
        self.docker_text = scrolledtext.ScrolledText(frame, height=8, wrap="word")
        self.docker_text.pack(fill="x", pady=(2, 8))

        ttk.Label(
            frame,
            text=(
                "Next steps:\n"
                "1) Run the generated command in your terminal.\n"
                "2) Open http://127.0.0.1:8501\n"
                "3) In Summary: Save -> validate-out -> run-out"
            ),
        ).pack(anchor="w")

        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w", pady=(8, 0))

    def _path_row(self, parent, label_text: str, variable: tk.StringVar, dialog_title: str):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label_text, width=12).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(6, 6))
        ttk.Button(row, text="Browse...", command=lambda: self._browse(variable, dialog_title)).pack(side="left")

    def _browse(self, target_var: tk.StringVar, dialog_title: str):
        start_dir = target_var.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(title=dialog_title, initialdir=start_dir, mustexist=True)
        if selected:
            target_var.set(selected)

    def _copy_from(self, widget):
        if widget is None:
            return
        content = widget.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("Copy", "No generated command to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status_var.set("Copied command to clipboard.")

    def _validate_inputs(self):
        windows = self.shell_var.get() == "powershell"
        repo_path = _normalize_path(self.repo_var.get(), windows)
        input_path = _normalize_path(self.input_var.get(), windows)
        out_path = _normalize_path(self.out_var.get(), windows)
        image = (self.image_var.get() or "").strip() or self.image_default
        try:
            port = int((self.port_var.get() or "").strip())
        except ValueError:
            port = 0

        errors = []
        if not repo_path:
            errors.append("Repo path is required.")
        if not input_path:
            errors.append("Input path is required.")
        if not out_path:
            errors.append("Output path is required.")
        if port < 1 or port > 65535:
            errors.append("Port must be in range 1..65535.")
        for label, value in [("repo", repo_path), ("input", input_path), ("output", out_path)]:
            if '"' in value:
                errors.append(f'{label} path contains a double quote ("). Remove it and retry.')

        if errors:
            messagebox.showerror("Invalid input", "\n".join(errors))
            return None

        return repo_path, input_path, out_path, image, port

    def _generate(self):
        validated = self._validate_inputs()
        if validated is None:
            return
        repo_path, input_path, out_path, image, port = validated
        embed_paths = bool(self.embed_var.get())

        if self.shell_var.get() == "powershell":
            just_cmd = _powershell_just(repo_path, input_path, out_path, embed_paths)
            docker_cmd = _powershell_docker(repo_path, input_path, out_path, image, port, embed_paths)
        else:
            just_cmd = _bash_just(repo_path, input_path, out_path, embed_paths)
            docker_cmd = _bash_docker(repo_path, input_path, out_path, image, port, embed_paths)

        self.just_text.delete("1.0", "end")
        self.just_text.insert("1.0", just_cmd)
        self.docker_text.delete("1.0", "end")
        self.docker_text.insert("1.0", docker_cmd)
        self.status_var.set("Commands generated. Copy and paste into your terminal.")


def main():
    app = LauncherApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
