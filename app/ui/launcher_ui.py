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


def _parse_bool(value, default: bool):
    if value is None:
        return default
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "on")


def _qp_value(key: str, default: str = ""):
    qp = st.query_params
    value = qp.get(key, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


def _powershell_just(repo_path: str, input_path: str, out_path: str, embed_paths: bool):
    lines = []
    if repo_path:
        lines.insert(0, f"Set-Location {_q(repo_path)}")
    if embed_paths:
        lines.append(f"$env:INPUT={_q(input_path)}; $env:OUT={_q(out_path)}; just ui")
    else:
        lines.extend(
            [
                f"$env:INPUT={_q(input_path)}",
                f"$env:OUT={_q(out_path)}",
            ]
        )
        lines.append("just ui")
    return "\n".join(lines)


def _powershell_docker(repo_path: str, input_path: str, out_path: str, image: str, port: int, embed_paths: bool):
    if embed_paths:
        return (
            f"docker run --rm -p 127.0.0.1:{port}:8501 "
            f'-v "{repo_path}:/app" -v "{input_path}:/input:ro" -v "{out_path}:/output" '
            f"{image} "
            f"bash -lc 'cd /app && {APP_CMD}'"
        )
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


def _bash_just(repo_path: str, input_path: str, out_path: str, embed_paths: bool):
    lines = []
    if repo_path:
        lines.insert(0, f"cd {_q(repo_path)}")
    if embed_paths:
        lines.append(f"INPUT={_q(input_path)} OUT={_q(out_path)} just ui")
    else:
        lines.extend(
            [
                f"export INPUT={_q(input_path)}",
                f"export OUT={_q(out_path)}",
            ]
        )
        lines.append("just ui")
    return "\n".join(lines)


def _bash_docker(repo_path: str, input_path: str, out_path: str, image: str, port: int, embed_paths: bool):
    if embed_paths:
        return (
            f"docker run --rm -p 127.0.0.1:{port}:8501 "
            f'-v "{repo_path}:/app" -v "{input_path}:/input:ro" -v "{out_path}:/output" '
            f"{image} "
            f"bash -lc 'cd /app && {APP_CMD}'"
        )
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

os_param = str(_qp_value("os", "")).strip().lower()
os_default = "Windows (PowerShell)" if os_param in ("powershell", "windows", "win") else "macOS / Linux (bash/zsh)"
repo_qp = _qp_value("repo", "")
input_qp = _qp_value("input", "")
out_qp = _qp_value("out", "")
use_just_qp = _parse_bool(_qp_value("use_just", None), True)

if "launcher_os" not in st.session_state:
    st.session_state.launcher_os = os_default
if "launcher_repo_path" not in st.session_state:
    st.session_state.launcher_repo_path = repo_qp
if "launcher_input_path" not in st.session_state:
    st.session_state.launcher_input_path = input_qp
if "launcher_out_path" not in st.session_state:
    st.session_state.launcher_out_path = out_qp
if "launcher_port" not in st.session_state:
    st.session_state.launcher_port = 8501
if "launcher_image" not in st.session_state:
    st.session_state.launcher_image = "rnaseq_pipeline"
if "launcher_use_just" not in st.session_state:
    st.session_state.launcher_use_just = use_just_qp
if "launcher_embed_paths" not in st.session_state:
    st.session_state.launcher_embed_paths = True

os_choice = st.radio(
    "OS",
    ["Windows (PowerShell)", "macOS / Linux (bash/zsh)"],
    horizontal=True,
    key="launcher_os",
)
windows = os_choice.startswith("Windows")

if not st.session_state.launcher_repo_path:
    st.session_state.launcher_repo_path = str(Path.cwd()) if not windows else ""

repo_path_raw = st.text_input("Repo path (required for direct docker run)", key="launcher_repo_path")
input_path_raw = st.text_input("Input path (required)", key="launcher_input_path")
out_path_raw = st.text_input("Output path (required)", key="launcher_out_path")
port = int(st.number_input("Port", min_value=1, max_value=65535, step=1, key="launcher_port"))
image = st.text_input("Docker image", key="launcher_image").strip() or "rnaseq_pipeline"
use_just = st.checkbox("Generate just ui command", key="launcher_use_just")
embed_paths = st.checkbox("Embed INPUT/OUT paths directly (recommended)", key="launcher_embed_paths")

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
        _powershell_just(repo_path, input_path, out_path, embed_paths)
        if use_just
        else _powershell_docker(repo_path, input_path, out_path, image, port, embed_paths)
    )
else:
    command = (
        _bash_just(repo_path, input_path, out_path, embed_paths)
        if use_just
        else _bash_docker(repo_path, input_path, out_path, image, port, embed_paths)
    )

st.subheader("Generated command")
st.code(command, language="powershell" if windows else "bash")

st.subheader("Next steps")
st.markdown(
    f"1. Run the generated command.\n"
    f"2. Open http://127.0.0.1:{port if not use_just else 8501}.\n"
        "3. In the main UI, open Summary, then select Save → Validate → Dry run → Run."
)
