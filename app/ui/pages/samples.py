"""Sample discovery and assignment page presentation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from app.ui import samples_table as ui_samples
from app.ui import state as ui_state


def render_samples_page(
    *,
    input_root: Path,
    page_key: str,
    translate: Callable[..., str],
    get_run_config: Callable[[], dict[str, Any]],
    update_run_config: Callable[[dict[str, Any]], None],
    list_subdirectories: Callable[[Path], list[str]],
    scan_fastq: Callable[[Path, list[str]], list[Path]],
    relative_path: Callable[[Path], str],
    read_counts: Callable[[list[str]], dict[str, int]],
    build_initial_rows: Callable[[list[str], bool, bool], list[dict[str, str]]],
    coerce_rows: Callable[[Any], list[dict[str, str]]],
    auto_pair: Callable[[list[dict[str, str]], list[str]], list[dict[str, str]]],
    canonicalize_rows: Callable[..., tuple[list[dict[str, str]], list[str]]],
    sync_rows_from_editor: Callable[[str], None],
    validate_rows: Callable[..., list[str]],
    read_side: Callable[[str], str],
) -> None:
    st.subheader(translate("label.samples_step"))
    st.caption(translate("step_desc.samples"))
    subdir_options = list_subdirectories(input_root)
    run_config = get_run_config()
    selected_subdirs = [
        item for item in list(run_config.get("selected_subdirs") or []) if item in subdir_options
    ]

    sel_col1, sel_col2, sel_col3 = st.columns([2, 1, 1])
    with sel_col1:
        selected_ui = st.multiselect(
            "Include subdirectories under /input",
            options=subdir_options,
            default=selected_subdirs,
            key=f"{page_key}:selected_subdirs",
        )
    with sel_col2:
        if st.button("Select all", key=f"{page_key}:select_all_subdirs"):
            selected_ui = list(subdir_options)
    with sel_col3:
        if st.button("Clear", key=f"{page_key}:clear_subdirs"):
            selected_ui = []

    selected_ui = [item for item in selected_ui if item in subdir_options]
    st.caption(f"Selected: {len(selected_ui)}")
    if selected_ui:
        st.code("\n".join(selected_ui))

    if selected_ui != selected_subdirs:
        update_run_config({"selected_subdirs": selected_ui})
        st.session_state.rows_initialized = False
        st.session_state.rows_raw = []
        st.session_state.auto_pair_warnings = []
        selected_subdirs = selected_ui

    fastq_rel = [relative_path(path) for path in scan_fastq(input_root, selected_subdirs)]
    st.session_state.fastq_rel = fastq_rel
    counts = read_counts(fastq_rel)
    if st.session_state.paired:
        st.write(
            translate(
                "label.fastq_summary_paired",
                total=len(fastq_rel),
                r1=counts["r1"],
                r2=counts["r2"],
                unknown=counts["unknown"],
            )
        )
    else:
        st.write(translate("label.fastq_summary_single", total=len(fastq_rel)))
    if not selected_subdirs:
        st.warning("No subdirectories selected. Select one or more folders to list FASTQ files.")
        st.stop()
    if not fastq_rel:
        st.warning("No FASTQ files found under selected subdirectories.")
        st.stop()

    st.checkbox(translate("label.autofill_condition"), key="autofill_conditions")
    if not st.session_state.rows_initialized:
        st.session_state.rows_raw = build_initial_rows(
            fastq_rel,
            st.session_state.paired,
            st.session_state.autofill_conditions,
        )
        st.session_state.rows_initialized = True

    auto_pair_col, normalize_col = st.columns(2)
    if st.session_state.paired:
        if auto_pair_col.button(translate("btn.auto_pair")):
            paired_rows = auto_pair(coerce_rows(st.session_state.rows_raw), fastq_rel)
            canonical_rows, warnings = canonicalize_rows(paired_rows, fastq_rel)
            st.session_state.rows_raw = canonical_rows
            st.session_state.auto_pair_warnings = warnings
            ui_state.mark_user_edit()
    else:
        auto_pair_col.button(translate("btn.auto_pair"), disabled=True)
        st.caption(translate("info.auto_pair_disabled"))
    if normalize_col.button(translate("btn.normalize_conditions")):
        st.session_state.rows_raw = ui_samples.apply_condition_autofill(
            st.session_state.rows_raw,
            overwrite=True,
        )
        ui_state.mark_user_edit()

    st.caption(translate("hint.sample_naming"))
    columns = ["sample", "condition", "fastq1"]
    if st.session_state.paired:
        columns.append("fastq2")
    column_config = {
        "sample": st.column_config.TextColumn("sample"),
        "condition": st.column_config.TextColumn("condition"),
        "fastq1": st.column_config.TextColumn("fastq1"),
    }
    if st.session_state.paired:
        column_config["fastq2"] = st.column_config.TextColumn("fastq2")
    editor_rows = [
        {key: row.get(key, "") for key in columns}
        for row in coerce_rows(st.session_state.rows_raw)
    ]
    samples_editor_key = f"{page_key}:samples_editor"
    st.data_editor(
        pd.DataFrame(editor_rows, columns=columns),
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config=column_config,
        key=samples_editor_key,
        on_change=sync_rows_from_editor,
        args=(samples_editor_key,),
    )

    issues = validate_rows(st.session_state.rows_raw, fastq_rel, st.session_state.paired)
    if st.session_state.paired:
        r2_in_fastq1 = []
        for index, row in enumerate(st.session_state.rows_raw, start=1):
            if read_side(row.get("fastq1", "")) == "2":
                r2_in_fastq1.append(
                    translate("row_issue.row_label", row=index, sample=row.get("sample", ""))
                )
        if r2_in_fastq1:
            issues.append(
                translate("warn.fastq1_looks_like_read2", details=", ".join(r2_in_fastq1))
            )
    warnings = st.session_state.get("auto_pair_warnings", [])
    if warnings:
        st.warning(translate("warn.autopair_canonicalization", details="\n".join(warnings)))
    if issues:
        st.warning(translate("warn.fix_issues_before_saving", details="\n".join(issues)))
