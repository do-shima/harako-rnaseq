import re
from pathlib import Path

import streamlit as st


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


def _powershell_just(repo_path: str, input_path: str, out_path: str):
    lines = [
        f"$env:INPUT={_q(input_path)}",
        f"$env:OUT={_q(out_path)}",
    ]
    if repo_path:
        lines.insert(0, f"Set-Location {_q(repo_path)}")
    lines.append("just ui")
    return "\n".join(lines)


def _powershell_docker(repo_path: str, input_path: str, out_path: str, image: str, port: int):
    return "\n".join(
        [
            f"$env:REPO={_q(repo_path)}",
            f"$env:INPUT={_q(input_path)}",
            f"$env:OUT={_q(out_path)}",
            (
                f"docker run --rm -p 127.0.0.1:{port}:8501 "
                f'-v "${{env:REPO}}:/app" -v "${{env:INPUT}}:/input:ro" -v "${{env:OUT}}:/output" '
                f"{image} "
                f"bash -lc 'cd /app && {APP_CMD}'"
            ),
        ]
    )


def _bash_just(repo_path: str, input_path: str, out_path: str):
    lines = [
        f"export INPUT={_q(input_path)}",
        f"export OUT={_q(out_path)}",
    ]
    if repo_path:
        lines.insert(0, f"cd {_q(repo_path)}")
    lines.append("just ui")
    return "\n".join(lines)


def _bash_docker(repo_path: str, input_path: str, out_path: str, image: str, port: int):
    return "\n".join(
        [
            f"REPO={_q(repo_path)}",
            f"INPUT={_q(input_path)}",
            f"OUT={_q(out_path)}",
            (
                f"docker run --rm -p 127.0.0.1:{port}:8501 "
                f'-v "$REPO:/app" -v "$INPUT:/input:ro" -v "$OUT:/output" '
                f"{image} "
                f"bash -lc 'cd /app && {APP_CMD}'"
            ),
        ]
    )


st.set_page_config(page_title="RNA-seq Launcher", layout="wide")
st.title("RNA-seq Launcher")
st.write("This page generates a safe command to start the UI with /input and /output mounted.")
st.write("Mounts cannot be changed after the UI starts. Generate the command first.")

os_choice = st.radio("OS", ["Windows (PowerShell)", "macOS / Linux (bash/zsh)"], horizontal=True)
windows = os_choice.startswith("Windows")

repo_default = str(Path.cwd()) if not windows else ""
repo_path_raw = st.text_input("Repo path (required for direct docker run)", value=repo_default)
input_path_raw = st.text_input("Input path (required)")
out_path_raw = st.text_input("Output path (required)")
port = int(st.number_input("Port", min_value=1, max_value=65535, value=8501, step=1))
image = st.text_input("Docker image", value="rnaseq_pipeline").strip() or "rnaseq_pipeline"
use_just = st.checkbox("Generate just ui command", value=True)

repo_path = _normalize_path(repo_path_raw, windows)
input_path = _normalize_path(input_path_raw, windows)
out_path = _normalize_path(out_path_raw, windows)

errors = []
if not input_path:
    errors.append("Input path is required.")
if not out_path:
    errors.append("Output path is required.")
if not use_just and not repo_path:
    errors.append("Repo path is required when generating direct docker run command.")
if windows:
    for label, value in [("repo_path", repo_path), ("input_path", input_path), ("out_path", out_path)]:
        if '"' in value:
            errors.append(f'{label} contains a double quote ("). Remove it and retry.')

if errors:
    st.error("\n".join(errors))
    st.stop()

if use_just and port != 8501:
    st.warning("`just ui` uses port 8501. Use direct docker run if you need a custom port.")

if windows:
    command = (
        _powershell_just(repo_path, input_path, out_path)
        if use_just
        else _powershell_docker(repo_path, input_path, out_path, image, port)
    )
else:
    command = (
        _bash_just(repo_path, input_path, out_path)
        if use_just
        else _bash_docker(repo_path, input_path, out_path, image, port)
    )

st.subheader("Generated command")
st.code(command, language="powershell" if windows else "bash")

st.subheader("Next steps")
st.markdown(
    f"1. Run the generated command.\n"
    f"2. Open http://127.0.0.1:{port if not use_just else 8501}.\n"
    "3. In the main UI, go to Summary then run Save -> validate-out -> run-out."
)
