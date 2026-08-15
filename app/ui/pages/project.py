"""Project and execution-environment page presentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import streamlit as st

from app.core.protocol import LEGACY_UNSPECIFIED, NEW_LIBRARY_PROTOCOLS
from app.ui.config_builder import normalize_engine


def render_project_page(
    *,
    input_root: Path,
    translate: Callable[..., str],
    get_run_config: Callable[[], dict[str, Any]],
    update_run_config: Callable[[dict[str, Any]], None],
    io_access_state: Callable[[], dict[str, Any]],
    mount_status: Callable[[], None],
    host_mount_info: Callable[[], None],
    translate_lines: Callable[[str], list[str]],
    scan_fastq: Callable[[Path, list[str]], list[Path]],
    scan_references: Callable[[Path], tuple[list[Path], list[Path]]],
    relative_path: Callable[[Path], str],
) -> None:
    st.subheader(translate("label.project_step"))
    st.caption(translate("step_desc.project"))
    mount_status()
    io_state = io_access_state()
    if not io_state["ok"]:
        st.warning("\n".join(translate_lines("msg.io_inaccessible")))
        host_mount_info()
        st.caption(translate("label.io_status"))
        st.code(
            "\n".join(
                [
                    f"input_ok={io_state['input_ok']}",
                    f"output_ok={io_state['output_ok']}",
                    f"output_writable={io_state['output_writable']}",
                    f"fastq_count={io_state['fastq_count']}",
                ]
            )
        )
    run_config = get_run_config()
    engine_options = ["stub", "real"]
    engine_value = normalize_engine(run_config.get("engine"))
    engine_index = engine_options.index(engine_value) if engine_value in engine_options else 0
    engine_choice = st.selectbox(
        "Engine",
        options=engine_options,
        index=engine_index,
        help="real: DESeq2, stub: minimal pipeline for smoke tests",
    )
    engine_choice = normalize_engine(engine_choice)
    if engine_choice != engine_value:
        update_run_config({"engine": engine_choice})
    paired_options = [translate("label.single_end"), translate("label.paired_end")]
    paired_value = bool(run_config.get("paired", False))
    paired_choice = st.radio(
        translate("label.read_layout"),
        paired_options,
        index=1 if paired_value else 0,
        horizontal=True,
    )
    paired_selected = paired_choice == translate("label.paired_end")
    if paired_selected != paired_value:
        update_run_config({"paired": paired_selected})
        st.session_state.paired = paired_selected
    protocol_value = str(run_config.get("library_protocol") or "")
    protocol_options = ["", *NEW_LIBRARY_PROTOCOLS]
    if protocol_value == LEGACY_UNSPECIFIED:
        protocol_options.append(LEGACY_UNSPECIFIED)
    protocol_choice = st.selectbox(
        translate("label.library_protocol"),
        options=protocol_options,
        index=protocol_options.index(protocol_value) if protocol_value in protocol_options else 0,
        format_func=lambda value: translate(f"label.library_protocol.{value or 'unselected'}"),
        help=translate("help.library_protocol"),
        disabled=protocol_value == LEGACY_UNSPECIFIED,
    )
    if protocol_choice != protocol_value:
        update_run_config({"library_protocol": protocol_choice})
    threads_value = int(run_config.get("threads") or 1)
    threads_choice = st.number_input(
        translate("label.threads"),
        min_value=1,
        max_value=64,
        value=threads_value,
        step=1,
    )
    if int(threads_choice) != threads_value:
        update_run_config({"threads": int(threads_choice)})
    st.caption(translate("info.threads_cap"))
    if st.button(translate("btn.refresh_scan")):
        selected = list(get_run_config().get("selected_subdirs") or [])
        st.session_state.fastq_rel = [relative_path(path) for path in scan_fastq(input_root, selected)]
        fasta, gtf = scan_references(input_root)
        st.session_state.refs_rel = {
            "fasta": [relative_path(path) for path in fasta],
            "gtf": [relative_path(path) for path in gtf],
        }
