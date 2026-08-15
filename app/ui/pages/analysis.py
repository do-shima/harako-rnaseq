"""Analysis-plan and enrichment settings page presentation."""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from app.core.analysis import evaluate_analysis_eligibility
from app.ui import samples_table as ui_samples


def render_analysis_page(
    *,
    page_key: str,
    translate: Callable[..., str],
    rows: list[dict[str, str]],
    conditions: list[str],
    engine: str,
    advanced_state: Callable[[], dict[str, Any]],
    advanced_value: Callable[[str], Any],
    set_advanced_values: Callable[..., None],
    seed_widget_state: Callable[[str, Any], None],
    enrichment_status: Callable[[list[dict[str, str]], str], tuple[bool, str, Any]],
) -> None:
    st.subheader(translate("label.advanced"))
    st.caption(translate("step_desc.advanced"))
    eligibility = evaluate_analysis_eligibility(rows)
    contrast_allowed = eligibility.contrast_allowed
    st.markdown(f"**{translate('analysis.mode.heading')}**")
    st.write(translate(f"analysis.mode.{eligibility.mode}"))
    if eligibility.mode == "qc_only":
        st.caption(translate(f"analysis.reason.{eligibility.reason_code}"))
        st.caption(
            translate(
                "analysis.condition_counts",
                counts=ui_samples.format_condition_counts(eligibility.condition_counts),
            )
        )
        st.caption(translate("analysis.settings_retained"))
    st.markdown(f"**{translate('label.contrast_block')}**")
    st.caption(translate("info.contrast_intro"))
    st.write(
        translate(
            "label.condition_levels",
            levels=", ".join(conditions) if conditions else translate("label.none"),
        )
    )
    advanced = advanced_state()
    mode_options = ["ref", "pairwise", "select", "legacy"]
    mode_key = f"{page_key}:contrast_mode"
    seed_widget_state(mode_key, advanced.get("contrast_mode", "ref"))
    contrast_mode = st.selectbox(
        translate("label.contrast_mode"),
        mode_options,
        index=mode_options.index(st.session_state[mode_key])
        if st.session_state.get(mode_key) in mode_options
        else 0,
        key=mode_key,
        format_func=lambda value: translate(f"label.contrast_mode.{value}"),
        disabled=not contrast_allowed,
    )
    set_advanced_values(contrast_mode=contrast_mode)
    st.caption(translate(f"desc.contrast_mode.{contrast_mode}"))
    contrast_pairs = list(advanced_value("contrast_pairs") or [])

    if contrast_mode == "ref":
        reference_key = f"{page_key}:contrast_ref"
        reference_value = advanced.get("contrast_ref") or (conditions[0] if conditions else "")
        seed_widget_state(reference_key, reference_value)
        st.selectbox(
            translate("label.reference_condition"),
            conditions,
            index=conditions.index(st.session_state[reference_key])
            if conditions and st.session_state.get(reference_key) in conditions
            else 0,
            key=reference_key,
            disabled=not conditions or not contrast_allowed,
            help=translate("analysis.contrast_disabled") if not contrast_allowed else None,
        )
        set_advanced_values(contrast_ref=st.session_state.get(reference_key, ""))
    elif contrast_mode == "select":
        left_column, right_column, add_column = st.columns([2, 2, 1])
        left_key = f"{page_key}:pair_left"
        right_key = f"{page_key}:pair_right"
        seed_widget_state(left_key, conditions[0] if conditions else "")
        seed_widget_state(
            right_key,
            conditions[1] if len(conditions) > 1 else (conditions[0] if conditions else ""),
        )
        with left_column:
            left = st.selectbox("A", conditions, key=left_key, disabled=not conditions)
        with right_column:
            right = st.selectbox("B", conditions, key=right_key, disabled=not conditions)
        with add_column:
            if st.button(translate("btn.add_pair"), disabled=not contrast_allowed):
                pair = [left, right]
                if left and right and left != right and pair not in contrast_pairs:
                    contrast_pairs.append(pair)
                    set_advanced_values(contrast_pairs=contrast_pairs)
        if contrast_pairs:
            st.write(translate("label.selected_pairs"))
            for index, pair in enumerate(contrast_pairs):
                columns = st.columns([4, 1])
                columns[0].write(f"{pair[0]} vs {pair[1]}")
                if columns[1].button(translate("btn.remove_pair"), key=f"pair_{index}"):
                    set_advanced_values(
                        contrast_pairs=[
                            item for pair_index, item in enumerate(contrast_pairs) if pair_index != index
                        ]
                    )
    elif contrast_mode == "legacy":
        legacy_key = f"{page_key}:contrast_legacy"
        seed_widget_state(legacy_key, advanced.get("contrast_legacy", ""))
        st.text_input(
            translate("label.legacy_contrast"),
            key=legacy_key,
            disabled=not contrast_allowed,
        )
        set_advanced_values(contrast_legacy=st.session_state.get(legacy_key, ""))

    st.markdown(f"**{translate('label.advanced_block')}**")
    st.caption(translate("info.advanced_block"))
    enrichment_allowed, enrichment_reason, _ = enrichment_status(rows, engine)
    enable_key = f"{page_key}:enrich_enable"
    seed_widget_state(enable_key, bool(advanced_value("enrich_enable")))
    enable_enrichment = st.checkbox(
        translate("label.enable_enrichment"),
        key=enable_key,
        disabled=not enrichment_allowed,
        help=enrichment_reason or None,
    )
    if enrichment_allowed:
        set_advanced_values(enrich_enable=enable_enrichment)
    if enrichment_reason:
        st.caption(enrichment_reason)
    if not enable_enrichment:
        return

    methods_key = f"{page_key}:enrich_methods"
    alpha_key = f"{page_key}:enrich_alpha"
    lfc_key = f"{page_key}:enrich_lfc"
    top_key = f"{page_key}:enrich_top"
    rank_key = f"{page_key}:enrich_rank"
    seed_widget_state(methods_key, advanced.get("enrich_methods", ["ORA", "GSEA"]))
    seed_widget_state(alpha_key, float(advanced.get("enrich_alpha", 0.05)))
    seed_widget_state(lfc_key, float(advanced.get("enrich_lfc", 0.0)))
    seed_widget_state(top_key, int(advanced.get("enrich_top", 15)))
    seed_widget_state(rank_key, advanced.get("enrich_rank", "stat"))
    methods = st.multiselect(
        translate("label.enrich_methods"),
        ["ORA", "GSEA"],
        default=st.session_state[methods_key],
        key=methods_key,
    )
    alpha = st.number_input(
        translate("label.enrich_alpha"),
        min_value=0.0,
        max_value=1.0,
        value=float(st.session_state[alpha_key]),
        step=0.01,
        key=alpha_key,
    )
    lfc = st.number_input(
        translate("label.enrich_lfc"),
        value=float(st.session_state[lfc_key]),
        step=0.5,
        key=lfc_key,
    )
    top_terms = st.number_input(
        translate("label.enrich_top"),
        min_value=1,
        max_value=100,
        value=int(st.session_state[top_key]),
        step=1,
        key=top_key,
    )
    rank_metric = st.selectbox(
        translate("label.enrich_rank"),
        ["stat"],
        index=0,
        key=rank_key,
    )
    set_advanced_values(
        enrich_methods=methods,
        enrich_alpha=alpha,
        enrich_lfc=lfc,
        enrich_top=top_terms,
        enrich_rank=rank_metric,
    )
