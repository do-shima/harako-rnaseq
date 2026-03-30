from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import streamlit as st

PROJECT_NAME_SESSION_KEY = "project_name"
_LEGACY_PROJECT_NAME_KEYS = ("header_project_name",)
UI_SESSION_ID_SESSION_KEY = "ui_session_id"
UI_SESSION_QUERY_KEY = "ui_session_id"
_UI_SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_ui_session_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _UI_SESSION_ID_RE.fullmatch(text) else ""


def session_root(output_root: Path, ui_session_id: str) -> Path:
    return Path(output_root) / "ui_sessions" / sanitize_ui_session_id(ui_session_id)


def session_ui_state_path(output_root: Path, ui_session_id: str) -> Path:
    return session_root(output_root, ui_session_id) / "ui_state.json"


def session_effective_config_path(output_root: Path, ui_session_id: str) -> Path:
    return session_root(output_root, ui_session_id) / "ui_effective_config.json"


def session_config_path(output_root: Path, ui_session_id: str) -> Path:
    return session_root(output_root, ui_session_id) / "config.yaml"


def session_samples_path(output_root: Path, ui_session_id: str) -> Path:
    return session_root(output_root, ui_session_id) / "metadata" / "samples.tsv"


def session_logs_dir(output_root: Path, ui_session_id: str) -> Path:
    return session_root(output_root, ui_session_id) / "logs"


def _clear_legacy_validation_flags() -> None:
    st.session_state.pop("validation_failed", None)
    st.session_state.pop("validation_failed_detail", None)
    blockers = st.session_state.get("blockers")
    if isinstance(blockers, list):
        st.session_state["blockers"] = [item for item in blockers if not str(item).startswith("validation_failed")]


def mark_user_edit() -> None:
    st.session_state["run_config_touched"] = True
    st.session_state["validation_ok"] = False
    st.session_state["saved"] = False
    st.session_state["validation"] = {
        "ok": False,
        "detail": None,
        "ts": _now_iso(),
        "traceback": None,
    }
    _clear_legacy_validation_flags()


def set_validation_state(ok: bool, detail: str | None = None, traceback_text: str | None = None) -> None:
    detail_text = (detail or "").strip() or None
    fallback = "Validation failed (no detail). Check logs."
    st.session_state["validation"] = {
        "ok": bool(ok),
        "detail": detail_text if not ok else None,
        "ts": _now_iso(),
        "traceback": (traceback_text or "").strip() or None,
    }
    st.session_state["validation_ok"] = bool(ok)
    if not ok:
        reason = detail_text or fallback
        st.session_state["validation_failed"] = reason
        st.session_state["validation_failed_detail"] = reason
    else:
        _clear_legacy_validation_flags()


def set_validation_pending(detail: str | None = None) -> None:
    st.session_state["validation"] = {
        "ok": False,
        "detail": (detail or "").strip() or None,
        "ts": _now_iso(),
        "traceback": None,
    }
    st.session_state["validation_ok"] = False
    _clear_legacy_validation_flags()


def set_save_state(ok: bool, detail: str | None = None, traceback_text: str | None = None) -> None:
    detail_text = (detail or "").strip() or None
    st.session_state["save"] = {
        "ok": bool(ok),
        "detail": detail_text if not ok else None,
        "ts": _now_iso(),
        "traceback": (traceback_text or "").strip() or None,
    }


def initialize_project_name(
    session_state: MutableMapping[str, Any],
    run_config: Mapping[str, Any] | None,
    default_name: str,
    *,
    touched: bool = False,
) -> str:
    run_config_name = str((run_config or {}).get("project_name") or "").strip() or default_name
    legacy_name = ""
    for legacy_key in _LEGACY_PROJECT_NAME_KEYS:
        text = str(session_state.get(legacy_key) or "").strip()
        if text:
            legacy_name = text
            break

    if PROJECT_NAME_SESSION_KEY not in session_state:
        session_state[PROJECT_NAME_SESSION_KEY] = legacy_name or run_config_name

    for legacy_key in _LEGACY_PROJECT_NAME_KEYS:
        session_state.pop(legacy_key, None)

    return str(session_state.get(PROJECT_NAME_SESSION_KEY) or run_config_name)


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
