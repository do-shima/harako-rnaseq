from __future__ import annotations

import json
from typing import Any

import streamlit as st


def mark_user_edit() -> None:
    st.session_state["run_config_touched"] = True
    st.session_state["validation_ok"] = False
    st.session_state["saved"] = False


def read_persisted_state(key: str) -> str:
    try:
        params = st.query_params
        raw = params.get(key, "")
        if isinstance(raw, list):
            return raw[0] if raw else ""
        return raw or ""
    except Exception:
        params = st.experimental_get_query_params()
        raw = params.get(key, [""])
        return raw[0] if raw else ""


def write_persisted_state(key: str, value: str) -> None:
    try:
        st.query_params[key] = value
    except Exception:
        st.experimental_set_query_params(**{key: value})


def merge_run_config(base: dict[str, Any], incoming: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
    for key, value in (incoming or {}).items():
        if overwrite or base.get(key) in ("", None, [], {}):
            base[key] = value
    return base


def persist_state_if_changed(storage_key: str, state: dict[str, Any]) -> None:
    payload = json.dumps(state, sort_keys=True)
    if payload != st.session_state.get("run_config_last_saved"):
        write_persisted_state(storage_key, payload)
        st.session_state["run_config_last_saved"] = payload
