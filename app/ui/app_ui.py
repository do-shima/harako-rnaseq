from __future__ import annotations

import os
import re
import subprocess
import time
import json
import shutil
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pandas as pd
import streamlit as st
import yaml

from app.ui.i18n import t
from app.ui.error_messages import extract_incomplete_files, summarize_error
from app.ui.config_builder import build_config_payload, normalize_engine, normalize_species
from app.analysis_eligibility import analysis_plan_from_rows, evaluate_analysis_eligibility
from app.library_protocol import (
    LEGACY_UNSPECIFIED,
    NEW_LIBRARY_PROTOCOLS,
)
from app.ui import logging as ui_logging
from app.ui import refs as ui_refs
from app.ui import run as ui_run
from app.ui import samples_table as ui_samples
from app.ui import scan as ui_scan
from app.ui import state as ui_state

INPUT_ROOT = Path("/input")
OUTPUT_ROOT = Path("/output")
REPO_ROOT = Path(__file__).resolve().parents[2]
REF_MANIFEST_PATH = REPO_ROOT / "workflow" / "ref_manifest.yaml"
LOGO_PNG_PATH = REPO_ROOT / "icon" / "Harako-logo.png"
FASTQ_EXTS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")
RUN_LOG_MAX_CHARS = 200000
RUNS_ROOT = OUTPUT_ROOT / "data_out"
JST = timezone(timedelta(hours=9), name="JST")
ALLOWED_SPECIES = ("mouse", "rat", "human")
RUN_CONFIG_KEY = "run_config"
RUN_CONFIG_STORAGE_KEY = "rnaseq_pipeline.run_config.v1"
LOGO_DISPLAY_WIDTH = 88
_UNLIMITED_MEMORY_THRESHOLD = 1 << 60


def _default_project_name():
    return f"Project{datetime.now(JST).strftime('%y%m%d')}"


def _normalize_project_slug(name: str):
    text = (name or "").strip().replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or _default_project_name()


def _normalize_mem_bytes(mem_raw):
    if mem_raw is None:
        return None
    try:
        value = int(mem_raw)
    except Exception:
        return None
    if value <= 0:
        return None
    # Docker Desktop may expose memory as MiB (small number) or bytes.
    if value <= 10_000_000:
        return value * (1024 ** 2)
    return value


def _memory_limit_display_info(mem_raw):
    normalized = _normalize_mem_bytes(mem_raw)
    if normalized is None:
        return {"bytes": None, "display": "-", "kind": "unknown", "approximate": False}
    if normalized >= _UNLIMITED_MEMORY_THRESHOLD:
        return {"bytes": None, "display": "unlimited", "kind": "unlimited", "approximate": False}
    approximate = int(mem_raw) <= 10_000_000
    label = _format_bytes(normalized)
    if approximate:
        label = f"detected {label} (approx.)"
    else:
        label = f"detected {label}"
    return {"bytes": normalized, "display": label, "kind": "limit", "approximate": approximate}


def _format_bytes(value: int):
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def _read_first_line(path: Path):
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _detect_cpu_limit():
    cpu_count = os.cpu_count() or 1
    cpu_max = Path("/sys/fs/cgroup/cpu.max")
    if cpu_max.exists():
        raw = _read_first_line(cpu_max)
        parts = raw.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota = int(parts[0])
                period = int(parts[1])
                if quota > 0 and period > 0:
                    return max(1, int(quota / period))
            except ValueError:
                pass
    quota_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if quota_path.exists() and period_path.exists():
        try:
            quota = int(_read_first_line(quota_path))
            period = int(_read_first_line(period_path))
            if quota > 0 and period > 0:
                return max(1, int(quota / period))
        except ValueError:
            pass
    return cpu_count


def _detect_memory_limit():
    mem_max = Path("/sys/fs/cgroup/memory.max")
    if mem_max.exists():
        raw = _read_first_line(mem_max)
        if raw == "max":
            return {"bytes": None, "display": "unlimited", "kind": "unlimited", "approximate": False}
        if raw and raw != "max":
            try:
                info = _memory_limit_display_info(int(raw))
                if info["kind"] in ("limit", "unlimited"):
                    return info
            except ValueError:
                pass
    mem_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if mem_limit.exists():
        try:
            info = _memory_limit_display_info(int(_read_first_line(mem_limit)))
            if info["kind"] in ("limit", "unlimited"):
                return info
        except ValueError:
            pass
    return _memory_limit_display_info(None)


def _t_lines(key: str):
    text = t(key)
    return [line for line in text.splitlines() if line.strip()]


def _run_config_defaults():
    return {
        "input_dir": str(INPUT_ROOT),
        "output_dir": str(OUTPUT_ROOT),
        "sample_table": str(_ui_session_samples_path()),
        "project_name": _default_project_name(),
        "species": "mouse",
        "library_protocol": "",
        "threads": 1,
        "engine": "stub",
        "paired": False,
        "use_custom_refs": False,
        "ref_mode": "preset_cache",
        "ref_transcripts": "",
        "ref_genome": "",
        "ref_gtf": "",
        "ref_preset": "mouse_ensembl_grcm39",
        "ref_release": "pinned",
        "ref_manifest": str(REF_MANIFEST_PATH),
        "ref_cache_dir": str(OUTPUT_ROOT / "refs_cache"),
        "selected_subdirs": [],
    }


def _run_config_snapshot(state=None):
    state = state or st.session_state.get(RUN_CONFIG_KEY, {})
    return {
        "project_name": state.get("project_name", ""),
        "species": normalize_species(state.get("species")),
        "library_protocol": str(state.get("library_protocol") or ""),
        "threads": int(state.get("threads") or 1),
        "engine": normalize_engine(state.get("engine")),
        "paired": bool(state.get("paired", False)),
        "use_custom_refs": bool(state.get("use_custom_refs", False)),
        "ref_mode": state.get("ref_mode", ""),
        "ref_transcripts": state.get("ref_transcripts", ""),
        "ref_genome": state.get("ref_genome", ""),
        "ref_gtf": state.get("ref_gtf", ""),
        "ref_preset": state.get("ref_preset", ""),
        "ref_release": state.get("ref_release", ""),
        "selected_subdirs": list(state.get("selected_subdirs") or []),
    }


def _default_preset_for_species(species: str):
    mapping = {
        "mouse": "mouse_ensembl_grcm39",
        "human": "human_ensembl_grch38",
        "rat": "rat_ensembl_mratbn7_2",
    }
    return mapping.get(normalize_species(species) or "", "mouse_ensembl_grcm39")


def _preset_matches_species(preset: str, species: str):
    preset_value = (preset or "").strip().lower()
    species_value = (species or "").strip().lower()
    return bool(preset_value and species_value and preset_value.startswith(species_value))


def _run_config_status():
    validation_state = st.session_state.get("validation", {}) if isinstance(st.session_state.get("validation", {}), dict) else {}
    validation_ok = bool(validation_state.get("ok", st.session_state.get("validation_ok")))
    if validation_ok and not st.session_state.get("run_config_touched"):
        return "ready"
    if st.session_state.get("saved") and not st.session_state.get("run_config_touched"):
        return "saved"
    return "draft"


def _ref_state_snapshot():
    run_cfg = _get_run_config()
    return {
        "use_custom_refs": bool(run_cfg.get("use_custom_refs", False)),
        "ref_mode": run_cfg.get("ref_mode", ""),
        "ref_transcripts": run_cfg.get("ref_transcripts", ""),
        "ref_genome": run_cfg.get("ref_genome", ""),
        "ref_gtf": run_cfg.get("ref_gtf", ""),
        "ref_preset": run_cfg.get("ref_preset", ""),
        "ref_release": run_cfg.get("ref_release", ""),
    }


def _log_ui_event(event: str, data: dict):
    ui_logging.log_ui_event(_ui_session_root(), event, data)


def _log_debug(event: str, before: dict, after: dict):
    ui_logging.log_debug(_ui_session_root(), event, before, after)


def _read_persisted_state(key: str) -> str:
    return ui_state.read_persisted_state(key)


def _write_persisted_state(key: str, value: str):
    ui_state.write_persisted_state(key, value)


def _ensure_ui_session_id():
    persisted = ui_state.sanitize_ui_session_id(_read_persisted_state(ui_state.UI_SESSION_QUERY_KEY))
    st.session_state.setdefault(ui_state.UI_SESSION_ID_SESSION_KEY, persisted or uuid4().hex)
    session_id = ui_state.sanitize_ui_session_id(st.session_state.get(ui_state.UI_SESSION_ID_SESSION_KEY)) or persisted or uuid4().hex
    st.session_state[ui_state.UI_SESSION_ID_SESSION_KEY] = session_id
    if persisted != session_id:
        _write_persisted_state(ui_state.UI_SESSION_QUERY_KEY, session_id)
    return session_id


def _ui_session_root():
    return ui_state.session_root(OUTPUT_ROOT, _ensure_ui_session_id())


def _ui_session_ui_state_path():
    return ui_state.session_ui_state_path(OUTPUT_ROOT, _ensure_ui_session_id())


def _ui_session_effective_config_path():
    return ui_state.session_effective_config_path(OUTPUT_ROOT, _ensure_ui_session_id())


def _ui_session_config_path():
    return ui_state.session_config_path(OUTPUT_ROOT, _ensure_ui_session_id())


def _ui_session_samples_path():
    return ui_state.session_samples_path(OUTPUT_ROOT, _ensure_ui_session_id())


def _legacy_ui_state_path():
    return OUTPUT_ROOT / "run" / "ui_state.json"


def _legacy_config_path():
    return OUTPUT_ROOT / "config.yaml"


def _get_run_config():
    if RUN_CONFIG_KEY not in st.session_state:
        st.session_state[RUN_CONFIG_KEY] = _run_config_defaults()
    return st.session_state[RUN_CONFIG_KEY]


def updateRunConfig(patch: dict):
    state = _get_run_config()
    before = dict(state)
    species_before = normalize_species(before.get("species")) or "mouse"
    state.update(patch or {})
    if "ref_preset" in (patch or {}) and "_requested_ref_preset" not in (patch or {}):
        state["_requested_ref_preset"] = patch.get("ref_preset")
        state["_requested_ref_release"] = patch.get("ref_release", state.get("ref_release"))
        state["_ref_migration_notice"] = None
    if "ref_release" in (patch or {}) and "_requested_ref_release" not in (patch or {}):
        state["_requested_ref_release"] = patch.get("ref_release")
        state["_requested_ref_preset"] = state.get("ref_preset")
        state["_ref_migration_notice"] = None
    state["project_name"] = (str(state.get("project_name", "")).strip() or _default_project_name())
    state["species"] = normalize_species(state.get("species")) or "mouse"
    state["engine"] = normalize_engine(state.get("engine")) or "stub"
    state["library_protocol"] = str(state.get("library_protocol") or "").strip().lower()
    state["paired"] = bool(state.get("paired", False))
    try:
        state["threads"] = max(1, int(str(state.get("threads")).strip()))
    except Exception:
        state["threads"] = 1
    state["use_custom_refs"] = bool(state.get("use_custom_refs", False))
    state["selected_subdirs"] = [
        _normalize_input_value(str(item))
        for item in list(state.get("selected_subdirs") or [])
        if _normalize_input_value(str(item))
    ]
    state["ref_release"] = str(state.get("ref_release") or "pinned")
    if state["species"] != species_before:
        state["ref_release"] = "pinned"
        if state["use_custom_refs"]:
            state["ref_preset"] = ""
        else:
            state["ref_preset"] = _default_preset_for_species(state["species"])
            state["ref_mode"] = "preset_cache"
            state["ref_transcripts"] = ""
            state["ref_genome"] = ""
            state["ref_gtf"] = ""
    if not state["use_custom_refs"]:
        state["ref_mode"] = "preset_cache"
        if not _preset_matches_species(state.get("ref_preset", ""), state["species"]):
            state["ref_preset"] = _default_preset_for_species(state["species"])
        state["ref_transcripts"] = ""
        state["ref_genome"] = ""
        state["ref_gtf"] = ""
    else:
        if state.get("ref_mode") not in ("fasta_gtf", "transcripts_only"):
            state["ref_mode"] = "fasta_gtf"
        state["ref_preset"] = ""
    after = dict(state)
    if before != after:
        ui_state.mark_user_edit()
        _log_debug("update_run_config", before, after)


def _on_project_name_change():
    updateRunConfig(
        {
            "project_name": str(st.session_state.get(ui_state.PROJECT_NAME_SESSION_KEY) or "").strip(),
        }
    )


def _saved_config_patch(saved_cfg: dict, sample_rows=None, manifest_config=None, *, legacy_frozen=False):
    if not isinstance(saved_cfg, dict) or not saved_cfg:
        return {}
    saved_species = normalize_species(saved_cfg.get("species")) or "mouse"
    saved_ref = saved_cfg.get("ref") if isinstance(saved_cfg.get("ref"), dict) else {}
    if saved_ref and isinstance(saved_ref.get(saved_species), dict):
        saved_ref = saved_ref.get(saved_species) or {}
    ref_transcripts = saved_ref.get("transcripts_fasta", "") if isinstance(saved_ref, dict) else ""
    ref_genome = saved_ref.get("genome_fasta", "") if isinstance(saved_ref, dict) else ""
    ref_gtf = saved_ref.get("gtf", "") if isinstance(saved_ref, dict) else ""
    ref_mode = ""
    use_custom_refs = False
    if saved_cfg.get("ref_preset"):
        ref_mode = "preset_cache"
    elif ref_transcripts:
        use_custom_refs = True
        ref_mode = "fasta_gtf" if (ref_genome and ref_gtf) else "transcripts_only"
    manifest_cfg = manifest_config if isinstance(manifest_config, dict) else {}
    library_protocol = str(saved_cfg.get("library_protocol") or "").strip().lower()
    if not library_protocol and legacy_frozen:
        library_protocol = LEGACY_UNSPECIFIED
    paired = bool(manifest_cfg.get("paired", False))
    if not paired and isinstance(sample_rows, list):
        paired = any(str((row or {}).get("fastq2") or "").strip() for row in sample_rows if isinstance(row, dict))
    requested_preset = saved_cfg.get("ref_preset")
    resolved_preset = requested_preset
    resolved_release = saved_cfg.get("ref_release")
    migration_notice = None
    if requested_preset:
        try:
            manifest = _load_ref_manifest()
            resolved_preset, resolved_release = ui_refs.resolve_preset_release(
                manifest, requested_preset, resolved_release
            )
            if (
                resolved_preset != requested_preset
                or resolved_release != str(saved_cfg.get("ref_release") or "pinned")
            ):
                migration_notice = {
                    "requested_preset": requested_preset,
                    "requested_release": str(saved_cfg.get("ref_release") or "pinned"),
                    "canonical_preset": resolved_preset,
                    "manifest_release": resolved_release,
                }
        except ui_refs.ReferencePresetError:
            pass
    return {
        "project_name": saved_cfg.get("project_name"),
        "species": saved_species,
        "engine": saved_cfg.get("engine"),
        "library_protocol": library_protocol,
        "threads": saved_cfg.get("threads"),
        "paired": paired,
        "use_custom_refs": use_custom_refs,
        "ref_mode": ref_mode,
        "ref_transcripts": ref_transcripts,
        "ref_genome": ref_genome,
        "ref_gtf": ref_gtf,
        "ref_preset": resolved_preset,
        "ref_release": resolved_release,
        "_requested_ref_preset": requested_preset,
        "_requested_ref_release": str(saved_cfg.get("ref_release") or "pinned"),
        "_ref_migration_notice": migration_notice,
        "ref_cache_dir": saved_cfg.get("ref_cache_dir"),
        "sample_table": saved_cfg.get("sample_table"),
        "selected_subdirs": list(manifest_cfg.get("selected_subdirs") or []),
    }


def _load_ui_state_json():
    path = _ui_session_ui_state_path()
    if not path.exists():
        path = _legacy_ui_state_path()
    if not path.exists():
        st.session_state["_persisted_ui_state_raw"] = {}
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            st.session_state["_persisted_ui_state_raw"] = {"_non_dict": str(type(raw))}
            return {}
        st.session_state["_persisted_ui_state_raw"] = dict(raw)
        for legacy_key in ("blockers", "validation_failed", "validation_failed_detail", "validation", "validation_ok", "save"):
            raw.pop(legacy_key, None)
        return raw
    except Exception:
        st.session_state["_persisted_ui_state_raw"] = {"_error": "failed_to_load"}
        return {}


def _write_ui_state_json(state: dict):
    path = _ui_session_ui_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _write_ui_effective_config(state: dict):
    path = _ui_session_effective_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _load_config_yaml():
    path = _ui_session_config_path()
    if not path.exists():
        path = _legacy_config_path()
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _merge_run_config(base: dict, incoming: dict, overwrite: bool = False):
    return ui_state.merge_run_config(base, incoming, overwrite=overwrite)


def _restore_run_config():
    if st.session_state.get("run_config_loaded"):
        return
    state = _run_config_defaults()
    stored = _read_persisted_state(RUN_CONFIG_STORAGE_KEY)
    source = "default"
    saved_cfg = _load_config_yaml()
    saved_ui_state = _load_ui_state_json()

    if saved_cfg:
        _merge_run_config(state, _saved_config_patch(saved_cfg), overwrite=True)
        source = str(_ui_session_config_path()) if _ui_session_config_path().exists() else str(_legacy_config_path())

    if saved_ui_state:
        _merge_run_config(state, saved_ui_state, overwrite=True)
        source = "ui_state.json"

    if stored:
        try:
            data = json.loads(stored)
            if isinstance(data, dict):
                for legacy_key in ("blockers", "validation_failed", "validation_failed_detail", "validation", "validation_ok", "save"):
                    data.pop(legacy_key, None)
                _merge_run_config(state, data, overwrite=True)
                source = "query_params"
        except Exception:
            source = source

    st.session_state[RUN_CONFIG_KEY] = state
    updateRunConfig({})
    st.session_state.paired = bool(state.get("paired", False))
    st.session_state.run_config_loaded = True
    st.session_state.run_config_touched = False
    st.session_state.run_config_source = source
    _log_ui_event("state_restore", {"source": source, "state": _run_config_snapshot()})


def _persist_run_config():
    state = _get_run_config()
    ui_state.persist_state_if_changed(RUN_CONFIG_STORAGE_KEY, state)


def _scan_fastq(root: Path):
    return ui_scan.scan_fastq(root)


def _scan_fastq_selected(root: Path, include_subdirs):
    return ui_scan.scan_fastqs(root, include_subdirs=include_subdirs)


def _list_subdirs(root: Path):
    return ui_scan.list_subdirs(root)


def _scan_input(root: Path):
    return ui_scan.scan_input(root, INPUT_ROOT)


def _fastq_read_counts(fastq_rel):
    return ui_scan.fastq_read_counts(fastq_rel)


def _scan_refs(root: Path):
    return ui_scan.scan_refs(root)


def _rel(path: Path):
    return ui_scan.rel(path, INPUT_ROOT)


def _normalize_input_value(value: str):
    return ui_scan.normalize_input_value(value)


def _normalize_ref(value: str):
    val = _normalize_input_value(value)
    if not val:
        return ""
    if val.startswith("/input/") or val == "/input":
        return val
    if val.startswith("/"):
        return val
    return val


def _prune_empty(value):
    def is_empty(item):
        return item is None or item == "" or item == [] or item == {}

    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item_clean = _prune_empty(item)
            if is_empty(item_clean):
                continue
            cleaned[key] = item_clean
        return cleaned
    if isinstance(value, list):
        return [item for item in (_prune_empty(item) for item in value) if not is_empty(item)]
    return value


def _ref_exists(value: str):
    val = _normalize_input_value(value)
    if not val:
        return False
    if val.startswith("/input/") or val == "/input":
        return Path(val).exists()
    if val.startswith("/"):
        return Path(val).exists()
    return (INPUT_ROOT / val).exists()


def _pick_ref_candidate(candidates, keywords):
    if not candidates:
        return ""
    lowered = [(item, item.lower()) for item in candidates]
    for keyword in keywords:
        for item, item_lower in lowered:
            if keyword in item_lower:
                return item
    return candidates[0]


def _ensure_ref_default(key, candidates, keywords=None):
    if not candidates:
        return
    current = st.session_state.get(key, "")
    if current and (current in candidates or _ref_exists(current)):
        return
    picked = _pick_ref_candidate(candidates, keywords or [])
    if picked:
        st.session_state[key] = picked


def _infer_pair(name: str):
    candidates = _infer_pair_candidates(name)
    return candidates[0] if candidates else ""


def _split_fastq_name(path_value: str):
    return ui_scan.split_fastq_name(path_value)


def _split_read_suffix(stem: str):
    return ui_scan.split_read_suffix(stem)


def _read_side(path_value: str):
    return ui_scan.read_side(path_value)


def _is_r1(path_value: str):
    return ui_scan.is_r1(path_value)


def _sample_base(path_value: str):
    return ui_scan.sample_base(path_value)


def _infer_pair_candidates(name: str):
    return ui_scan.infer_pair_candidates(name)


def _new_row(fastq1: str, condition_from_sample: bool, fastq2: str = ""):
    sample = _sample_base(fastq1)
    condition = ui_samples.normalize_condition_from_sample(sample) if condition_from_sample else ""
    return {"sample": sample, "condition": condition, "fastq1": fastq1, "fastq2": fastq2}


def _build_initial_rows(fastq_rel, paired: bool, condition_from_sample: bool):
    _ = paired  # UI toggle only; do not auto-pair during initialization.
    return [_new_row(fq, condition_from_sample) for fq in fastq_rel]


def _coerce_editor_rows(edited):
    if edited is None:
        return []
    if isinstance(edited, list):
        return edited
    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")
    return list(edited)


def _clean_cell(value):
    return ui_samples.clean_cell(value)


def _coerce_rows_raw(rows):
    return ui_samples.coerce_rows_raw(rows)


def _normalize_rows(rows_raw, paired: bool, fastq_rel, autofill_conditions: bool):
    return ui_samples.normalize_rows(rows_raw, paired, fastq_rel, autofill_conditions)


def _sync_rows_raw_from_editor(editor_key: str = "samples_editor"):
    changed = ui_samples.sync_rows_raw_from_editor(editor_key)
    if changed:
        ui_state.mark_user_edit()


def _validate_rows(rows, fastq_rel, paired):
    return ui_samples.validate_rows(rows, fastq_rel, paired, _ref_exists, t)


def _validate_rows_report(rows, fastq_rel, paired):
    return ui_samples.validate_rows_report(rows, fastq_rel, paired, _ref_exists, t)


def _sanitize_disable_reasons(raw_reasons, rows, paired):
    return ui_samples.sanitize_disable_reasons(raw_reasons, rows, paired, t)


def _advanced_state():
    return ui_state.initialize_advanced_state(st.session_state)


def _advanced_value(key: str):
    return _advanced_state().get(key)


def _set_advanced_values(**updates):
    before = dict(_advanced_state())
    state = ui_state.update_advanced_state(st.session_state, **updates)
    if state != before:
        ui_state.mark_user_edit()
    return state


def _seed_widget_state(widget_key: str, value):
    if widget_key not in st.session_state:
        if isinstance(value, list):
            st.session_state[widget_key] = list(value)
        elif isinstance(value, dict):
            st.session_state[widget_key] = dict(value)
        else:
            st.session_state[widget_key] = value


def _translate_enrichment_reason(status: dict[str, object], engine: str) -> str:
    if normalize_engine(engine) != "real":
        return t("info.enrichment_requires_real")

    counts_text = ui_samples.format_condition_counts(status.get("condition_counts", {})) or t("label.none")
    reason_code = str(status.get("reason_code") or "")
    if reason_code == "min_conditions":
        return t(
            "info.enrichment_min_conditions",
            required=int(status.get("min_conditions") or 2),
            found=int(status.get("found_conditions") or 0),
            counts=counts_text,
        )
    if reason_code == "min_replicates":
        return t(
            "info.enrichment_min_replicates",
            required=int(status.get("min_replicates_per_condition") or 2),
            counts=counts_text,
        )
    return ""


def _enrichment_ui_status(rows: list[dict[str, object]], engine: str) -> tuple[bool, str, dict[str, object]]:
    status = ui_samples.enrichment_eligibility(rows)
    allowed = normalize_engine(engine) == "real" and bool(status.get("ok"))
    reason = "" if allowed else _translate_enrichment_reason(status, engine)
    return allowed, reason, status


def _compute_blockers(
    *,
    common_disable_errors,
    naming_issue,
    config_ok,
    saved_species,
    resolved_species,
    samples_ok,
    fastq_count,
    output_write_ok,
    validation_state,
    run_config_touched,
):
    blockers = list(common_disable_errors or [])
    if naming_issue:
        blockers.append(t("run_blocker.fastp_naming_mismatch"))
    if not config_ok:
        blockers.append(t("run_blocker.missing_config"))
    elif not saved_species:
        blockers.append(t("run_blocker.species_missing"))
    elif saved_species != resolved_species:
        blockers.append(t("run_blocker.species_mismatch", saved=saved_species, current=resolved_species))
    if not samples_ok:
        blockers.append(t("run_blocker.missing_samples_tsv"))
    if fastq_count == 0:
        blockers.append(t("run_blocker.no_fastq"))
    if not output_write_ok:
        blockers.append(t("run_blocker.output_not_writable"))

    state = validation_state if isinstance(validation_state, dict) else {}
    validation_ok = bool(state.get("ok", st.session_state.get("validation_ok")))
    if not validation_ok or run_config_touched:
        detail = (state.get("detail") or "").strip()
        if st.session_state.get("validation_failed"):
            blockers.append(f"validation_failed: {detail or 'Validation failed (no detail). Check logs.'}")
        else:
            blockers.append(detail or (t("msg.validate_needs_save") if not config_ok else t("msg.validate_needs_fix")))

    return sorted({str(reason) for reason in blockers if str(reason).strip()})


def _validate_refs(ref_mode, ref_block, refs_rel, ref_preset, ref_release):
    errors = []
    has_missing = False
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])
    if ref_mode == "none":
        errors.append(t("ref_error.not_ready"))
        return errors, True
    if ref_mode == "preset_cache":
        if not ref_preset:
            errors.append(t("ref_error.missing_ref_preset"))
            return errors, True
        cache_paths = _cache_ref_paths(ref_preset, ref_release)
        for key, path in cache_paths.items():
            status = _file_status(path)
            if status.get("status") != "present":
                errors.append(t("ref_error.file_not_found", field=key, val=path))
                has_missing = True
        return errors, has_missing
    if ref_mode == "fasta_gtf":
        for key in ("transcripts_fasta", "genome_fasta", "gtf"):
            val = _normalize_input_value(ref_block.get(key) or "")
            if not val:
                errors.append(t("ref_error.missing_key", field=key))
                has_missing = True
                continue
            if key == "gtf":
                if val not in gtf_rel and not _ref_exists(val):
                    errors.append(t("ref_error.file_not_found", field=key, val=val))
            else:
                if val not in fasta_rel and not _ref_exists(val):
                    errors.append(t("ref_error.file_not_found", field=key, val=val))
    elif ref_mode == "transcripts_only":
        val = _normalize_input_value(ref_block.get("transcripts_fasta") or "")
        if not val:
            errors.append(t("ref_error.missing_key", field="transcripts_fasta"))
            has_missing = True
        elif val not in fasta_rel and not _ref_exists(val):
            errors.append(t("ref_error.file_not_found", field="transcripts_fasta", val=val))
    return errors, has_missing


def _auto_pair(rows, available):
    return ui_samples.auto_pair(rows, available)


def _canonicalize_rows_after_autopair(rows, available=None):
    return ui_samples.canonicalize_rows_after_autopair(
        rows,
        available=available,
        autofill_conditions=bool(st.session_state.get("autofill_conditions", True)),
        translate=t,
    )


def _write_samples(rows, paired: bool):
    return ui_samples.write_samples(_ui_session_root(), rows, paired)


def _write_config(payload):
    out_path = _ui_session_config_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)
    return out_path


def _write_config_and_samples(payload, rows, paired):
    samples_path = _write_samples(rows, paired)
    config_path = _write_config(payload)
    return config_path, samples_path


def _check_saved_outputs():
    config_path = _ui_session_config_path()
    samples_path = _ui_session_samples_path()
    config_ok = config_path.exists() and config_path.stat().st_size > 0
    samples_ok = samples_path.exists() and samples_path.stat().st_size > 0
    return config_path, samples_path, config_ok, samples_ok


def _path_info(path: Path):
    if not path.exists():
        return f"{path} (missing)"
    return f"{path} ({path.stat().st_size} bytes)"


def _list_output_dir():
    entries = []
    if OUTPUT_ROOT.exists():
        for name in sorted(os.listdir(OUTPUT_ROOT)):
            full = OUTPUT_ROOT / name
            if full.is_dir():
                entries.append(f"{name}/")
            else:
                entries.append(name)
    return entries


def _output_write_test():
    test_path = OUTPUT_ROOT / ".ui_write_test"
    try:
        test_path.write_text("ok\n", encoding="utf-8")
        ok = test_path.exists() and test_path.stat().st_size > 0
        if test_path.exists():
            test_path.unlink()
        return ok, ""
    except Exception as exc:
        return False, str(exc)


def _io_access_state():
    input_ok = INPUT_ROOT.exists() and INPUT_ROOT.is_dir() and os.access(INPUT_ROOT, os.R_OK)
    output_ok = OUTPUT_ROOT.exists() and OUTPUT_ROOT.is_dir()
    output_writable = output_ok and os.access(OUTPUT_ROOT, os.W_OK)
    fastq_count = len(st.session_state.fastq_rel or [])
    ok = input_ok and output_ok and output_writable
    return {
        "ok": ok,
        "input_ok": input_ok,
        "output_ok": output_ok,
        "output_writable": output_writable,
        "fastq_count": fastq_count,
    }


def _check_fastp_output_naming(output_root: Path, paired: bool):
    if not paired:
        return ""
    fastp_dir = output_root / "fastp"
    if not fastp_dir.exists():
        return ""
    r1_files = list(fastp_dir.glob("*_R1.fastq"))
    r2_files = list(fastp_dir.glob("*_R2.fastq"))
    single_files = [
        p for p in fastp_dir.glob("*.fastq") if not p.name.endswith("_R1.fastq") and not p.name.endswith("_R2.fastq")
    ]
    if single_files and (r1_files or r2_files):
        return "mixed"
    if single_files:
        return "single"
    if (r1_files and not r2_files) or (r2_files and not r1_files):
        return "partial"
    return ""


def _resolve_species():
    value = normalize_species(_get_run_config().get("species"))
    if not value:
        return ""
    return value


def _mount_status():
    fastq_rel = st.session_state.fastq_rel
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])
    st.write(
        t(
            "label.input_scan",
            fastq=len(fastq_rel),
            fasta=len(fasta_rel),
            gtf=len(gtf_rel),
        )
    )
    if st.button(t("btn.test_output_write")):
        ok, detail = _output_write_test()
        if ok:
            st.success(t("status.output_writable"))
        else:
            st.error(t("error.output_not_writable"))
            if detail:
                st.code(detail)


def _host_mount_info():
    host_input = (os.environ.get("HOST_INPUT") or "").strip() or "unknown"
    host_out = (os.environ.get("HOST_OUT") or "").strip() or "unknown"
    st.caption(
        t(
            "info.host_paths",
            host_input=host_input,
            host_out=host_out,
        )
    )


def _load_ref_manifest():
    return ui_refs.load_ref_manifest(REF_MANIFEST_PATH)


def _species_presets(manifest, species):
    presets = ui_refs.species_presets(manifest or {}, species)
    if presets:
        return presets
    return sorted((manifest.get("presets") or {}).keys())


def _preset_releases(manifest, preset):
    return ui_refs.preset_releases(manifest or {}, preset) or ["pinned"]


def _ref_cache_root():
    cfg_root = str(_get_run_config().get("ref_cache_dir") or "").strip()
    if not cfg_root:
        return OUTPUT_ROOT / "refs_cache"
    root = Path(cfg_root)
    if not root.is_absolute():
        root = OUTPUT_ROOT / root
    return root


def _cache_ref_paths(preset, release, cache_root=None):
    root = Path(cache_root) if cache_root else _ref_cache_root()
    manifest = _load_ref_manifest()
    existing = ui_refs.resolve_existing_cache_paths(
        manifest, root, preset, release
    )
    if existing:
        values = existing["paths"]
        return {
            "transcripts_fasta": Path(values["transcripts_fasta_url"]),
            "genome_fasta": Path(values["genome_fasta_url"]),
            "gtf": Path(values["gtf_url"]),
        }
    canonical, canonical_release = ui_refs.resolve_preset_release(
        manifest, preset, release
    )
    base = root / canonical / canonical_release
    return {
        "transcripts_fasta": base / "transcripts.fa.gz",
        "genome_fasta": base / "genome.fa.gz",
        "gtf": base / "annotation.gtf.gz",
    }


def _gzip_ok(path: Path):
    if not path.name.lower().endswith(".gz"):
        return True
    cache = st.session_state.setdefault("gzip_status_cache", {})
    try:
        stat = path.stat()
        key = (str(path), int(stat.st_size), int(stat.st_mtime_ns))
        if key in cache:
            return cache[key]
    except Exception:
        return False
    ok = True
    try:
        rc, _ = _run_cmd(["gzip", "-t", str(path)])
        ok = rc == 0
    except FileNotFoundError:
        try:
            import gzip as _gzip

            with _gzip.open(path, "rb") as handle:
                handle.read(1024)
            ok = True
        except Exception:
            ok = False
    except Exception:
        ok = False
    cache[key] = ok
    return ok


def _file_status(path: Path):
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    mtime = (
        datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone(JST).strftime("%Y-%m-%d %H:%M:%S %Z")
        if exists
        else "-"
    )
    gzip_ok = True
    if exists and size > 0:
        gzip_ok = _gzip_ok(path)
    status = "missing"
    if exists and size > 0 and gzip_ok:
        status = "present"
    elif exists and (size == 0 or not gzip_ok):
        status = "invalid"
    try:
        display_path = path.relative_to(OUTPUT_ROOT)
    except ValueError:
        display_path = path
    return {
        "path": str(display_path),
        "exists": exists,
        "size": size,
        "updated_jst": mtime,
        "status": status,
    }


def _cache_status(paths):
    rows = []
    ok = True
    for key, path in paths.items():
        item = _file_status(path)
        if item["status"] != "present":
            ok = False
        row = {"file": key}
        row.update(item)
        rows.append(row)
    return ok, rows


def _ref_path_from_value(value: str):
    val = _normalize_input_value(value)
    if not val:
        return None
    if val.startswith("/"):
        return Path(val)
    return INPUT_ROOT / val


def _ref_status_table(ref_mode: str, ref_block: dict, ref_preset: str, ref_release: str):
    if ref_mode == "preset_cache" and ref_preset:
        cache_paths = _cache_ref_paths(ref_preset, ref_release)
        return _cache_status(cache_paths)
    rows = []
    ok = True
    keys = []
    if ref_mode == "transcripts_only":
        keys = ["transcripts_fasta"]
    elif ref_mode == "fasta_gtf":
        keys = ["transcripts_fasta", "genome_fasta", "gtf"]
    for key in keys:
        path = _ref_path_from_value(ref_block.get(key, ""))
        if path is None:
            rows.append({"file": key, "path": "-", "exists": False, "size": 0, "updated_jst": "-", "status": "missing"})
            ok = False
            continue
        item = _file_status(path)
        row = {"file": key}
        row.update(item)
        rows.append(row)
        if item["status"] != "present":
            ok = False
    return ok, rows


def _fetch_refs(preset, release, cache_root=None, overwrite=False):
    cache_dir = Path(cache_root) if cache_root else _ref_cache_root()
    cmd = [
        "python",
        str(REPO_ROOT / "scripts" / "fetch_reference_preset.py"),
        "--preset",
        preset,
        "--release",
        release,
        "--cache-dir",
        str(cache_dir),
        "--manifest",
        str(REF_MANIFEST_PATH),
    ]
    if overwrite:
        cmd.append("--overwrite")
    return _run_cmd(cmd)


def _ref_fetch_error_message(code: int, output: str):
    text = (output or "").lower()
    if "not checksum-pinned" in text:
        return t("error.ref_fetch_unverified")
    if code == 43 or "http 403" in text or "http 404" in text:
        return t("error.ref_fetch_url_unreachable")
    if "gzip test failed" in text or "is corrupted" in text:
        return t("error.ref_fetch_gzip_invalid")
    if "size is 0" in text:
        return t("error.ref_fetch_size_zero")
    if "gtf looks invalid" in text:
        return t("error.ref_fetch_gtf_invalid")
    return t("error.ref_fetch_failed_exit", code=code)


def _ref_fetch_state_key(run_config: dict):
    species = normalize_species(run_config.get("species")) or ""
    build = run_config.get("ref_release") or "pinned"
    preset = run_config.get("ref_preset") or "-"
    ref_mode = run_config.get("ref_mode") or "-"
    return f"{species}:{build}:{preset}:{ref_mode}"


def _set_op_log(op_name: str, status: str, text: str, rc: int | None = None, set_active: bool = False):
    logs = st.session_state.setdefault(
        "op_logs",
        {"save": "", "validate": "", "dryrun": "", "run": ""},
    )
    meta = st.session_state.setdefault("op_status", {})
    logs[op_name] = _tail_text(text or "")
    meta[op_name] = {
        "status": status,
        "rc": rc,
        "ok": status in ("success", "running"),
        "ts": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    st.session_state["op_logs"] = logs
    st.session_state["op_status"] = meta
    if set_active:
        st.session_state["active_op"] = op_name


def build_run_dirname(run_config: dict, run_id: str):
    return ui_run.build_run_dirname(run_config, run_id, _default_project_name())


def _human(n):
    size = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def _build_manifest_payload(payload: dict, rows_raw, fastq_rel):
    return ui_run.build_manifest_payload(
        payload=payload,
        rows_raw=rows_raw,
        fastq_rel=fastq_rel,
        coerce_rows_raw=_coerce_rows_raw,
        git_rev=_git_rev(),
        input_root=INPUT_ROOT,
    )


def _manifest_run_id(payload: dict):
    return ui_run.manifest_run_id(payload)


def _load_run_metadata(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_run_manifest(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_run_record(run_dir: Path):
    return ui_run.load_run_record(run_dir)


def _apply_run_record(run_record: dict, run_dir: Path):
    config = run_record.get("config") if isinstance(run_record.get("config"), dict) else {}
    manifest = run_record.get("manifest") if isinstance(run_record.get("manifest"), dict) else {}
    metadata = run_record.get("metadata") if isinstance(run_record.get("metadata"), dict) else {}
    payload = manifest.get("payload") if isinstance(manifest.get("payload"), dict) else {}
    manifest_config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    sample_rows = payload.get("samples") if isinstance(payload.get("samples"), list) else []

    state = _run_config_defaults()
    _merge_run_config(
        state,
        _saved_config_patch(
            config,
            sample_rows=sample_rows,
            manifest_config=manifest_config,
            legacy_frozen=True,
        ),
        overwrite=True,
    )
    st.session_state[RUN_CONFIG_KEY] = state
    updateRunConfig({})
    st.session_state.paired = bool(state.get("paired", False))
    if sample_rows:
        st.session_state.rows_raw = _coerce_rows_raw(sample_rows)
        st.session_state.rows_initialized = True
    st.session_state.saved = True
    st.session_state.run_config_touched = False
    st.session_state.run_config_path = str(run_record.get("config_path") or "")
    st.session_state.run_dir = str(run_dir)
    st.session_state.run_id = str(metadata.get("run_id") or manifest.get("run_id") or st.session_state.get("run_id") or "")
    compatibility = (
        run_record.get("analysis_compatibility")
        if isinstance(run_record.get("analysis_compatibility"), dict)
        else {}
    )
    if compatibility.get("legacy") and compatibility.get("resume_allowed"):
        ui_run.update_run_metadata(
            run_dir,
            {
                "analysis_policy_compatibility": {
                    "policy_version": 1,
                    "legacy_frozen_config": True,
                    "mode": (compatibility.get("plan") or {}).get("mode"),
                }
            },
        )
    try:
        _write_ui_state_json(_get_run_config())
        _write_ui_effective_config(
            {
                **_get_run_config(),
                "run_id": st.session_state.get("run_id"),
                "run_dir": str(run_dir),
                "config_path": st.session_state.get("run_config_path"),
            }
        )
    except Exception:
        pass


def _resolve_run_config_path(run_dir: Path):
    return ui_run.resolve_run_config_path(run_dir)


def _get_run_config_or_error(run_dir: Path):
    try:
        return _resolve_run_config_path(run_dir), ""
    except FileNotFoundError as exc:
        return None, str(exc)


def _run_dir_for_id(run_id: str):
    run_config = _get_run_config()
    preferred = RUNS_ROOT / build_run_dirname(run_config, run_id)
    legacy = RUNS_ROOT / run_id
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


def _write_run_metadata(run_dir: Path, metadata: dict):
    meta_dir = run_dir / "run"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return meta_path


def _write_run_manifest(run_dir: Path, run_id: str, payload: dict):
    return ui_run.write_run_manifest(run_dir, run_id, payload)


def _git_rev():
    try:
        code, out = _run_cmd(["git", "rev-parse", "HEAD"])
        if code != 0:
            return "unknown"
        rev = (out or "").splitlines()[0].strip()
        code2, out2 = _run_cmd(["git", "status", "--porcelain"])
        if code2 == 0 and (out2 or "").strip():
            rev += "+dirty"
        return rev
    except Exception:
        return "unknown"


def _prepare_run_dir(mode: str, run_dir: Path, run_exists: bool):
    if mode in ("resume", "open_existing") and run_exists:
        return run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_run_config(run_dir: Path, base_cfg: dict):
    return ui_run.write_frozen_run_config(run_dir, base_cfg, sample_table_source=_ui_session_samples_path())


def _run_cmd(cmd):
    return ui_run.run_cmd(cmd)


def _append_ui_command(cmd, work_id: str, label: str):
    ui_logging.append_ui_command(_ui_session_root(), cmd, work_id, label)


def _run_cmd_logged(cmd, work_id: str, label: str):
    _append_ui_command(cmd, work_id, label)
    return _run_cmd(cmd)


def _extract_snakemake_log_path(text: str):
    return ui_run.extract_snakemake_log_path(text)


def _extract_run_dir_from_cmd(cmd):
    if not isinstance(cmd, list):
        return None
    return ui_run.extract_run_dir_from_cmd(cmd)


def _shell_join_cmd(cmd):
    return ui_run.shell_join_cmd(cmd)


def _snakemake_version_text():
    return ui_run.snakemake_version_text()


def _write_snakemake_debug_files(run_dir: Path, cmd, stdout_text: str, stderr_text: str, version_text: str = "unknown"):
    ui_run.write_snakemake_debug_files(run_dir, cmd, stdout_text, stderr_text, version_text)


def _snakemake_log_candidates(run_dir: Path, limit: int = 10):
    return ui_run.snakemake_log_candidates(run_dir, limit=limit)


def _summarize_failure(text: str):
    return ui_run.summarize_failure(text)


def _failure_debug_commands(run_dir: Path):
    return ui_run.failure_debug_commands(run_dir)


def _dev_ui_enabled():
    return os.environ.get("HARAKO_DEV_UI") == "1"


def _public_path(path_like, run_dir: Path | None = None):
    return ui_run.format_public_path(path_like, run_dir=run_dir, output_root=OUTPUT_ROOT)


def _public_text(text: str, run_dir: Path | None = None, max_lines: int = 4):
    return ui_run.format_public_error(text, run_dir=run_dir, output_root=OUTPUT_ROOT, max_lines=max_lines)


def _sanitized_text(text: str, run_dir: Path | None = None):
    return ui_run.sanitize_public_text(text, run_dir=run_dir, output_root=OUTPUT_ROOT)


def _build_snakemake_base_cmd(run_dir: Path, config_path: Path, threads: int):
    return ui_run.build_snakemake_base_cmd(run_dir, config_path, threads)


def _pre_run_guard(run_dir: Path, config_path: Path, threads: int, work_id: str):
    return ui_run.pre_run_guard(run_dir, config_path, threads, work_id, _run_cmd_logged)


def _load_yaml(path: Path):
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _tail_text(text: str, max_chars: int = RUN_LOG_MAX_CHARS):
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _read_text(path: Path):
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _cleanup_run_handles():
    for key in ("run_stdout_handle", "run_stderr_handle", "run_handle"):
        handle = st.session_state.get(key)
        if handle:
            try:
                handle.close()
            except Exception:
                pass
        st.session_state[key] = None
    st.session_state.run_proc = None


def _start_run_report(threads: int, run_dir: Path, config_path: Path, extra_args=None):
    run_meta = run_dir / "run"
    run_meta.mkdir(parents=True, exist_ok=True)
    cmd_path = run_meta / "snakemake_cmd.txt"
    stdout_path = run_meta / "snakemake_stdout.txt"
    stderr_path = run_meta / "snakemake_stderr.txt"
    version_path = run_meta / "snakemake_version.txt"
    workdir = Path(ui_run.snakemake_workdir(str(run_dir)))
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    version_path.write_text(_snakemake_version_text() + "\n", encoding="utf-8")
    cmd = [
        "python",
        "-m",
        "snakemake",
        "--directory",
        str(workdir),
        "-s",
        "workflow/Snakefile",
        "--configfile",
        str(config_path),
        "--config",
        "input=/input",
        f"output={run_dir}",
        "--cores",
        str(int(threads)),
        "-p",
        "--show-failed-logs",
        "--latency-wait",
        "60",
    ]
    cmd = [item for item in cmd if item]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(["--", "report"])
    cmd_line = _shell_join_cmd(cmd)
    cmd_path.write_text(cmd_line + "\n", encoding="utf-8")
    (run_meta / "snakemake.cmd.txt").write_text(cmd_line + "\n", encoding="utf-8")
    (run_meta / "snakemake.stdout.log").write_text("", encoding="utf-8")
    (run_meta / "snakemake.stderr.log").write_text("", encoding="utf-8")
    ui_run.record_runtime_log_paths(run_dir, stdout_path=stdout_path, stderr_path=stderr_path, workdir=workdir)
    _append_ui_command(cmd, st.session_state.get("run_id", ""), "run_start")
    cfg_stat = {}
    try:
        stat = os.stat(config_path)
        cfg_stat = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
    except Exception:
        cfg_stat = {}
    _log_ui_event(
        "run_start",
        {
            "cmd": cmd,
            "run_dir": str(run_dir),
            "config_path": str(config_path),
            "workdir": str(workdir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "config_stat": cfg_stat,
            "state": _run_config_snapshot(),
        },
    )
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(cmd, stdout=stdout_handle, stderr=stderr_handle, text=True, env=env)
    st.session_state.run_proc = proc
    st.session_state.run_stdout_handle = stdout_handle
    st.session_state.run_stderr_handle = stderr_handle
    st.session_state.run_log_path = str(stdout_path)
    st.session_state.run_stdout_log_path = str(stdout_path)
    st.session_state.run_stderr_log_path = str(stderr_path)
    st.session_state.run_version_path = str(version_path)
    st.session_state.run_cmd_path = str(cmd_path)
    st.session_state.run_dir = str(run_dir)
    st.session_state.run_config_path = str(config_path)
    st.session_state.run_cmd = cmd
    st.session_state.run_status = "running"
    st.session_state.run_rc = None
    st.session_state.run_log = f"$ {' '.join(cmd)}\n"
    st.session_state.run_started_at = time.time()


def _poll_run_process():
    proc = st.session_state.get("run_proc")
    if not proc:
        if st.session_state.get("run_status") == "running":
            st.session_state.run_status = "failed"
            st.session_state.run_rc = -1
        return
    stdout_path_raw = st.session_state.get("run_stdout_log_path", "")
    stderr_path_raw = st.session_state.get("run_stderr_log_path", "")
    out_text = _tail_text(_read_text(Path(stdout_path_raw))) if stdout_path_raw else ""
    err_text = _tail_text(_read_text(Path(stderr_path_raw))) if stderr_path_raw else ""
    merged = out_text
    if err_text:
        merged = (merged + "\n\n[stderr]\n" + err_text).strip()
    st.session_state.run_log = merged
    run_dir = Path(st.session_state.get("run_dir")) if st.session_state.get("run_dir") else None
    if run_dir:
        main_log = _extract_snakemake_log_path(merged)
        ui_run.record_runtime_log_paths(
            run_dir,
            stdout_path=Path(stdout_path_raw) if stdout_path_raw else None,
            stderr_path=Path(stderr_path_raw) if stderr_path_raw else None,
            main_log_path=Path(main_log) if main_log else None,
        )
    rc = proc.poll()
    if rc is None:
        return
    st.session_state.run_rc = int(rc)
    st.session_state.run_status = "success" if rc == 0 else "failed"
    _cleanup_run_handles()


def _stop_run_process():
    proc = st.session_state.get("run_proc")
    if not proc:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    time.sleep(0.5)
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
    st.session_state.run_rc = proc.poll() if proc.poll() is not None else -15
    st.session_state.run_status = "stopped"
    _cleanup_run_handles()


def _get_conditions(rows):
    return sorted({row.get("condition", "") for row in rows if row.get("condition")})


def _build_contrast(rows, left, right):
    if left and right and left != right:
        return [f"{left}_vs_{right}"]
    return []


def _clamp_step(x):
    return max(0, min(x, len(steps) - 1))


st.set_page_config(
    page_title="Harako-RNAseq Web UI",
    page_icon=str(LOGO_PNG_PATH) if LOGO_PNG_PATH.exists() else None,
    layout="wide",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)

st.markdown(
    """
<style>
[data-testid="stDataEditor"] button {
  min-width: 40px;
  min-height: 40px;
}
[data-testid="stDataEditor"] svg {
  width: 32px;
  height: 32px;
}
</style>
""",
    unsafe_allow_html=True,
)

_ensure_ui_session_id()
_restore_run_config()

if "step" not in st.session_state:
    st.session_state.step = 0
if "step_epoch" not in st.session_state:
    st.session_state.step_epoch = 0
if "rows_raw" not in st.session_state:
    legacy_rows = st.session_state.get("rows", [])
    st.session_state.rows_raw = _coerce_rows_raw(legacy_rows)
if "rows_initialized" not in st.session_state:
    st.session_state.rows_initialized = False
if "auto_pair_warnings" not in st.session_state:
    st.session_state.auto_pair_warnings = []
if "paired" not in st.session_state:
    st.session_state.paired = bool(_get_run_config().get("paired", False))
if "fastq_rel" not in st.session_state:
    st.session_state.fastq_rel = []
if "refs_rel" not in st.session_state:
    st.session_state.refs_rel = {"fasta": [], "gtf": []}
if "autofill_conditions" not in st.session_state:
    st.session_state.autofill_conditions = True
if "run_status" not in st.session_state:
    st.session_state.run_status = "idle"
if "run_log" not in st.session_state:
    st.session_state.run_log = ""
if "run_rc" not in st.session_state:
    st.session_state.run_rc = None
if "run_proc" not in st.session_state:
    st.session_state.run_proc = None
if "run_handle" not in st.session_state:
    st.session_state.run_handle = None
if "run_stdout_handle" not in st.session_state:
    st.session_state.run_stdout_handle = None
if "run_stderr_handle" not in st.session_state:
    st.session_state.run_stderr_handle = None
if "run_log_path" not in st.session_state:
    st.session_state.run_log_path = ""
if "run_stdout_log_path" not in st.session_state:
    st.session_state.run_stdout_log_path = ""
if "run_stderr_log_path" not in st.session_state:
    st.session_state.run_stderr_log_path = ""
if "run_version_path" not in st.session_state:
    st.session_state.run_version_path = ""
if "run_cmd_path" not in st.session_state:
    st.session_state.run_cmd_path = ""
if "run_dir" not in st.session_state:
    st.session_state.run_dir = ""
if "run_config_path" not in st.session_state:
    st.session_state.run_config_path = ""
if "rerun_incomplete" not in st.session_state:
    st.session_state.rerun_incomplete = True
if "auto_recover" not in st.session_state:
    st.session_state.auto_recover = True
if "auto_recover_cleanup" not in st.session_state:
    st.session_state.auto_recover_cleanup = False
if "auto_recover_incomplete" not in st.session_state:
    st.session_state.auto_recover_incomplete = False
if "run_guard" not in st.session_state:
    st.session_state.run_guard = None
if "run_mode" not in st.session_state:
    st.session_state.run_mode = "start_new"
if "show_fix_commands" not in st.session_state:
    st.session_state.show_fix_commands = False
if "lang" not in st.session_state:
    st.session_state.lang = "en"
if "saved" not in st.session_state:
    st.session_state.saved = False
if "validation_ok" not in st.session_state:
    st.session_state.validation_ok = False
if "validation" not in st.session_state:
    st.session_state.validation = {
        "ok": bool(st.session_state.get("validation_ok", False)),
        "detail": None,
        "ts": datetime.now(timezone.utc).isoformat(),
        "traceback": None,
    }
if "save" not in st.session_state:
    st.session_state.save = {
        "ok": None,
        "detail": None,
        "ts": None,
        "traceback": None,
    }
if bool((st.session_state.get("validation") or {}).get("ok", False)):
    st.session_state.pop("validation_failed", None)
    st.session_state.pop("validation_failed_detail", None)
    if isinstance(st.session_state.get("blockers"), list):
        st.session_state["blockers"] = [item for item in st.session_state["blockers"] if not str(item).startswith("validation_failed")]
if "run_config_touched" not in st.session_state:
    st.session_state.run_config_touched = False
if "ref_fetch_state" not in st.session_state:
    st.session_state.ref_fetch_state = {}
if "op_logs" not in st.session_state:
    st.session_state.op_logs = {"save": "", "validate": "", "dryrun": "", "run": ""}
if "op_status" not in st.session_state:
    st.session_state.op_status = {}
if "active_op" not in st.session_state:
    st.session_state.active_op = "save"
ui_state.initialize_advanced_state(st.session_state)

lang_options = ["en", "ja"]
lang_index = 0 if st.session_state.lang == "en" else 1
st.sidebar.selectbox(t("sidebar.language"), lang_options, index=lang_index, key="lang")
if LOGO_PNG_PATH.exists():
    st.sidebar.image(str(LOGO_PNG_PATH), width=96)

if not st.session_state.refs_rel["fasta"] and not st.session_state.refs_rel["gtf"]:
    fasta, gtf = _scan_refs(INPUT_ROOT)
    st.session_state.refs_rel = {
        "fasta": [_rel(p) for p in fasta],
        "gtf": [_rel(p) for p in gtf],
    }

steps = [
    t("label.project_step"),
    t("label.samples_step"),
    t("label.reference_files"),
    t("label.advanced"),
    t("label.summary"),
]
ss = st.session_state
ss.step = _clamp_step(int(ss.step))
ss.step_radio = ss.step

header_left, header_right = st.columns([3, 2])
with header_left:
    run_cfg_header = _get_run_config()
    ui_state.initialize_project_name(
        st.session_state,
        run_cfg_header,
        _default_project_name(),
        touched=bool(st.session_state.get("run_config_touched")),
    )
    logo_col, text_col = st.columns([1, 6])
    with logo_col:
        if LOGO_PNG_PATH.exists():
            st.image(str(LOGO_PNG_PATH), width=LOGO_DISPLAY_WIDTH)
    with text_col:
        st.title("Harako-RNAseq Web UI")
        st.caption(t("info.subtitle_wizard"))
    project_name_input = st.text_input(
        t("label.project_name"),
        key=ui_state.PROJECT_NAME_SESSION_KEY,
        on_change=_on_project_name_change,
    )
with header_right:
    limits_help = t("help.runtime_limits")
    run_cfg = _get_run_config()
    threads_req = int(run_cfg.get("threads") or 1)
    threads_limit = _detect_cpu_limit()
    mem_limit = _detect_memory_limit()
    st.caption(t("label.runtime_limits"))
    st.caption(
        t(
            "label.runtime_limits_detail",
            threads=threads_req,
            threads_limit=threads_limit,
            memory=mem_limit["display"],
        )
    )
    st.markdown(
        f"<span title='{limits_help}'>{t('label.runtime_limits_help')}</span>",
        unsafe_allow_html=True,
    )
status_key = _run_config_status()
st.caption(t(f"status.{status_key}"))
io_state = _io_access_state()
if not io_state["ok"]:
    st.warning("\n".join(_t_lines("msg.io_inaccessible")))

col1, col2 = st.columns([3, 1])
with col1:
    st.progress((st.session_state.step + 1) / len(steps))
with col2:
    st.write(f"Step {st.session_state.step + 1} / {len(steps)}: {steps[st.session_state.step]}")


def _on_step_change():
    _set_step(_clamp_step(int(st.session_state.step_radio)), trigger="radio")


def _cleanup_ui_for_step(step_from: int, step_to: int):
    deleted = []
    step_prefix = f"page:{step_from}:"
    for key in list(st.session_state.keys()):
        key_str = str(key)
        if key_str.startswith(step_prefix):
            deleted.append(key_str)
            del st.session_state[key]
    # Backward-compat cleanup for historical non-namespaced keys.
    if step_from == 1 and "samples_editor" in st.session_state:
        deleted.append("samples_editor")
        del st.session_state["samples_editor"]
    if step_from == 2:
        for key in ("ref_download_overwrite",):
            if key in st.session_state:
                deleted.append(key)
                del st.session_state[key]
    _log_ui_event(
        "ui_cleanup",
        {
            "from": step_from,
            "to": step_to,
            "deleted": deleted,
            "step_epoch": int(st.session_state.get("step_epoch", 0)),
        },
    )
    return deleted


def _set_step(step_to: int, trigger: str = "nav"):
    step_from = int(st.session_state.get("step", 0))
    step_to = _clamp_step(int(step_to))
    if step_from == step_to:
        return
    _cleanup_ui_for_step(step_from, step_to)
    st.session_state.step_epoch = int(st.session_state.get("step_epoch", 0)) + 1
    st.session_state.step = step_to
    _log_ui_event(
        "step_change",
        {
            "from": step_from,
            "to": step_to,
            "trigger": trigger,
            "step_epoch": int(st.session_state.get("step_epoch", 0)),
        },
    )


def _nav_buttons():
    nav_left, nav_mid, nav_right = st.columns([1, 3, 1])
    with nav_left:
        if st.button("Back", disabled=st.session_state.step <= 0):
            _set_step(st.session_state.step - 1, trigger="back")
    with nav_mid:
        st.radio(
            "Step",
            options=list(range(len(steps))),
            index=st.session_state.step,
            format_func=lambda i: f"{i + 1}/{len(steps)}: {steps[i]}",
            key="step_radio",
            on_change=_on_step_change,
            horizontal=True,
        )
    with nav_right:
        if st.button("Next", disabled=st.session_state.step >= len(steps) - 1):
            _set_step(st.session_state.step + 1, trigger="next")


_nav_buttons()

prev_step = st.session_state.get("last_step")
current_step = st.session_state.step
prev_snapshot = st.session_state.get("last_run_config_snapshot")
current_snapshot = _run_config_snapshot()
if prev_step is not None and prev_step != current_step:
    _log_ui_event(
        "route_change",
        {
            "from": prev_step,
            "to": current_step,
            "prev_state": prev_snapshot,
            "state": current_snapshot,
            "state_changed": prev_snapshot != current_snapshot,
            "step_epoch": int(st.session_state.get("step_epoch", 0)),
        },
    )
    _log_debug("route_change", prev_snapshot or {}, current_snapshot or {})
st.session_state.last_step = current_step
st.session_state.last_run_config_snapshot = current_snapshot

summary_state = _get_run_config()
page_key = f"page:{st.session_state.step}:{int(st.session_state.get('step_epoch', 0))}"
st.caption(
    t(
        "label.run_config_summary",
        species=normalize_species(summary_state.get("species")) or "-",
        engine=normalize_engine(summary_state.get("engine")) or "-",
        threads=int(summary_state.get("threads") or 1),
        preset=summary_state.get("ref_preset") or "-",
        protocol=t(
            f"label.library_protocol.{summary_state.get('library_protocol')}"
        ) if summary_state.get("library_protocol") else t("label.library_protocol.unselected"),
    )
)


if st.session_state.step == 0:
    st.subheader(t("label.project_step"))
    st.caption(t("step_desc.project"))
    _mount_status()
    io_state = _io_access_state()
    if not io_state["ok"]:
        st.warning("\n".join(_t_lines("msg.io_inaccessible")))
        _host_mount_info()
        st.caption(t("label.io_status"))
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
    run_config = _get_run_config()
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
        updateRunConfig({"engine": engine_choice})
    paired_options = [t("label.single_end"), t("label.paired_end")]
    paired_value = bool(run_config.get("paired", False))
    paired_index = 1 if paired_value else 0
    paired_choice = st.radio(
        t("label.read_layout"),
        paired_options,
        index=paired_index,
        horizontal=True,
    )
    paired_selected = paired_choice == t("label.paired_end")
    if paired_selected != paired_value:
        updateRunConfig({"paired": paired_selected})
        st.session_state.paired = paired_selected
    protocol_value = str(run_config.get("library_protocol") or "")
    protocol_options = ["", *NEW_LIBRARY_PROTOCOLS]
    if protocol_value == LEGACY_UNSPECIFIED:
        protocol_options.append(LEGACY_UNSPECIFIED)
    protocol_choice = st.selectbox(
        t("label.library_protocol"),
        options=protocol_options,
        index=protocol_options.index(protocol_value) if protocol_value in protocol_options else 0,
        format_func=lambda value: t(f"label.library_protocol.{value or 'unselected'}"),
        help=t("help.library_protocol"),
        disabled=protocol_value == LEGACY_UNSPECIFIED,
    )
    if protocol_choice != protocol_value:
        updateRunConfig({"library_protocol": protocol_choice})
    threads_value = int(run_config.get("threads") or 1)
    threads_choice = st.number_input(
        t("label.threads"),
        min_value=1,
        max_value=64,
        value=threads_value,
        step=1,
    )
    if int(threads_choice) != threads_value:
        updateRunConfig({"threads": int(threads_choice)})
    st.caption(t("info.threads_cap"))
    if st.button(t("btn.refresh_scan")):
        selected_subdirs = list(_get_run_config().get("selected_subdirs") or [])
        st.session_state.fastq_rel = [_rel(p) for p in _scan_fastq_selected(INPUT_ROOT, selected_subdirs)]
        fasta, gtf = _scan_refs(INPUT_ROOT)
        st.session_state.refs_rel = {
            "fasta": [_rel(p) for p in fasta],
            "gtf": [_rel(p) for p in gtf],
        }

elif st.session_state.step == 1:
    st.subheader(t("label.samples_step"))
    st.caption(t("step_desc.samples"))
    subdir_options = _list_subdirs(INPUT_ROOT)
    run_config = _get_run_config()
    selected_subdirs = [item for item in list(run_config.get("selected_subdirs") or []) if item in subdir_options]

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
        updateRunConfig({"selected_subdirs": selected_ui})
        st.session_state.rows_initialized = False
        st.session_state.rows_raw = []
        st.session_state.auto_pair_warnings = []
        selected_subdirs = selected_ui

    fastq_rel = [_rel(p) for p in _scan_fastq_selected(INPUT_ROOT, selected_subdirs)]
    st.session_state.fastq_rel = fastq_rel
    counts = _fastq_read_counts(fastq_rel)
    if st.session_state.paired:
        st.write(
            t(
                "label.fastq_summary_paired",
                total=len(fastq_rel),
                r1=counts["r1"],
                r2=counts["r2"],
                unknown=counts["unknown"],
            )
        )
    else:
        st.write(t("label.fastq_summary_single", total=len(fastq_rel)))
    if len(selected_subdirs) == 0:
        st.warning("No subdirectories selected. Select one or more folders to list FASTQ files.")
        st.stop()
    if len(fastq_rel) == 0:
        st.warning("No FASTQ files found under selected subdirectories.")
        st.stop()

    st.checkbox(t("label.autofill_condition"), key="autofill_conditions")
    if not st.session_state.rows_initialized:
        st.session_state.rows_raw = _build_initial_rows(
            fastq_rel,
            st.session_state.paired,
            st.session_state.autofill_conditions,
        )
        st.session_state.rows_initialized = True

    auto_pair_col, normalize_col = st.columns(2)
    if st.session_state.paired:
        if auto_pair_col.button(t("btn.auto_pair")):
            paired_rows = _auto_pair(_coerce_rows_raw(st.session_state.rows_raw), fastq_rel)
            canonical_rows, canonical_warnings = _canonicalize_rows_after_autopair(paired_rows, fastq_rel)
            st.session_state.rows_raw = canonical_rows
            st.session_state.auto_pair_warnings = canonical_warnings
            ui_state.mark_user_edit()
    else:
        auto_pair_col.button(t("btn.auto_pair"), disabled=True)
        st.caption(t("info.auto_pair_disabled"))
    if normalize_col.button(t("btn.normalize_conditions")):
        st.session_state.rows_raw = ui_samples.apply_condition_autofill(st.session_state.rows_raw, overwrite=True)
        ui_state.mark_user_edit()

    st.caption(t("hint.sample_naming"))

    cols = ["sample", "condition", "fastq1"]
    if st.session_state.paired:
        cols.append("fastq2")

    column_config = {
        "sample": st.column_config.TextColumn("sample"),
        "condition": st.column_config.TextColumn("condition"),
        "fastq1": st.column_config.TextColumn("fastq1"),
    }
    if st.session_state.paired:
        column_config["fastq2"] = st.column_config.TextColumn("fastq2")

    editor_rows_raw = _coerce_rows_raw(st.session_state.rows_raw)
    editor_rows = [{k: row.get(k, "") for k in cols} for row in editor_rows_raw]
    editor_df = pd.DataFrame(editor_rows, columns=cols)
    samples_editor_key = f"{page_key}:samples_editor"
    st.data_editor(
        editor_df,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config=column_config,
        key=samples_editor_key,
        on_change=_sync_rows_raw_from_editor,
        args=(samples_editor_key,),
    )

    issues = _validate_rows(st.session_state.rows_raw, fastq_rel, st.session_state.paired)
    if st.session_state.paired:
        r2_in_fastq1 = []
        for idx, row in enumerate(st.session_state.rows_raw, start=1):
            if _read_side(row.get("fastq1", "")) == "2":
                r2_in_fastq1.append(t("row_issue.row_label", row=idx, sample=row.get("sample", "")))
        if r2_in_fastq1:
            issues.append(t("warn.fastq1_looks_like_read2", details=", ".join(r2_in_fastq1)))
    auto_pair_warnings = st.session_state.get("auto_pair_warnings", [])
    if auto_pair_warnings:
        st.warning(t("warn.autopair_canonicalization", details="\n".join(auto_pair_warnings)))
    if issues:
        st.warning(t("warn.fix_issues_before_saving", details="\n".join(issues)))

elif st.session_state.step == 2:
    st.subheader(t("label.reference_files"))
    st.caption(t("step_desc.reference"))
    manifest = _load_ref_manifest()
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])

    run_config = _get_run_config()
    ref_fetch_state = st.session_state.setdefault("ref_fetch_state", {})
    ref_state_key = _ref_fetch_state_key(run_config)
    use_custom_refs_key = f"{page_key}:use_custom_refs"
    use_custom_refs_value = st.checkbox(
        t("label.use_custom_refs"),
        value=bool(run_config.get("use_custom_refs", False)),
        key=use_custom_refs_key,
    )
    if use_custom_refs_value != bool(run_config.get("use_custom_refs", False)):
        updateRunConfig({"use_custom_refs": use_custom_refs_value})
        run_config = _get_run_config()
        ref_state_key = _ref_fetch_state_key(run_config)
    use_custom_refs = bool(run_config.get("use_custom_refs", False))

    ref_cache_root = _ref_cache_root()
    species_choices = []
    for preset in (
        "mouse_ensembl_grcm38",
        "mouse_ensembl_grcm39",
        "human_ensembl_grch38",
        "rat_ensembl_mratbn7_2",
    ):
        metadata = ui_refs.get_preset_metadata(manifest, preset)
        species_choices.append(
            {
                "label": metadata["display_name"],
                "species": metadata["species"],
                "preset": preset,
            }
        )
    labels = [choice["label"] for choice in species_choices]
    run_config = _get_run_config()
    migration_notice = run_config.get("_ref_migration_notice")
    notice_key = json.dumps(migration_notice, sort_keys=True) if migration_notice else ""
    if migration_notice and st.session_state.get("_shown_ref_migration_notice") != notice_key:
        st.warning(t("warn.ref_preset_migrated", **migration_notice))
        st.session_state["_shown_ref_migration_notice"] = notice_key
    preset_value = run_config.get("ref_preset", "")
    species_value = normalize_species(run_config.get("species"))
    selected_index = 0
    for idx, choice in enumerate(species_choices):
        if preset_value and choice["preset"] == preset_value:
            selected_index = idx
            break
        if not preset_value and choice["species"] == species_value:
            selected_index = idx
    species_label = st.selectbox(
        t("label.species_build"),
        labels,
        index=selected_index,
        key=f"{page_key}:species_build",
    )
    selected = species_choices[labels.index(species_label)]
    if selected["species"] != species_value:
        updateRunConfig({"species": selected["species"]})
        run_config = _get_run_config()
        species_value = normalize_species(run_config.get("species"))
        preset_value = run_config.get("ref_preset", "")
    if not use_custom_refs and selected["preset"] and selected["preset"] != preset_value:
        updateRunConfig({"ref_preset": selected["preset"]})
        run_config = _get_run_config()
        preset_value = run_config.get("ref_preset", "")

    if not use_custom_refs:
        presets_all = manifest.get("presets") or {}
        preset_available = preset_value in presets_all
        if not preset_available:
            st.warning(t("warn.preset_unavailable", preset=preset_value))
        release_options = _preset_releases(manifest, preset_value) if preset_available else ["pinned"]
        if not release_options:
            release_options = ["pinned"]
        run_config = _get_run_config()
        release_value = run_config.get("ref_release") or "pinned"
        if release_value not in release_options:
            release_value = release_options[0]
            updateRunConfig({"ref_release": release_value})
        release_index = release_options.index(release_value) if release_value in release_options else 0
        release_choice = st.selectbox(
            t("label.release"),
            release_options,
            index=release_index,
            help=t("help.ref_release"),
            disabled=not preset_available,
            key=f"{page_key}:ref_release",
        )
        if release_choice != release_value:
            updateRunConfig({"ref_release": release_choice})
            release_value = release_choice
        run_config = _get_run_config()
        ref_state_key = _ref_fetch_state_key(run_config)

        preset = preset_value
        release = release_value
        if not preset:
            st.warning(t("ref_error.missing_ref_preset"))
            cache_ok = False
            rows = []
        else:
            cache_ok, rows = _ref_status_table("preset_cache", {}, preset, release)
            cache_resolution = ui_refs.resolve_existing_cache_paths(
                manifest, ref_cache_root, preset, release
            )
            if cache_resolution and cache_resolution["cache_source"] == "legacy_alias":
                st.info(
                    t(
                        "info.legacy_ref_cache_reused",
                        preset=cache_resolution["preset"],
                        release=cache_resolution["release"],
                    )
                )
            _, _, release_entry = ui_refs.get_release_entry(
                manifest, preset, release
            )
            hashes = release_entry.get("sha256", {})
            hashes_complete = all(hashes.get(key) for key in ui_refs.REFERENCE_FILES)
            if not hashes_complete:
                st.warning(t("warn.reference_unverified"))
            cache_dir = _cache_ref_paths(preset, release, ref_cache_root)["gtf"].parent
            try:
                display_cache_dir = cache_dir.relative_to(OUTPUT_ROOT)
            except ValueError:
                display_cache_dir = cache_dir
            st.write(t("label.cache_directory", path=display_cache_dir))
            df_rows = pd.DataFrame(rows)
            if not df_rows.empty:
                df_rows["status"] = df_rows["status"].map(
                    {"present": t("status.present"), "missing": t("status.missing"), "invalid": t("status.invalid")}
                )
            st.dataframe(df_rows, width="stretch", hide_index=True)
            if not cache_ok:
                st.caption(t("msg.refs_download_needed"))

            overwrite_refs = st.checkbox(
                t("label.ref_download_overwrite"),
                value=False,
                key=f"{page_key}:ref_download_overwrite",
            )
            fetch_disabled = (
                (cache_ok and not overwrite_refs)
                or (not preset_available)
                or (not hashes_complete)
            )
            locate_disabled = not preset_available
            st.caption(t("desc.locate_refs_local"))
            st.caption(
                t(
                    "label.locate_scan_dirs",
                    ref_cache_dir=str(ref_cache_root),
                    preset_cache_dir=str(cache_dir),
                )
            )
            if st.button(t("btn.download_refs"), disabled=locate_disabled):
                locate_ok, locate_rows = _ref_status_table("preset_cache", {}, preset, release)
                locate_df = pd.DataFrame(locate_rows)
                if not locate_df.empty:
                    locate_df["status"] = locate_df["status"].map(
                        {"present": t("status.present"), "missing": t("status.missing"), "invalid": t("status.invalid")}
                    )
                st.dataframe(locate_df, width="stretch", hide_index=True)
                ref_fetch_state[ref_state_key] = {
                    "status": "success" if locate_ok else "error",
                    "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "message": t("status.present") if locate_ok else t("status.missing"),
                }

            st.caption(t("desc.download_refs_url"))
            if st.button(t("btn.download_refs_url"), disabled=fetch_disabled):
                ref_fetch_state[ref_state_key] = {
                    "status": "running",
                    "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "message": "fetch started",
                }
                cmd = [
                    "python",
                    str(REPO_ROOT / "scripts" / "fetch_reference_preset.py"),
                    "--preset",
                    preset,
                    "--release",
                    release,
                    "--cache-dir",
                    str(ref_cache_root),
                    "--manifest",
                    str(REF_MANIFEST_PATH),
                    "--progress-jsonl",
                ]
                if overwrite_refs:
                    cmd.append("--overwrite")
                pinned_dir = _cache_ref_paths(preset, release, ref_cache_root)["gtf"].parent
                paths = {
                    "transcripts": pinned_dir / "transcripts.fa.gz",
                    "genome": pinned_dir / "genome.fa.gz",
                    "gtf": pinned_dir / "annotation.gtf.gz",
                }
                file_state = {
                    key: {"downloaded": 0, "total": None, "done": False}
                    for key in paths
                }
                stdout_extra = []
                with st.status(t("status.fetch_refs_running"), state="running") as status:
                    prog = st.progress(0.0)
                    lines = st.empty()
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                    )
                    if proc.stdout is not None:
                        for raw in proc.stdout:
                            line = raw.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                stdout_extra.append(line)
                                continue
                            event_type = event.get("event")
                            label = event.get("file")
                            if label in file_state:
                                if event_type == "start":
                                    file_state[label]["total"] = event.get("total")
                                elif event_type == "chunk":
                                    file_state[label]["downloaded"] = event.get("downloaded", 0)
                                    if event.get("total") is not None:
                                        file_state[label]["total"] = event.get("total")
                                elif event_type == "done":
                                    file_state[label]["done"] = True
                                    dest = event.get("dest")
                                    if dest and os.path.exists(dest):
                                        file_state[label]["downloaded"] = os.path.getsize(dest)
                            done = sum(1 for s in file_state.values() if s["done"])
                            prog.progress(done / 3.0)
                            status_lines = []
                            for key, state in file_state.items():
                                if state["done"]:
                                    status_lines.append(f"{key}: done ({_human(state['downloaded'])})")
                                elif state["downloaded"]:
                                    if state["total"]:
                                        pct = state["downloaded"] * 100.0 / state["total"]
                                        status_lines.append(
                                            f"{key}: {_human(state['downloaded'])}/{_human(state['total'])} ({pct:.1f}%)"
                                        )
                                    else:
                                        status_lines.append(f"{key}: {_human(state['downloaded'])}")
                                else:
                                    status_lines.append(f"{key}: (not started)")
                            lines.text("\n".join(status_lines))
                    rc = proc.wait()
                    stderr = (proc.stderr.read() if proc.stderr else "").strip()
                    done = sum(1 for s in file_state.values() if s["done"])
                    prog.progress(done / 3.0)
                    if rc == 0 and done == 3:
                        updateRunConfig(
                            {
                                "use_custom_refs": False,
                                "ref_mode": "preset_cache",
                                "ref_transcripts": "",
                                "ref_genome": "",
                                "ref_gtf": "",
                            }
                        )
                        selected_subdirs = list(_get_run_config().get("selected_subdirs") or [])
                        st.session_state.fastq_rel = [_rel(p) for p in _scan_fastq_selected(INPUT_ROOT, selected_subdirs)]
                        fasta, gtf = _scan_refs(INPUT_ROOT)
                        st.session_state.refs_rel = {
                            "fasta": [_rel(p) for p in fasta],
                            "gtf": [_rel(p) for p in gtf],
                        }
                        ref_fetch_state[ref_state_key] = {
                            "status": "success",
                            "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                            "message": t("success.ref_fetch_completed"),
                        }
                        status.update(label=t("success.ref_fetch_completed"), state="complete")
                        with st.expander(t("label.details")):
                            if stdout_extra:
                                st.text_area("Fetch refs (URL) stdout", "\n".join(stdout_extra), height=140)
                            if stderr:
                                st.text_area("Fetch refs (URL) stderr", stderr, height=140)
                        st.rerun()
                    else:
                        ref_fetch_state[ref_state_key] = {
                            "status": "error",
                            "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                            "message": _ref_fetch_error_message(rc, stderr or "\n".join(stdout_extra)),
                        }
                        status.update(label=t("status.fetch_refs_failed"), state="error")
                        st.error(_ref_fetch_error_message(rc, stderr or "\n".join(stdout_extra)))
                        st.warning(t("warn.ref_fetch_custom_fallback"))
                        st.code(
                            "refs/transcripts.fa.gz\n"
                            "refs/genome.fa.gz\n"
                            "refs/annotation.gtf.gz"
                        )
                        if stdout_extra:
                            st.text_area("Fetch refs (URL) stdout", "\n".join(stdout_extra), height=140)

        if cache_ok:
            st.caption(t("info.using_cached_refs"))
        else:
            st.warning(t("warning.fetch_refs_to_enable"))
        latest = ref_fetch_state.get(ref_state_key)
        if latest:
            st.caption(f"[fetch:{latest.get('status')}] {latest.get('updated_at')} - {latest.get('message')}")
    else:
        mode_options = ["fasta_gtf", "transcripts_only"]
        mode_value = run_config.get("ref_mode", "fasta_gtf")
        if mode_value not in mode_options:
            mode_value = "fasta_gtf"
        mode = st.selectbox(
            t("label.reference_mode"),
            mode_options,
            index=mode_options.index(mode_value),
            key=f"{page_key}:ref_mode",
        )
        if mode != run_config.get("ref_mode"):
            updateRunConfig({"ref_mode": mode})
        if mode in ("fasta_gtf", "transcripts_only") and not fasta_rel:
            st.error(t("error.no_fasta"))
            st.stop()
        if mode == "fasta_gtf" and not gtf_rel:
            st.error(t("error.no_gtf"))
            st.stop()

        transcript_options = fasta_rel or [""]
        genome_options = fasta_rel or [""]
        gtf_options = gtf_rel or [""]
        ref_transcripts_value = _normalize_ref(run_config.get("ref_transcripts", "")) or _pick_ref_candidate(fasta_rel, ["transcript", "cdna"])
        ref_genome_value = _normalize_ref(run_config.get("ref_genome", "")) or _pick_ref_candidate(fasta_rel, ["genome"])
        ref_gtf_value = _normalize_ref(run_config.get("ref_gtf", "")) or _pick_ref_candidate(gtf_rel, ["gtf"])
        if ref_transcripts_value and ref_transcripts_value not in transcript_options:
            transcript_options = [ref_transcripts_value] + transcript_options
        if ref_genome_value and ref_genome_value not in genome_options:
            genome_options = [ref_genome_value] + genome_options
        if ref_gtf_value and ref_gtf_value not in gtf_options:
            gtf_options = [ref_gtf_value] + gtf_options

        if mode == "transcripts_only":
            transcripts_choice = st.selectbox(
                t("label.transcripts_fasta"),
                transcript_options,
                index=transcript_options.index(ref_transcripts_value) if ref_transcripts_value in transcript_options else 0,
                key=f"{page_key}:ref_transcripts",
            )
            updateRunConfig(
                {
                    "use_custom_refs": True,
                    "ref_mode": "transcripts_only",
                    "ref_transcripts": _normalize_ref(transcripts_choice),
                    "ref_genome": "",
                    "ref_gtf": "",
                }
            )
        else:
            transcripts_choice = st.selectbox(
                t("label.transcripts_fasta"),
                transcript_options,
                index=transcript_options.index(ref_transcripts_value) if ref_transcripts_value in transcript_options else 0,
                key=f"{page_key}:ref_transcripts",
            )
            genome_choice = st.selectbox(
                t("label.genome_fasta"),
                genome_options,
                index=genome_options.index(ref_genome_value) if ref_genome_value in genome_options else 0,
                key=f"{page_key}:ref_genome",
            )
            gtf_choice = st.selectbox(
                t("label.gtf"),
                gtf_options,
                index=gtf_options.index(ref_gtf_value) if ref_gtf_value in gtf_options else 0,
                key=f"{page_key}:ref_gtf",
            )
            updateRunConfig(
                {
                    "use_custom_refs": True,
                    "ref_mode": "fasta_gtf",
                    "ref_transcripts": _normalize_ref(transcripts_choice),
                    "ref_genome": _normalize_ref(genome_choice),
                    "ref_gtf": _normalize_ref(gtf_choice),
                }
            )

        ref_block = {
            "transcripts_fasta": _normalize_ref(_get_run_config().get("ref_transcripts", "")),
            "genome_fasta": _normalize_ref(_get_run_config().get("ref_genome", "")),
            "gtf": _normalize_ref(_get_run_config().get("ref_gtf", "")),
        }
        custom_ok, rows = _ref_status_table(mode, ref_block, "", "")
        df_rows = pd.DataFrame(rows)
        if not df_rows.empty:
            df_rows["status"] = df_rows["status"].map(
                {"present": t("status.present"), "missing": t("status.missing"), "invalid": t("status.invalid")}
            )
        st.dataframe(df_rows, width="stretch", hide_index=True)
        if not custom_ok:
            st.caption(t("msg.refs_download_needed"))

    current_ref_state = _ref_state_snapshot()
    prev_ref_state = st.session_state.get("last_ref_state")
    if prev_ref_state is not None and prev_ref_state != current_ref_state:
        ui_state.mark_user_edit()
    st.session_state.last_ref_state = current_ref_state

elif st.session_state.step == 3:
    st.subheader(t("label.advanced"))
    st.caption(t("step_desc.advanced"))
    rows_raw = _coerce_rows_raw(st.session_state.rows_raw)
    levels = _get_conditions(rows_raw)
    run_config = _get_run_config()
    engine = normalize_engine(run_config.get("engine"))
    draft_eligibility = evaluate_analysis_eligibility(rows_raw)
    contrast_allowed = draft_eligibility.contrast_allowed
    st.markdown(f"**{t('analysis.mode.heading')}**")
    st.write(t(f"analysis.mode.{draft_eligibility.mode}"))
    if draft_eligibility.mode == "qc_only":
        st.caption(t(f"analysis.reason.{draft_eligibility.reason_code}"))
        st.caption(
            t(
                "analysis.condition_counts",
                counts=ui_samples.format_condition_counts(draft_eligibility.condition_counts),
            )
        )
        st.caption(t("analysis.settings_retained"))
    st.markdown(f"**{t('label.contrast_block')}**")
    st.caption(t("info.contrast_intro"))
    st.write(t("label.condition_levels", levels=", ".join(levels) if levels else t("label.none")))
    advanced = _advanced_state()
    contrast_mode_options = ["ref", "pairwise", "select", "legacy"]
    contrast_mode_key = f"{page_key}:contrast_mode"
    _seed_widget_state(contrast_mode_key, advanced.get("contrast_mode", "ref"))
    contrast_mode = st.selectbox(
        t("label.contrast_mode"),
        contrast_mode_options,
        index=contrast_mode_options.index(st.session_state[contrast_mode_key]) if st.session_state.get(contrast_mode_key) in contrast_mode_options else 0,
        key=contrast_mode_key,
        format_func=lambda v: t(f"label.contrast_mode.{v}"),
        disabled=not contrast_allowed,
    )
    _set_advanced_values(contrast_mode=contrast_mode)
    st.caption(t(f"desc.contrast_mode.{contrast_mode}"))
    contrast_pairs = list(_advanced_value("contrast_pairs") or [])

    if contrast_mode == "ref":
        contrast_ref_key = f"{page_key}:contrast_ref"
        contrast_ref_value = advanced.get("contrast_ref") or (levels[0] if levels else "")
        _seed_widget_state(contrast_ref_key, contrast_ref_value)
        st.selectbox(
            t("label.reference_condition"),
            levels,
            index=levels.index(st.session_state[contrast_ref_key]) if levels and st.session_state.get(contrast_ref_key) in levels else 0,
            key=contrast_ref_key,
            disabled=len(levels) == 0 or not contrast_allowed,
            help=t("analysis.contrast_disabled") if not contrast_allowed else None,
        )
        _set_advanced_values(contrast_ref=st.session_state.get(contrast_ref_key, ""))
    elif contrast_mode == "pairwise":
        pass
    elif contrast_mode == "select":
        col_left, col_right, col_add = st.columns([2, 2, 1])
        pair_left_key = f"{page_key}:pair_left"
        pair_right_key = f"{page_key}:pair_right"
        _seed_widget_state(pair_left_key, levels[0] if levels else "")
        _seed_widget_state(pair_right_key, levels[1] if len(levels) > 1 else (levels[0] if levels else ""))
        with col_left:
            left = st.selectbox("A", levels, key=pair_left_key, disabled=len(levels) == 0)
        with col_right:
            right = st.selectbox("B", levels, key=pair_right_key, disabled=len(levels) == 0)
        with col_add:
            if st.button(t("btn.add_pair"), disabled=not contrast_allowed):
                if left and right and left != right:
                    pair = [left, right]
                    if pair not in contrast_pairs:
                        contrast_pairs.append(pair)
                        _set_advanced_values(contrast_pairs=contrast_pairs)
        if contrast_pairs:
            st.write(t("label.selected_pairs"))
            for idx, pair in enumerate(contrast_pairs):
                cols = st.columns([4, 1])
                cols[0].write(f"{pair[0]} vs {pair[1]}")
                if cols[1].button(t("btn.remove_pair"), key=f"pair_{idx}"):
                    _set_advanced_values(contrast_pairs=[item for pair_idx, item in enumerate(contrast_pairs) if pair_idx != idx])
    else:
        contrast_legacy_key = f"{page_key}:contrast_legacy"
        _seed_widget_state(contrast_legacy_key, advanced.get("contrast_legacy", ""))
        st.text_input(
            t("label.legacy_contrast"),
            key=contrast_legacy_key,
            disabled=not contrast_allowed,
        )
        _set_advanced_values(contrast_legacy=st.session_state.get(contrast_legacy_key, ""))

    st.markdown(f"**{t('label.advanced_block')}**")
    st.caption(t("info.advanced_block"))
    enrich_allowed, enrich_reason, _ = _enrichment_ui_status(rows_raw, engine)
    enrich_enable_key = f"{page_key}:enrich_enable"
    _seed_widget_state(enrich_enable_key, bool(_advanced_value("enrich_enable")))
    enable_enrich = st.checkbox(
        t("label.enable_enrichment"),
        key=enrich_enable_key,
        disabled=not enrich_allowed,
        help=enrich_reason or None,
    )
    if enrich_allowed:
        _set_advanced_values(enrich_enable=enable_enrich)
    if enrich_reason:
        st.caption(enrich_reason)
    if enable_enrich:
        enrich_methods_key = f"{page_key}:enrich_methods"
        enrich_alpha_key = f"{page_key}:enrich_alpha"
        enrich_lfc_key = f"{page_key}:enrich_lfc"
        enrich_top_key = f"{page_key}:enrich_top"
        enrich_rank_key = f"{page_key}:enrich_rank"
        _seed_widget_state(enrich_methods_key, advanced.get("enrich_methods", ["ORA", "GSEA"]))
        _seed_widget_state(enrich_alpha_key, float(advanced.get("enrich_alpha", 0.05)))
        _seed_widget_state(enrich_lfc_key, float(advanced.get("enrich_lfc", 0.0)))
        _seed_widget_state(enrich_top_key, int(advanced.get("enrich_top", 15)))
        _seed_widget_state(enrich_rank_key, advanced.get("enrich_rank", "stat"))
        methods = st.multiselect(t("label.enrich_methods"), ["ORA", "GSEA"], default=st.session_state[enrich_methods_key], key=enrich_methods_key)
        alpha = st.number_input(t("label.enrich_alpha"), min_value=0.0, max_value=1.0, value=float(st.session_state[enrich_alpha_key]), step=0.01, key=enrich_alpha_key)
        lfc = st.number_input(t("label.enrich_lfc"), value=float(st.session_state[enrich_lfc_key]), step=0.5, key=enrich_lfc_key)
        top_terms = st.number_input(t("label.enrich_top"), min_value=1, max_value=100, value=int(st.session_state[enrich_top_key]), step=1, key=enrich_top_key)
        rank_metric = st.selectbox(t("label.enrich_rank"), ["stat"], index=0, key=enrich_rank_key)
        _set_advanced_values(
            enrich_methods=methods,
            enrich_alpha=alpha,
            enrich_lfc=lfc,
            enrich_top=top_terms,
            enrich_rank=rank_metric,
        )

else:
    st.subheader(t("summary.title"))
    st.caption(t("step_desc.summary"))
    rows_raw = _coerce_rows_raw(st.session_state.rows_raw)
    analysis_eligibility = evaluate_analysis_eligibility(rows_raw)
    analysis_plan = (
        analysis_eligibility.to_plan()
        if analysis_eligibility.structurally_valid
        else None
    )
    conditions = _get_conditions(rows_raw)
    advanced = _advanced_state()
    contrast_mode = advanced.get("contrast_mode", "ref")
    contrast_ref = advanced.get("contrast_ref") or (conditions[0] if conditions else "")
    contrast_pairs = list(advanced.get("contrast_pairs", []))
    legacy_raw = advanced.get("contrast_legacy", "")
    legacy_list = [item.strip() for item in legacy_raw.split(",") if item.strip()]

    contrasts = []
    if analysis_eligibility.eligible_for_de and contrast_mode == "ref" and contrast_ref:
        for lvl in conditions:
            if lvl != contrast_ref:
                contrasts.append(f"{lvl}_vs_{contrast_ref}")
    elif analysis_eligibility.eligible_for_de and contrast_mode == "pairwise":
        for i in range(len(conditions)):
            for j in range(i + 1, len(conditions)):
                contrasts.append(f"{conditions[i]}_vs_{conditions[j]}")
    elif analysis_eligibility.eligible_for_de and contrast_mode == "select":
        for a, b in contrast_pairs:
            contrasts.append(f"{a}_vs_{b}")
    elif analysis_eligibility.eligible_for_de and contrast_mode == "legacy":
        contrasts = legacy_list

    run_config = _get_run_config()
    use_custom_refs = bool(run_config.get("use_custom_refs", False))
    ref_mode = run_config.get("ref_mode", "preset_cache" if not use_custom_refs else "fasta_gtf")
    resolved_species = _resolve_species()
    if not resolved_species:
        st.error(t("error.species_missing"))
        st.stop()
    if resolved_species not in ALLOWED_SPECIES:
        st.error(t("error.species_invalid", value=resolved_species))
        st.stop()
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])
    ref_transcripts = _normalize_ref(run_config.get("ref_transcripts", ""))
    ref_genome = _normalize_ref(run_config.get("ref_genome", ""))
    ref_gtf = _normalize_ref(run_config.get("ref_gtf", ""))
    ref_block = {}
    ref_block_payload = {}
    reference_provenance = None
    ref_preset = None
    ref_release = run_config.get("ref_release") or "pinned"
    if ref_mode == "preset_cache":
        requested_preset = (
            run_config.get("_requested_ref_preset")
            or run_config.get("ref_preset", "")
        )
        requested_release = (
            run_config.get("_requested_ref_release")
            or run_config.get("ref_release")
        )
        manifest = _load_ref_manifest()
        ref_preset, ref_release = ui_refs.resolve_preset_release(
            manifest, run_config.get("ref_preset", ""), ref_release
        )
        cache_resolution = ui_refs.resolve_existing_cache_paths(
            manifest, _ref_cache_root(), requested_preset, requested_release
        )
        if cache_resolution:
            cache_paths = cache_resolution["paths"]
            ref_block_payload = {
                "transcripts_fasta": str(cache_paths["transcripts_fasta_url"]),
                "genome_fasta": str(cache_paths["genome_fasta_url"]),
                "gtf": str(cache_paths["gtf_url"]),
            }
            checksum_verified = bool(cache_resolution["verified"])
            cache_source = cache_resolution["cache_source"]
        else:
            expected = _cache_ref_paths(ref_preset, ref_release)
            ref_block_payload = {key: str(value) for key, value in expected.items()}
            checksum_verified = False
            cache_source = "canonical"
        reference_provenance = ui_refs.build_reference_provenance(
            manifest,
            requested_preset,
            requested_release,
            paths=ref_block_payload,
            checksum_verified=checksum_verified,
            cache_source=cache_source,
        )
        ref_block = {}
    elif ref_mode == "transcripts_only":
        ref_block["transcripts_fasta"] = ref_transcripts
    else:
        ref_block["transcripts_fasta"] = ref_transcripts
        ref_block["genome_fasta"] = ref_genome
        ref_block["gtf"] = ref_gtf
    ref_block = _prune_empty(ref_block)
    if ref_mode != "preset_cache":
        ref_block_payload = dict(ref_block)
        reference_provenance = ui_refs.build_custom_reference_provenance(
            resolved_species, ref_block_payload
        )
    ref_block_payload = _prune_empty(ref_block_payload)

    engine = normalize_engine(run_config.get("engine"))
    enrich_allowed, enrich_reason, _ = _enrichment_ui_status(rows_raw, engine)
    requested_analysis_options = None
    if analysis_plan and not analysis_eligibility.eligible_for_de:
        requested_analysis_options = {
            "contrast_mode": contrast_mode,
            "contrast_ref": contrast_ref,
            "contrast_pairs": contrast_pairs,
            "contrasts": legacy_list,
            "enrichment": {
                "enable": bool(advanced.get("enrich_enable")),
                "methods": advanced.get("enrich_methods", ["ORA", "GSEA"]),
                "alpha": float(advanced.get("enrich_alpha", 0.05)),
                "lfc": float(advanced.get("enrich_lfc", 0.0)),
                "top_terms": int(advanced.get("enrich_top", 15)),
                "rank_metric": advanced.get("enrich_rank", "stat"),
            },
        }
    payload = build_config_payload(
        project_name=str(run_config.get("project_name") or _default_project_name()),
        engine=engine,
        species=resolved_species,
        library_protocol=str(run_config.get("library_protocol") or ""),
        samples=[row.get("sample", "") for row in rows_raw if row.get("sample")],
        input_root=str(INPUT_ROOT),
        output_root=str(OUTPUT_ROOT),
        sample_table=str(_ui_session_samples_path()),
        threads=int(run_config.get("threads") or 1),
        ref_mode=ref_mode,
        ref_block=ref_block_payload,
        ref_preset=ref_preset or "",
        ref_release=ref_release,
        ref_cache_dir=str(_ref_cache_root()) if ref_preset else "",
        use_custom_refs=use_custom_refs,
        contrast_mode=contrast_mode if analysis_eligibility.eligible_for_de else "",
        contrast_ref=contrast_ref if analysis_eligibility.eligible_for_de else "",
        contrast_pairs=contrast_pairs if analysis_eligibility.eligible_for_de else [],
        contrasts=contrasts,
        enrichment={
            "enable": True,
            "methods": advanced.get("enrich_methods", ["ORA", "GSEA"]),
            "alpha": float(advanced.get("enrich_alpha", 0.05)),
            "lfc": float(advanced.get("enrich_lfc", 0.0)),
            "top_terms": int(advanced.get("enrich_top", 15)),
            "rank_metric": advanced.get("enrich_rank", "stat"),
        } if advanced.get("enrich_enable") and enrich_allowed else None,
        reference_provenance=reference_provenance,
        analysis_plan=analysis_plan,
        requested_analysis_options=requested_analysis_options,
    )
    payload = _prune_empty(payload)
    manifest_config_payload = dict(payload)
    manifest_config_payload["paired"] = bool(st.session_state.paired)
    manifest_config_payload["selected_subdirs"] = list(run_config.get("selected_subdirs") or [])

    lang = st.session_state.get("lang", "en")
    sample_header = ["sample", "condition", "fastq1"] + (["fastq2"] if st.session_state.paired else [])
    samples_preview = "\t".join(sample_header) + "\n" + "\n".join(
        ["\t".join([row.get(k, "") for k in sample_header]) for row in rows_raw]
    )

    if st.session_state.get("run_status") == "running":
        _poll_run_process()

    diagnostics = {"ok": True, "errors": [], "warnings": []}
    fastq_rel = st.session_state.fastq_rel
    try:
        if not rows_raw:
            diagnostics["errors"].append(t("invalid.samples_missing"))
        if engine not in ("real", "stub"):
            diagnostics["errors"].append(t("invalid.engine_invalid"))
        if run_config.get("library_protocol") not in (*NEW_LIBRARY_PROTOCOLS, LEGACY_UNSPECIFIED):
            diagnostics["errors"].append(t("invalid.library_protocol"))
        if engine == "real":
            if analysis_eligibility.eligible_for_de and contrast_mode == "ref" and (not contrast_ref or contrast_ref not in conditions):
                diagnostics["errors"].append(t("invalid.contrast_ref"))
            if analysis_eligibility.eligible_for_de and contrast_mode == "select":
                for a, b in contrast_pairs:
                    if a not in conditions or b not in conditions:
                        diagnostics["errors"].append(t("invalid.contrast_pair", a=a, b=b))
            if analysis_eligibility.eligible_for_de and contrast_mode == "legacy":
                for item in legacy_list:
                    if "_vs_" in item:
                        a, b = item.split("_vs_", 1)
                        if a not in conditions or b not in conditions:
                            diagnostics["errors"].append(t("invalid.contrast_legacy", item=item))

        row_report = _validate_rows_report(rows_raw, fastq_rel, st.session_state.paired)
        diagnostics["errors"].extend(row_report.get("errors") or [])
        diagnostics["warnings"].extend(row_report.get("warnings") or [])

        manifest = _load_ref_manifest()
        if ref_mode == "preset_cache" and ref_preset:
            try:
                metadata = ui_refs.get_preset_metadata(manifest, ref_preset)
                if metadata.get("species") != resolved_species:
                    diagnostics["errors"].append(t("invalid.ref_preset_species_mismatch", preset=ref_preset, species=resolved_species))
            except ui_refs.ReferencePresetError:
                diagnostics["errors"].append(t("invalid.ref_preset_unknown", preset=ref_preset))

        if engine == "real":
            ref_errors, ref_missing = _validate_refs(ref_mode, ref_block, st.session_state.refs_rel, ref_preset, ref_release)
            if ref_errors:
                if ref_missing:
                    st.error(t("error.ref_not_selected"))
                    st.warning("\n".join(_t_lines("msg.refs_missing")))
                fasta_rel = st.session_state.refs_rel.get("fasta", [])
                gtf_rel = st.session_state.refs_rel.get("gtf", [])
                candidates_info = f"FASTA candidates: {len(fasta_rel)}, GTF candidates: {len(gtf_rel)}"
                diagnostics["errors"].extend(ref_errors)
                st.error(
                    t(
                        "error.reference_issues",
                        details="\n".join(sorted(set(ref_errors))),
                        candidates_info=candidates_info,
                    )
                )
    except Exception as exc:
        msg = f"Internal error: {exc.__class__.__name__}: {exc}"
        diagnostics["errors"].append(msg)
        _log_ui_event("summary_precheck_error", {"error": msg})
    diagnostics["ok"] = len(diagnostics["errors"]) == 0
    invalid = list(diagnostics["errors"])
    if invalid:
        st.error(t("error.save_disabled"))
        st.write("\n".join(map(str, invalid)))
        st.warning(t("warn.fix_issues_enable_save"))
        if st.button(t("btn.go_reference")):
            _set_step(2, trigger="go_reference")

    config_path, samples_path, config_ok, samples_ok = _check_saved_outputs()
    output_write_ok, output_write_detail = _output_write_test()
    saved_species = ""
    if config_ok:
        saved_cfg = _load_yaml(config_path)
        saved_species = (saved_cfg.get("species") or "").strip().lower()

    manifest_payload = _build_manifest_payload(manifest_config_payload, rows_raw, fastq_rel)
    run_id = _manifest_run_id(manifest_payload)
    st.session_state.run_id = run_id
    run_dirname = build_run_dirname(run_config, run_id)
    run_dir = _run_dir_for_id(run_id)
    run_manifest_path = run_dir / "run" / "manifest.json"
    run_local_config_path = run_dir / "run" / "config_resolved.yaml"
    existing_report_path = run_dir / "report" / "report.html"
    run_exists = run_manifest_path.exists() or run_local_config_path.exists() or run_dir.exists()
    has_frozen_run = run_local_config_path.exists()
    has_existing_report = run_exists and existing_report_path.exists()
    frozen_analysis = (
        ui_run.assess_frozen_analysis_plan(run_local_config_path)
        if has_frozen_run
        else {"resume_allowed": True, "legacy": False, "error": ""}
    )
    run_options = ui_run.available_run_modes(
        run_exists=run_exists,
        has_frozen_run=has_frozen_run,
        has_report=has_existing_report,
        resume_allowed=bool(frozen_analysis.get("resume_allowed", True)),
    )
    if st.session_state.run_mode not in run_options:
        if has_existing_report:
            st.session_state.run_mode = "open_existing"
        elif has_frozen_run:
            st.session_state.run_mode = "resume"
        else:
            st.session_state.run_mode = "start_new"
    try:
        display_run_dir = run_dir.relative_to(OUTPUT_ROOT)
    except ValueError:
        display_run_dir = run_dir

    common_disable_errors = _sanitize_disable_reasons(invalid, rows_raw, st.session_state.paired)

    validation_state = st.session_state.get("validation", {}) if isinstance(st.session_state.get("validation", {}), dict) else {}
    validation_ok = bool(validation_state.get("ok", st.session_state.get("validation_ok")))
    validation_ready = validation_ok and not st.session_state.get("run_config_touched")
    validation_detail = (validation_state.get("detail") or "").strip()
    validation_traceback = (validation_state.get("traceback") or "").strip()
    naming_issue = _check_fastp_output_naming(run_dir if run_dir.exists() else OUTPUT_ROOT, st.session_state.paired)
    run_blockers = _compute_blockers(
        common_disable_errors=common_disable_errors,
        naming_issue=naming_issue,
        config_ok=config_ok,
        saved_species=saved_species,
        resolved_species=resolved_species,
        samples_ok=samples_ok,
        fastq_count=len(fastq_rel),
        output_write_ok=output_write_ok,
        validation_state=validation_state,
        run_config_touched=st.session_state.get("run_config_touched"),
    )

    with st.expander(t("summary.overview.title", lang=lang), expanded=False):
        st.caption(t("summary.overview.desc", lang=lang))
        st.caption(f"{t('summary.run_id', lang=lang)}: {run_id}")
        st.caption(f"{t('summary.run_dirname', lang=lang)}: {run_dirname}")
        st.caption(t("info.run_dir", path=display_run_dir))
        st.caption(t("info.resolved_species", species=resolved_species))
        st.text_area(t("summary.config_preview", lang=lang), yaml.safe_dump(payload, sort_keys=False), height=220, disabled=True)
        st.text_area(t("summary.samples_preview", lang=lang), samples_preview, height=220, disabled=True)

    st.markdown(f"**{t('analysis.mode.heading')}**")
    st.write(t(f"analysis.mode.{analysis_eligibility.mode}"))
    protocol_label_key = f"label.library_protocol.{run_config.get('library_protocol') or 'unselected'}"
    st.caption(
        f"{t('label.library_protocol')}: "
        f"{t(protocol_label_key)}"
    )
    st.caption(
        t(
            "analysis.condition_counts",
            counts=ui_samples.format_condition_counts(analysis_eligibility.condition_counts)
            or t("label.none"),
        )
    )
    if analysis_eligibility.mode == "qc_only":
        st.info(t(f"analysis.reason.{analysis_eligibility.reason_code}"))
        st.caption(t("analysis.minimum_limitation"))

    with st.expander(t("summary.options_precheck.title", lang=lang), expanded=False):
        st.caption(t("summary.options_precheck.desc", lang=lang))
        st.radio(
            t("summary.run_behavior.label", lang=lang),
            options=run_options,
            key="run_mode",
            format_func=lambda v: {
                "start_new": t("summary.run_behavior.start_new", lang=lang),
                "open_existing": t("summary.run_behavior.open_existing", lang=lang),
                "resume": t("summary.run_behavior.resume", lang=lang),
            }[v],
            horizontal=True,
        )
        st.checkbox(
            t("label.auto_recover"),
            key="auto_recover",
            value=True,
            help=t("help.auto_recover"),
        )
        st.checkbox(
            t("label.rerun_incomplete"),
            key="rerun_incomplete",
            help=t("help.rerun_incomplete"),
        )
        st.caption(
            t(
                "label.run_precheck",
                config_ok=config_ok,
                samples_ok=samples_ok,
                fastq_count=len(fastq_rel),
                output_writable=output_write_ok,
            )
        )
        if config_ok:
            st.caption(t("label.saved_species", species=saved_species or "-"))
            stat = config_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone(JST).strftime("%Y-%m-%d %H:%M:%S %Z")
            st.caption(t("label.config_stat", path=_public_path(config_path), size=stat.st_size, mtime=mtime))
        if run_exists and not has_existing_report and has_frozen_run:
            st.caption(t("msg.open_existing_unavailable"))
            st.caption(t("msg.inspect_logs_resume"))
        if frozen_analysis.get("legacy") and frozen_analysis.get("resume_allowed"):
            st.warning(t("analysis.legacy_eligible_warning"))
        if has_frozen_run and not frozen_analysis.get("resume_allowed", True):
            st.error(t("analysis.legacy_ineligible_block"))
        if output_write_detail and not output_write_ok:
            st.code(output_write_detail)

    st.markdown(f"**{t('summary.actions.title', lang=lang)}**")
    st.caption(t("summary.actions.desc", lang=lang))

    save_disabled = bool(invalid)
    validate_disabled = bool(invalid) or not config_ok
    legacy_resume_blocked = (
        run_exists
        and has_frozen_run
        and not bool(frozen_analysis.get("resume_allowed", True))
    )
    dry_run_disabled = not (validation_ready or has_frozen_run) or legacy_resume_blocked
    run_in_progress = st.session_state.get("run_status") == "running"
    open_existing_mode = st.session_state.run_mode == "open_existing"
    resume_mode = st.session_state.run_mode == "resume"
    run_disabled = (
        run_in_progress
        or (open_existing_mode and not has_existing_report)
        or (resume_mode and not has_frozen_run)
        or (legacy_resume_blocked and not open_existing_mode)
        or ((not validation_ready) and not open_existing_mode and not resume_mode)
    )
    op_cols = st.columns(4)
    with op_cols[0]:
        save_clicked = st.button(t("action.save.label", lang=lang), disabled=save_disabled, width="stretch")
        st.caption(t("action.save.desc", lang=lang))
    with op_cols[1]:
        validate_clicked = st.button(t("action.validate.label", lang=lang), disabled=validate_disabled, width="stretch")
        st.caption(t("action.validate.desc", lang=lang))
    with op_cols[2]:
        dryrun_clicked = st.button(t("action.trial.label", lang=lang), disabled=dry_run_disabled, width="stretch")
        st.caption(t("action.trial.desc", lang=lang))
    with op_cols[3]:
        run_clicked = st.button(t("action.run.label", lang=lang), disabled=run_disabled, width="stretch")
        st.caption(t("action.run.desc", lang=lang))

    if save_disabled and common_disable_errors:
        st.error(t("error.save_disabled"))
        for reason in common_disable_errors:
            st.markdown(f"- {reason}")
    if not validation_ready:
        st.warning(t("error.run_disabled"))
        if run_blockers:
            for reason in run_blockers:
                st.markdown(f"- {reason}")
        else:
            st.markdown(f"- {t('msg.validate_needs_save') if not config_ok else t('msg.validate_needs_fix')}")
        if validation_traceback and _dev_ui_enabled():
            with st.expander(t("label.validation_traceback")):
                st.code(validation_traceback)

    if save_clicked:
        try:
            rows_norm = _normalize_rows(
                rows_raw,
                st.session_state.paired,
                fastq_rel,
                st.session_state.autofill_conditions,
            )
            save_issues = _validate_rows(rows_norm, fastq_rel, st.session_state.paired)
            if save_issues:
                st.error(t("error.cannot_save_normalized"))
                _set_op_log("save", "error", "\n".join(save_issues), rc=1, set_active=True)
                with st.expander(t("summary.save_issues.title", lang=lang)):
                    st.code("\n".join(save_issues))
            else:
                payload_to_save = dict(payload)
                payload_to_save["samples"] = [row.get("sample", "") for row in rows_norm if row.get("sample")]
                payload_to_save["analysis_plan"] = analysis_plan_from_rows(rows_norm)
                _write_config_and_samples(payload_to_save, rows_norm, st.session_state.paired)
                config_path, samples_path, config_ok, samples_ok = _check_saved_outputs()
                st.code(_public_path(config_path))
                st.code(_public_path(samples_path))
                if config_ok and samples_ok:
                    st.session_state.saved = True
                    st.session_state.run_config_touched = False
                    ui_state.set_validation_pending(t("msg.validate_needs_save"))
                    ui_state.set_save_state(True)
                    _set_op_log(
                        "save",
                        "success",
                        f"{_public_path(config_path)}\n{_public_path(samples_path)}",
                        rc=0,
                        set_active=True,
                    )
                    st.success(t("success.saved_ok"))
                    saved_cfg = _load_yaml(config_path)
                    try:
                        _write_ui_state_json(_get_run_config())
                    except Exception:
                        pass
                    _log_ui_event(
                        "save_config",
                        {
                            "state": _run_config_snapshot(),
                            "config_path": str(config_path),
                            "saved_species": saved_cfg.get("species"),
                            "saved_ref_preset": saved_cfg.get("ref_preset"),
                            "saved_ref_release": saved_cfg.get("ref_release"),
                            "saved_ref": saved_cfg.get("ref"),
                        },
                    )
                else:
                    st.session_state.saved = False
                    missing = []
                    if not config_ok:
                        missing.append(str(config_path))
                    if not samples_ok:
                        missing.append(str(samples_path))
                    save_detail = t("error.save_failed_missing", missing=", ".join(missing))
                    ui_state.set_save_state(False, detail=save_detail)
                    _set_op_log("save", "error", ", ".join(missing), rc=1, set_active=True)
                    st.error(save_detail)
                    st.error(t("error.output_mount_wrong"))
        except Exception as exc:
            st.session_state.saved = False
            detail = f"Internal error: {exc.__class__.__name__}: {exc}"
            tb_text = traceback.format_exc()
            ui_state.set_save_state(False, detail=detail, traceback_text=tb_text)
            _set_op_log("save", "error", f"{detail}\n\n{tb_text}", rc=1, set_active=True)
            st.error(t("error.save_failed_generic"))
            if _dev_ui_enabled():
                with st.expander(t("label.debug_details")):
                    st.code(tb_text)
        entries = _list_output_dir()
        st.write(t("label.output_contents"))
        st.code("\n".join(entries) if entries else t("label.empty"))
    if save_disabled:
        st.caption(t("msg.save_disabled_short"))

    if validate_clicked:
        try:
            cmd = [
                "python",
                "-m",
                "app",
                "validate",
                "--config",
                str(config_path),
                "--input",
                str(INPUT_ROOT),
                "--output",
                str(OUTPUT_ROOT),
            ]
            cmd_text = "$ " + " ".join(cmd)
            code, output = _run_cmd_logged(cmd, st.session_state.get("run_id", ""), "validate_manual")
            _set_op_log(
                "validate",
                "success" if code == 0 else "error",
                f"{cmd_text}\n\n{output or t('label.no_output')}",
                rc=code,
                set_active=True,
            )
            if code == 0:
                naming_issue = _check_fastp_output_naming(run_dir if run_dir.exists() else OUTPUT_ROOT, st.session_state.paired)
                if naming_issue:
                    detail = t("warn.fastp_naming_mismatch")
                    ui_state.set_validation_state(False, detail=detail)
                    st.warning(detail)
                else:
                    ui_state.set_validation_state(True)
                    st.session_state.pop("validation_failed", None)
                    st.session_state.pop("validation_failed_detail", None)
                    if isinstance(st.session_state.get("blockers"), list):
                        st.session_state["blockers"] = [
                            item for item in st.session_state["blockers"] if not str(item).startswith("validation_failed")
                        ]
                    st.success(t("success.validate_ok"))
                    st.rerun()
            else:
                detail = (output or "").strip() or "Validation failed (no detail). Check logs."
                ui_state.set_validation_state(False, detail=detail)
                st.error(t("error.validate_failed", code=code))
        except Exception as exc:
            detail = f"Internal error: {exc.__class__.__name__}: {exc}"
            tb_text = traceback.format_exc()
            ui_state.set_validation_state(False, detail=detail, traceback_text=tb_text)
            _set_op_log("validate", "error", f"{detail}\n\n{tb_text}", rc=1, set_active=True)
            st.error(t("error.validate_failed", code=1))
            if _dev_ui_enabled():
                with st.expander(t("label.debug_details")):
                    st.code(tb_text)
    if validate_disabled:
        msg = t("msg.validate_needs_save") if not config_ok else t("msg.validate_needs_fix")
        st.caption(msg)

    if dryrun_clicked:
        try:
            if run_exists:
                run_record = _load_run_record(run_dir)
                _apply_run_record(run_record, run_dir)
                cfg_path = Path(run_record.get("config_path"))
                dryrun_threads = int((run_record.get("config") or {}).get("threads") or 1)
            else:
                run_dir = _prepare_run_dir("start_new", run_dir, run_exists)
                session_cfg = _load_yaml(_ui_session_config_path())
                cfg_path = _write_run_config(run_dir, session_cfg or payload)
                _write_run_manifest(run_dir, run_id, manifest_payload)
                now_utc = datetime.now(timezone.utc)
                _write_run_metadata(
                    run_dir,
                    {
                        "created_at_utc": now_utc.isoformat(),
                        "created_at_jst": now_utc.astimezone(JST).strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "git_rev": _git_rev(),
                        "run_id": run_id,
                        "species": resolved_species,
                        "ref_preset": _get_run_config().get("ref_preset", ""),
                        "threads": int(run_config.get("threads") or 1),
                        "engine": engine,
                    },
                )
                dryrun_threads = int(run_config.get("threads") or 1)
            cmd = _build_snakemake_base_cmd(run_dir, cfg_path, dryrun_threads) + ["-n", "--", "report"]
            cmd_text = "$ " + " ".join(cmd)
            code, output = _run_cmd_logged(cmd, st.session_state.get("run_id", ""), "dry_run_manual")
            _set_op_log(
                "dryrun",
                "success" if code == 0 else "error",
                f"{cmd_text}\n\n{output or t('label.no_output')}",
                rc=code,
                set_active=True,
            )
            if code == 0:
                st.success(t("success.dryrun_ok"))
            else:
                st.error(t("error.dryrun_failed", code=code))
        except FileNotFoundError as exc:
            detail = str(exc)
            _set_op_log("dryrun", "error", detail, rc=1, set_active=True)
            st.error(t("error.recover_missing_config"))
            if _dev_ui_enabled():
                with st.expander(t("label.debug_details")):
                    st.code(detail)
    if run_clicked:
        st.session_state.run_guard = None
        st.session_state.auto_recover_incomplete = False
        st.session_state.auto_recover_cleanup = False
        if open_existing_mode and run_exists:
            try:
                run_record = _load_run_record(run_dir)
            except FileNotFoundError as exc:
                st.error(t("error.recover_missing_config"))
                if _dev_ui_enabled():
                    with st.expander(t("label.debug_details")):
                        st.code(str(exc))
                st.stop()
            _apply_run_record(run_record, run_dir)
            existing_report = run_dir / "report" / "report.html"
            st.session_state.run_dir = str(run_dir)
            st.session_state.run_config_path = str(run_record.get("config_path") or "")
            st.session_state.run_status = "success"
            st.session_state.run_rc = 0
            st.session_state.run_log = t("msg.open_existing_report")
            _set_op_log("run", "success", st.session_state.run_log, rc=0, set_active=True)
            st.rerun()

        run_dir = _prepare_run_dir(st.session_state.run_mode, run_dir, run_exists)
        if run_exists:
            try:
                run_record = _load_run_record(run_dir)
            except FileNotFoundError as exc:
                st.error(t("error.recover_missing_config"))
                if _dev_ui_enabled():
                    with st.expander(t("label.debug_details")):
                        st.code(str(exc))
                st.stop()
            _apply_run_record(run_record, run_dir)
            run_cfg = Path(run_record.get("config_path"))
            run_exec_cfg = run_record.get("config") if isinstance(run_record.get("config"), dict) else {}
        else:
            session_cfg = _load_yaml(_ui_session_config_path())
            run_cfg = _write_run_config(run_dir, session_cfg or payload)
            _write_run_manifest(run_dir, run_id, manifest_payload)
            now_utc = datetime.now(timezone.utc)
            metadata = {
                "created_at_utc": now_utc.isoformat(),
                "created_at_jst": now_utc.astimezone(JST).strftime("%Y-%m-%dT%H:%M:%S%z"),
                "git_rev": _git_rev(),
                "run_id": run_id,
                "species": resolved_species,
                "ref_preset": _get_run_config().get("ref_preset", ""),
                "threads": int(run_config.get("threads") or 1),
                "engine": engine,
            }
            _write_run_metadata(run_dir, metadata)
            run_exec_cfg = session_cfg or payload
        try:
            _write_ui_state_json(_get_run_config())
            effective = dict(_get_run_config())
            effective.update(
                {
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "config_path": str(run_cfg),
                }
            )
            _write_ui_effective_config(effective)
        except Exception:
            pass
        extra_args = []
        if st.session_state.run_mode == "resume" or st.session_state.get("rerun_incomplete"):
            extra_args.append("--rerun-incomplete")
        run_threads = int(run_exec_cfg.get("threads") or run_config.get("threads") or 1)
        guard = _pre_run_guard(run_dir, run_cfg, run_threads, run_id)
        if guard.get("status") == "incomplete":
            if st.session_state.get("auto_recover"):
                st.session_state.auto_recover_incomplete = True
                st.session_state.incomplete_files = guard.get("files", [])
                if "--rerun-incomplete" not in extra_args:
                    extra_args.append("--rerun-incomplete")
            else:
                st.session_state.run_guard = guard
                st.rerun()
        elif guard.get("status") in ("lock", "error"):
            st.session_state.run_guard = guard
            st.rerun()
        _start_run_report(
            run_threads,
            run_dir,
            run_cfg,
            extra_args,
        )
        _set_op_log("run", "running", "$ " + " ".join(st.session_state.get("run_cmd") or []), rc=None, set_active=True)
        st.rerun()
    op_labels = {
        "save": t("label.log_tab.save"),
        "validate": t("label.log_tab.validate"),
        "dryrun": t("label.log_tab.dryrun"),
        "run": t("label.log_tab.run"),
    }
    active_op = st.radio(
        t("summary.logs.title", lang=lang),
        options=["save", "validate", "dryrun", "run"],
        key="active_op",
        horizontal=True,
        format_func=lambda k: op_labels.get(k, k),
    )
    run_status = st.session_state.get("run_status", "idle")
    run_log_text = st.session_state.get("run_log", "")
    if run_status == "running":
        _set_op_log("run", "running", run_log_text or "running...", rc=None)
    elif run_status in ("success", "failed", "stopped"):
        _set_op_log("run", run_status, run_log_text or t("label.no_output"), rc=st.session_state.get("run_rc"))
    op_logs = st.session_state.get("op_logs", {})
    op_status = st.session_state.get("op_status", {})
    active_meta = op_status.get(active_op, {})
    st.caption(t("summary.logs.latest", lang=lang, ts=active_meta.get("ts", "-"), status=active_meta.get("status", "-")))
    current_display_run_dir = Path(st.session_state.run_dir) if st.session_state.get("run_dir") else None
    display_log_text = _public_text(op_logs.get(active_op) or t("label.no_output"), run_dir=current_display_run_dir, max_lines=12) or t("label.no_output")
    st.text_area(
        t("label.run_output"),
        value=display_log_text,
        height=300,
        disabled=True,
    )
    if _dev_ui_enabled() and (op_logs.get(active_op) or "").strip():
        with st.expander(t("label.debug_details")):
            st.text_area(t("label.run_output"), value=op_logs.get(active_op) or t("label.no_output"), height=220, disabled=True)
    if _dev_ui_enabled():
        dev_run_dir = Path(st.session_state.run_dir) if st.session_state.get("run_dir") else None
        dev_summary = ui_run.build_dev_summary(
            ui_session_id=str(st.session_state.get(ui_state.UI_SESSION_ID_SESSION_KEY) or ""),
            run_id=str(st.session_state.get("run_id") or ""),
            session_config_path=_ui_session_config_path(),
            run_dir=dev_run_dir,
            validation_state=st.session_state.get("validation", {}),
        )
        with st.expander(t("label.dev_session_summary")):
            st.json(dev_summary)
        with st.expander("Debug (dev only)"):
            st.write("validation")
            st.json(st.session_state.get("validation", {}))
            st.write("legacy keys")
            st.json(
                {
                    "validation_failed": st.session_state.get("validation_failed"),
                    "validation_failed_detail": st.session_state.get("validation_failed_detail"),
                    "validation_ok": st.session_state.get("validation_ok"),
                    "blockers": st.session_state.get("blockers"),
                }
            )
            st.write("compute_blockers")
            st.json(run_blockers)
            st.write("persisted ui_state raw")
            st.json(st.session_state.get("_persisted_ui_state_raw", {}))

    guard = st.session_state.get("run_guard")
    if guard:
        status = guard.get("status")
        out_text = guard.get("output", "")
        log_path = _extract_snakemake_log_path(out_text)
        if status == "lock":
            st.error(t("msg.guard.lock_title"))
            st.warning(t("msg.guard.lock_body"))
        elif status == "incomplete":
            st.error(t("msg.guard.incomplete_title"))
            st.warning(t("msg.guard.incomplete_body"))
            files = guard.get("files", [])
            if files:
                st.code("\n".join(files[:20]) + (f"\n... (+{len(files)-20})" if len(files) > 20 else ""))
        else:
            st.error(t("msg.guard.error_title"))
            st.warning(t("msg.guard.error_body"))
            if out_text:
                public_guard = _public_text(out_text, run_dir=run_dir, max_lines=3)
                if public_guard:
                    st.code(public_guard)
            st.caption(t("label.next_steps"))
            if run_dir and _dev_ui_enabled():
                st.code("\n".join(_failure_debug_commands(run_dir)))
            elif _dev_ui_enabled():
                st.code("snakemake -n ...\nsnakemake --rerun-incomplete ...\nsnakemake --unlock ...")
        if log_path:
            st.caption(t("label.snakemake_log", path=_public_path(log_path, run_dir=run_dir)))
        if _dev_ui_enabled():
            with st.expander(t("summary.guard_details.title", lang=lang)):
                st.text_area(t("label.dryrun_output"), out_text or t("label.no_output"), height=220)

    active_run_dir = Path(st.session_state.run_dir) if st.session_state.get("run_dir") else None
    active_run_threads = int(run_config.get("threads") or 1)
    if active_run_dir:
        try:
            active_run_record = _load_run_record(active_run_dir)
            active_run_threads = int((active_run_record.get("config") or {}).get("threads") or active_run_threads)
        except FileNotFoundError:
            active_run_record = None
    else:
        active_run_record = None
    report_path = (active_run_dir / "report" / "report.html") if active_run_dir else (OUTPUT_ROOT / "report" / "report.html")
    if run_status != "idle" or run_log_text:
        if st.session_state.get("run_cmd"):
            st.code("$ " + " ".join(st.session_state.run_cmd))
        if run_status == "running":
            st.info(t("status.run_running"))
            if st.button(t("btn.stop_run")):
                _stop_run_process()
                st.rerun()
        elif run_status == "success":
            st.success(t("status.run_success"))
        else:
            summary = summarize_error(run_log_text, {"run_status": run_status}, translate=t)
            lines = summary.get("lines") or _t_lines("msg.run_generic")
            failure = _summarize_failure(run_log_text)
            log_info = _snakemake_log_candidates(active_run_dir) if active_run_dir else {"primary": None, "candidates": []}
            if run_status == "stopped":
                st.warning(t("status.run_stopped", code=st.session_state.get("run_rc")))
                st.warning("\n".join(lines))
            else:
                st.error(t("status.run_failed", code=st.session_state.get("run_rc")))
                st.error("\n".join(lines))
            st.error(f"{t('label.cause')}: {failure['cause']}")
            st.warning(f"{t('label.action')}: {failure['action']}")
            primary = log_info.get("primary")
            if primary:
                st.caption(f"{t('label.primary_log')}: {_public_path(primary['path'], run_dir=active_run_dir)} ({_human(primary['size'])})")
            candidates = log_info.get("candidates") or []
            if candidates:
                preview = [f"{_public_path(item['path'], run_dir=active_run_dir)} ({_human(item['size'])})" for item in candidates[:10]]
                st.caption(t("label.additional_logs"))
                st.code("\n".join(preview))
            if active_run_dir and _dev_ui_enabled():
                st.caption(t("label.debug_commands"))
                st.code("\n".join(_failure_debug_commands(active_run_dir)))
            if _dev_ui_enabled():
                if st.session_state.get("run_cmd_path"):
                    st.caption(f"{t('label.command_file')}: {st.session_state.get('run_cmd_path')}")
                if st.session_state.get("run_version_path"):
                    st.caption(f"{t('label.snakemake_version_file')}: {st.session_state.get('run_version_path')}")
                if st.session_state.get("run_stdout_log_path"):
                    st.caption(f"{t('label.stdout_log')}: {st.session_state.get('run_stdout_log_path')}")
                if st.session_state.get("run_stderr_log_path"):
                    st.caption(f"{t('label.stderr_log')}: {st.session_state.get('run_stderr_log_path')}")

            if summary.get("key") == "msg.run.incomplete_files":
                incomplete_files = extract_incomplete_files(run_log_text) or []
                if st.session_state.get("auto_recover_incomplete") and not st.session_state.get("auto_recover_cleanup"):
                    cfg_path, cfg_error = _get_run_config_or_error(active_run_dir)
                    if cfg_path:
                        if incomplete_files:
                            cmd = [
                                "python",
                                "-m",
                                "snakemake",
                                "--directory",
                                str(ui_run.snakemake_workdir(str(active_run_dir))),
                                "-s",
                                "workflow/Snakefile",
                                "--configfile",
                                str(cfg_path),
                                "--config",
                                "input=/input",
                                f"output={active_run_dir}",
                                "--cleanup-metadata",
                                *incomplete_files,
                            ]
                            _run_cmd_logged(cmd, st.session_state.get("run_id", ""), "cleanup_metadata_auto")
                        st.session_state.auto_recover_cleanup = True
                        _start_run_report(
                            active_run_threads,
                            active_run_dir,
                            cfg_path,
                            ["--rerun-incomplete"],
                        )
                        st.rerun()
                    elif cfg_error:
                        st.error(t("error.recover_missing_config"))
                        if _dev_ui_enabled():
                            st.caption(cfg_error)
                st.warning(t("msg.incomplete_short"))
                if incomplete_files:
                    st.code("\n".join(incomplete_files[:20]) + (f"\n... (+{len(incomplete_files)-20})" if len(incomplete_files) > 20 else ""))
                st.caption(t("help.incomplete_recover"))

                if st.button(t("btn.rerun_incomplete")):
                    cfg_path, cfg_error = _get_run_config_or_error(active_run_dir)
                    if not cfg_path:
                        st.error(t("error.recover_missing_config"))
                        if cfg_error:
                            if _dev_ui_enabled():
                                st.caption(cfg_error)
                    else:
                        _start_run_report(
                            active_run_threads,
                            active_run_dir,
                            cfg_path,
                            ["--rerun-incomplete"],
                        )
                        st.rerun()

                if st.button(t("btn.clean_incomplete_continue")):
                    cfg_path, cfg_error = _get_run_config_or_error(active_run_dir)
                    if not cfg_path:
                        st.error(t("error.recover_missing_config"))
                        if cfg_error:
                            if _dev_ui_enabled():
                                st.caption(cfg_error)
                    else:
                        if incomplete_files:
                            cmd = [
                                "python",
                                "-m",
                                "snakemake",
                                "--directory",
                                str(ui_run.snakemake_workdir(str(active_run_dir))),
                                "-s",
                                "workflow/Snakefile",
                                "--configfile",
                                str(cfg_path),
                                "--config",
                                "input=/input",
                                f"output={active_run_dir}",
                                "--cleanup-metadata",
                                *incomplete_files,
                            ]
                            _run_cmd_logged(cmd, st.session_state.get("run_id", ""), "cleanup_metadata")
                        _start_run_report(
                            active_run_threads,
                            active_run_dir,
                            cfg_path,
                            ["--rerun-incomplete"],
                        )
                        st.rerun()

                if st.button(t("btn.show_fix_commands")):
                    st.session_state.show_fix_commands = True

                if st.session_state.get("show_fix_commands"):
                    cleanup_cmd = "snakemake --cleanup-metadata " + " ".join(incomplete_files) if incomplete_files else "snakemake --cleanup-metadata <files>"
                    rerun_cmd = "snakemake --rerun-incomplete"
                    st.code(cleanup_cmd + "\n" + rerun_cmd)

            if failure.get("kind") == "missing_input":
                st.caption(t("help.missinginput_recover"))
                if st.button(t("btn.rerun_from_fastp")):
                    cfg_path, cfg_error = _get_run_config_or_error(active_run_dir)
                    if not cfg_path:
                        st.error(t("error.recover_missing_config"))
                        if cfg_error:
                            if _dev_ui_enabled():
                                st.caption(cfg_error)
                    else:
                        _start_run_report(
                            active_run_threads,
                            active_run_dir,
                            cfg_path,
                            ["--forcerun", "fastp", "--rerun-incomplete"],
                        )
                        st.rerun()

        if run_status in ("success", "failed", "stopped") and active_run_dir:
            with st.expander(t("label.advanced")):
                st.caption(t("help.recover"))
                if st.button(t("btn.recover")):
                    cfg_path, cfg_error = _get_run_config_or_error(active_run_dir)
                    if not cfg_path:
                        st.error(t("error.recover_missing_config"))
                        if cfg_error:
                            if _dev_ui_enabled():
                                st.caption(cfg_error)
                    else:
                        code, output = _run_cmd_logged(
                            [
                                "python",
                                "-m",
                                "snakemake",
                                "--directory",
                                str(ui_run.snakemake_workdir(str(active_run_dir))),
                                "-s",
                                "workflow/Snakefile",
                                "--configfile",
                                str(cfg_path),
                                "--config",
                                "input=/input",
                                f"output={active_run_dir}",
                                "--unlock",
                            ],
                            st.session_state.get("run_id", ""),
                            "unlock_manual",
                        )
                        st.text_area(t("label.recover_output"), output or t("label.no_output"), height=180)
                        if code == 0:
                            st.success(t("success.recover_ok"))
                        else:
                            st.error(t("error.recover_failed", code=code))

        if run_status == "success":
            try:
                display_report_path = report_path.relative_to(OUTPUT_ROOT)
            except ValueError:
                display_report_path = report_path
            st.success(t("status.report_ready", path=display_report_path))
            if report_path.exists():
                if st.button(t("btn.check_report_selfcontained")):
                    code, output = _run_cmd(
                        [
                            "python",
                            "/app/scripts/check_report_selfcontained.py",
                            "--report",
                            str(report_path),
                        ]
                    )
                    st.text_area(t("label.selfcontained_output"), output or t("label.no_output"), height=180)
                    if code == 0:
                        st.success(t("success.selfcontained_ok"))
                    else:
                        st.error(t("error.selfcontained_failed", code=code))

    _persist_run_config()

    if st.session_state.get("run_status") == "running":
        time.sleep(0.5)
        st.rerun()
