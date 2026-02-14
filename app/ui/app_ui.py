import os
import re
import subprocess
import time
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st
import yaml

from app.ui.i18n import t
from app.ui.error_messages import extract_incomplete_files, summarize_error
from app.ui.config_builder import build_config_payload, normalize_engine, normalize_species
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
FASTQ_EXTS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")
RUN_LOG_MAX_CHARS = 200000
RUNS_ROOT = OUTPUT_ROOT / "data_out"
JST = timezone(timedelta(hours=9), name="JST")
ALLOWED_SPECIES = ("mouse", "rat", "human")
RUN_CONFIG_KEY = "run_config"
RUN_CONFIG_STORAGE_KEY = "rnaseq_pipeline.run_config.v1"


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
        if raw and raw != "max":
            try:
                normalized = _normalize_mem_bytes(int(raw))
                if normalized:
                    return normalized
            except ValueError:
                pass
    mem_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if mem_limit.exists():
        try:
            normalized = _normalize_mem_bytes(int(_read_first_line(mem_limit)))
            if normalized:
                return normalized
        except ValueError:
            pass
    return None


def _t_lines(key: str):
    text = t(key)
    return [line for line in text.splitlines() if line.strip()]


def _run_config_defaults():
    return {
        "input_dir": str(INPUT_ROOT),
        "output_dir": str(OUTPUT_ROOT),
        "sample_table": str(OUTPUT_ROOT / "metadata" / "samples.tsv"),
        "project_name": _default_project_name(),
        "species": "mouse",
        "threads": 1,
        "engine": "stub",
        "paired": False,
        "use_custom_refs": False,
        "ref_mode": "preset_cache",
        "ref_transcripts": "",
        "ref_genome": "",
        "ref_gtf": "",
        "ref_preset": "mouse_gencode",
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
        "mouse": "mouse_gencode",
        "human": "human_gencode",
        "rat": "rat_ensembl",
    }
    return mapping.get(normalize_species(species) or "", "mouse_gencode")


def _preset_matches_species(preset: str, species: str):
    preset_value = (preset or "").strip().lower()
    species_value = (species or "").strip().lower()
    return bool(preset_value and species_value and preset_value.startswith(species_value))


def _run_config_status():
    if st.session_state.get("validation_ok") and not st.session_state.get("run_config_touched"):
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
    ui_logging.log_ui_event(OUTPUT_ROOT, event, data)


def _log_debug(event: str, before: dict, after: dict):
    ui_logging.log_debug(OUTPUT_ROOT, event, before, after)


def _read_persisted_state(key: str) -> str:
    return ui_state.read_persisted_state(key)


def _write_persisted_state(key: str, value: str):
    ui_state.write_persisted_state(key, value)


def _get_run_config():
    if RUN_CONFIG_KEY not in st.session_state:
        st.session_state[RUN_CONFIG_KEY] = _run_config_defaults()
    return st.session_state[RUN_CONFIG_KEY]


def updateRunConfig(patch: dict):
    state = _get_run_config()
    before = dict(state)
    species_before = normalize_species(before.get("species")) or "mouse"
    state.update(patch or {})
    state["project_name"] = (str(state.get("project_name", "")).strip() or _default_project_name())
    state["species"] = normalize_species(state.get("species")) or "mouse"
    state["engine"] = normalize_engine(state.get("engine")) or "stub"
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


def _load_ui_state_json():
    path = OUTPUT_ROOT / "run" / "ui_state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_ui_state_json(state: dict):
    path = OUTPUT_ROOT / "run" / "ui_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _write_ui_effective_config(state: dict):
    path = OUTPUT_ROOT / "run" / "ui_effective_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _load_config_yaml():
    path = OUTPUT_ROOT / "config.yaml"
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
        _merge_run_config(
            state,
            {
                "species": saved_species,
                "engine": saved_cfg.get("engine"),
                "threads": saved_cfg.get("threads"),
                "use_custom_refs": use_custom_refs,
                "ref_mode": ref_mode,
                "ref_transcripts": ref_transcripts,
                "ref_genome": ref_genome,
                "ref_gtf": ref_gtf,
                "ref_preset": saved_cfg.get("ref_preset"),
                "ref_release": saved_cfg.get("ref_release"),
                "ref_cache_dir": saved_cfg.get("ref_cache_dir"),
            },
            overwrite=True,
        )
        source = "config.yaml"

    if saved_ui_state:
        _merge_run_config(state, saved_ui_state, overwrite=True)
        source = "ui_state.json"

    if stored:
        try:
            data = json.loads(stored)
            if isinstance(data, dict):
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
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item_clean = _prune_empty(item)
            if item_clean in ("", None, [], {}):
                continue
            cleaned[key] = item_clean
        return cleaned
    if isinstance(value, list):
        return [item for item in (_prune_empty(item) for item in value) if item not in ("", None, [], {})]
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
    condition = sample if condition_from_sample else ""
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
                errors.append(t("ref_error.file_not_found", key=key, val=path))
                has_missing = True
        return errors, has_missing
    if ref_mode == "fasta_gtf":
        for key in ("transcripts_fasta", "genome_fasta", "gtf"):
            val = _normalize_input_value(ref_block.get(key) or "")
            if not val:
                errors.append(t("ref_error.missing_key", key=key))
                has_missing = True
                continue
            if key == "gtf":
                if val not in gtf_rel and not _ref_exists(val):
                    errors.append(t("ref_error.file_not_found", key=key, val=val))
            else:
                if val not in fasta_rel and not _ref_exists(val):
                    errors.append(t("ref_error.file_not_found", key=key, val=val))
    elif ref_mode == "transcripts_only":
        val = _normalize_input_value(ref_block.get("transcripts_fasta") or "")
        if not val:
            errors.append(t("ref_error.missing_key", key="transcripts_fasta"))
            has_missing = True
        elif val not in fasta_rel and not _ref_exists(val):
            errors.append(t("ref_error.file_not_found", key="transcripts_fasta", val=val))
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
    return ui_samples.write_samples(OUTPUT_ROOT, rows, paired)


def _write_config(payload):
    output_dir = OUTPUT_ROOT
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "config.yaml"
    with out_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)
    return out_path


def _write_config_and_samples(payload, rows, paired):
    samples_path = _write_samples(rows, paired)
    config_path = _write_config(payload)
    return config_path, samples_path


def _check_saved_outputs():
    config_path = OUTPUT_ROOT / "config.yaml"
    samples_path = OUTPUT_ROOT / "metadata" / "samples.tsv"
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
    return [rel for rel in ui_refs.preset_releases(manifest or {}, preset) if rel != "pinned"] or ["pinned"]


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
    base = root / preset / release
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
    run_cfg = dict(base_cfg)
    run_cfg["output"] = str(run_dir)
    run_cfg["sample_table"] = str(OUTPUT_ROOT / "metadata" / "samples.tsv")
    cfg_path = run_dir / "run" / "config_resolved.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(run_cfg, sort_keys=False), encoding="utf-8")
    return cfg_path


def _run_cmd(cmd):
    return ui_run.run_cmd(cmd)


def _append_ui_command(cmd, work_id: str, label: str):
    ui_logging.append_ui_command(OUTPUT_ROOT, cmd, work_id, label)


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
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
    version_path.write_text(_snakemake_version_text() + "\n", encoding="utf-8")
    cmd = [
        "python",
        "-m",
        "snakemake",
        "--directory",
        str(run_dir),
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

lang_options = ["en", "ja"]
lang_index = 0 if st.session_state.lang == "en" else 1
st.sidebar.selectbox(t("sidebar.language"), lang_options, index=lang_index, key="lang")

if not st.session_state.refs_rel["fasta"] and not st.session_state.refs_rel["gtf"]:
    fasta, gtf = _scan_refs(INPUT_ROOT)
    st.session_state.refs_rel = {
        "fasta": [_rel(p) for p in fasta],
        "gtf": [_rel(p) for p in gtf],
    }

steps = ["Project", "Samples", "Reference files", "Advanced", "Summary"]
ss = st.session_state
ss.step = _clamp_step(int(ss.step))
ss.step_radio = ss.step

header_left, header_right = st.columns([3, 2])
with header_left:
    st.title("Harako-RNAseq Web UI")
    st.caption(t("info.subtitle_wizard"))
    run_cfg_header = _get_run_config()
    if "header_project_name" not in st.session_state:
        st.session_state.header_project_name = str(run_cfg_header.get("project_name") or _default_project_name())
    if st.session_state.header_project_name != str(run_cfg_header.get("project_name") or ""):
        st.session_state.header_project_name = str(run_cfg_header.get("project_name") or _default_project_name())
    project_name_input = st.text_input(
        "Project name",
        key="header_project_name",
    )
    if project_name_input != run_cfg_header.get("project_name", ""):
        updateRunConfig({"project_name": project_name_input})
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
            memory=_format_bytes(mem_limit),
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
    st.rerun()


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

    if st.session_state.paired:
        if st.button(t("btn.auto_pair")):
            paired_rows = _auto_pair(_coerce_rows_raw(st.session_state.rows_raw), fastq_rel)
            canonical_rows, canonical_warnings = _canonicalize_rows_after_autopair(paired_rows, fastq_rel)
            st.session_state.rows_raw = canonical_rows
            st.session_state.auto_pair_warnings = canonical_warnings
            ui_state.mark_user_edit()
    else:
        st.button(t("btn.auto_pair"), disabled=True)
        st.caption(t("info.auto_pair_disabled"))

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
    species_choices = [
        {"label": t("label.species_mouse_mm10"), "species": "mouse", "preset": "mouse_gencode_mm10"},
        {"label": t("label.species_mouse_mm39"), "species": "mouse", "preset": "mouse_gencode"},
        {"label": t("label.species_human_hg38"), "species": "human", "preset": "human_gencode"},
        {"label": t("label.species_rat_rn7"), "species": "rat", "preset": "rat_ensembl"},
    ]
    labels = [choice["label"] for choice in species_choices]
    run_config = _get_run_config()
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
            fetch_disabled = (cache_ok and not overwrite_refs) or (not preset_available)
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
    levels = _get_conditions(st.session_state.rows_raw)
    st.markdown(f"**{t('label.contrast_block')}**")
    st.caption(t("info.contrast_intro"))
    st.write(t("label.condition_levels", levels=", ".join(levels) if levels else t("label.none")))
    contrast_mode_options = ["ref", "pairwise", "select", "legacy"]
    contrast_mode = st.selectbox(
        t("label.contrast_mode"),
        contrast_mode_options,
        index=0,
        key="contrast_mode",
        format_func=lambda v: t(f"label.contrast_mode.{v}"),
    )
    st.caption(t(f"desc.contrast_mode.{contrast_mode}"))
    st.session_state.contrast_pairs = st.session_state.get("contrast_pairs", [])
    st.session_state.contrast_legacy = st.session_state.get("contrast_legacy", "")

    if contrast_mode == "ref":
        st.selectbox(
            t("label.reference_condition"),
            levels,
            index=0 if levels else 0,
            key="contrast_ref",
            disabled=len(levels) == 0,
        )
    elif contrast_mode == "pairwise":
        pass
    elif contrast_mode == "select":
        col_left, col_right, col_add = st.columns([2, 2, 1])
        with col_left:
            left = st.selectbox("A", levels, key="pair_left", disabled=len(levels) == 0)
        with col_right:
            right = st.selectbox("B", levels, key="pair_right", disabled=len(levels) == 0)
        with col_add:
            if st.button(t("btn.add_pair")):
                if left and right and left != right:
                    st.session_state.contrast_pairs.append([left, right])
        if st.session_state.contrast_pairs:
            st.write(t("label.selected_pairs"))
            for idx, pair in enumerate(st.session_state.contrast_pairs):
                cols = st.columns([4, 1])
                cols[0].write(f"{pair[0]} vs {pair[1]}")
                if cols[1].button(t("btn.remove_pair"), key=f"pair_{idx}"):
                    st.session_state.contrast_pairs.pop(idx)
                    st.rerun()
    else:
        st.text_input(t("label.legacy_contrast"), key="contrast_legacy")

    st.markdown(f"**{t('label.advanced_block')}**")
    st.caption(t("info.advanced_block"))
    enable_enrich = st.checkbox(t("label.enable_enrichment"), value=False, key="enrich_enable")
    if enable_enrich:
        methods = st.multiselect(t("label.enrich_methods"), ["ORA", "GSEA"], default=["ORA", "GSEA"], key="enrich_methods")
        alpha = st.number_input(t("label.enrich_alpha"), min_value=0.0, max_value=1.0, value=0.05, step=0.01, key="enrich_alpha")
        lfc = st.number_input(t("label.enrich_lfc"), value=0.0, step=0.5, key="enrich_lfc")
        top_terms = st.number_input(t("label.enrich_top"), min_value=1, max_value=100, value=15, step=1, key="enrich_top")
        rank_metric = st.selectbox(t("label.enrich_rank"), ["stat"], index=0, key="enrich_rank")

else:
    st.subheader(t("summary.title"))
    st.caption(t("step_desc.summary"))
    rows_raw = _coerce_rows_raw(st.session_state.rows_raw)
    conditions = _get_conditions(rows_raw)
    contrast_mode = st.session_state.get("contrast_mode", "ref")
    contrast_ref = st.session_state.get("contrast_ref", conditions[0] if conditions else "")
    contrast_pairs = st.session_state.get("contrast_pairs", [])
    legacy_raw = st.session_state.get("contrast_legacy", "")
    legacy_list = [item.strip() for item in legacy_raw.split(",") if item.strip()]

    contrasts = []
    if contrast_mode == "ref" and contrast_ref:
        for lvl in conditions:
            if lvl != contrast_ref:
                contrasts.append(f"{lvl}_vs_{contrast_ref}")
    elif contrast_mode == "pairwise":
        for i in range(len(conditions)):
            for j in range(i + 1, len(conditions)):
                contrasts.append(f"{conditions[i]}_vs_{conditions[j]}")
    elif contrast_mode == "select":
        for a, b in contrast_pairs:
            contrasts.append(f"{a}_vs_{b}")
    elif contrast_mode == "legacy":
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
    ref_preset = None
    ref_release = run_config.get("ref_release") or "pinned"
    if ref_mode == "preset_cache":
        ref_preset = run_config.get("ref_preset", "")
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
    ref_block_payload = _prune_empty(ref_block_payload)

    engine = normalize_engine(run_config.get("engine"))
    payload = build_config_payload(
        engine=engine,
        species=resolved_species,
        samples=[row.get("sample", "") for row in rows_raw if row.get("sample")],
        input_root=str(INPUT_ROOT),
        output_root=str(OUTPUT_ROOT),
        sample_table=str(OUTPUT_ROOT / "metadata" / "samples.tsv"),
        threads=int(run_config.get("threads") or 1),
        ref_mode=ref_mode,
        ref_block=ref_block_payload,
        ref_preset=ref_preset or "",
        ref_release=ref_release,
        ref_cache_dir=str(_ref_cache_root()) if ref_preset else "",
        use_custom_refs=use_custom_refs,
        contrast_mode=contrast_mode,
        contrast_ref=contrast_ref,
        contrast_pairs=contrast_pairs,
        contrasts=contrasts,
        enrichment={
            "enable": True,
            "methods": st.session_state.get("enrich_methods", ["ORA", "GSEA"]),
            "alpha": float(st.session_state.get("enrich_alpha", 0.05)),
            "lfc": float(st.session_state.get("enrich_lfc", 0.0)),
            "top_terms": int(st.session_state.get("enrich_top", 15)),
            "rank_metric": st.session_state.get("enrich_rank", "stat"),
        } if st.session_state.get("enrich_enable") else None,
    )
    payload = _prune_empty(payload)

    lang = st.session_state.get("lang", "en")
    sample_header = ["sample", "condition", "fastq1"] + (["fastq2"] if st.session_state.paired else [])
    samples_preview = "\t".join(sample_header) + "\n" + "\n".join(
        ["\t".join([row.get(k, "") for k in sample_header]) for row in rows_raw]
    )

    if st.session_state.get("run_status") == "running":
        _poll_run_process()

    diagnostics = {"ok": True, "errors": [], "warnings": []}
    fastq_rel = st.session_state.fastq_rel
    needs_two_conditions = engine == "real" and len(conditions) < 2
    try:
        if not rows_raw:
            diagnostics["errors"].append(t("invalid.samples_missing"))
        if engine not in ("real", "stub"):
            diagnostics["errors"].append(t("invalid.engine_invalid"))
        if engine == "real":
            if needs_two_conditions:
                diagnostics["errors"].append(t("invalid.engine_need_two_conditions"))
            if contrast_mode == "ref" and (not contrast_ref or contrast_ref not in conditions):
                diagnostics["errors"].append(t("invalid.contrast_ref"))
            if contrast_mode == "select":
                for a, b in contrast_pairs:
                    if a not in conditions or b not in conditions:
                        diagnostics["errors"].append(t("invalid.contrast_pair", a=a, b=b))
            if contrast_mode == "legacy":
                for item in legacy_list:
                    if "_vs_" in item:
                        a, b = item.split("_vs_", 1)
                        if a not in conditions or b not in conditions:
                            diagnostics["errors"].append(t("invalid.contrast_legacy", item=item))

        row_report = _validate_rows_report(rows_raw, fastq_rel, st.session_state.paired)
        diagnostics["errors"].extend(row_report.get("errors") or [])
        diagnostics["warnings"].extend(row_report.get("warnings") or [])

        if ref_preset and not str(ref_preset).lower().startswith(resolved_species):
            diagnostics["errors"].append(t("invalid.ref_preset_species_mismatch", preset=ref_preset, species=resolved_species))
        manifest = _load_ref_manifest()
        if ref_mode == "preset_cache" and ref_preset and ref_preset not in (manifest.get("presets") or {}):
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
    if needs_two_conditions:
        st.warning("\n".join(_t_lines("msg.engine_need_two_conditions")))
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

    manifest_payload = _build_manifest_payload(payload, rows_raw, fastq_rel)
    run_id = _manifest_run_id(manifest_payload)
    st.session_state.run_id = run_id
    run_dirname = build_run_dirname(run_config, run_id)
    run_dir = _run_dir_for_id(run_id)
    run_manifest_path = run_dir / "run" / "manifest.json"
    run_exists = run_manifest_path.exists() or run_dir.exists()

    run_options = ["start_new"] if not run_exists else ["open_existing", "resume"]
    if st.session_state.run_mode not in run_options:
        st.session_state.run_mode = "resume" if run_exists else "start_new"
    try:
        display_run_dir = run_dir.relative_to(OUTPUT_ROOT)
    except ValueError:
        display_run_dir = run_dir

    common_disable_errors = _sanitize_disable_reasons(invalid, rows_raw, st.session_state.paired)

    run_blockers = list(common_disable_errors)
    naming_issue = _check_fastp_output_naming(run_dir if run_dir.exists() else OUTPUT_ROOT, st.session_state.paired)
    if naming_issue:
        run_blockers.append(t("run_blocker.fastp_naming_mismatch"))
    if not config_ok:
        run_blockers.append(t("run_blocker.missing_config"))
    elif not saved_species:
        run_blockers.append(t("run_blocker.species_missing"))
    elif saved_species != resolved_species:
        run_blockers.append(t("run_blocker.species_mismatch", saved=saved_species, current=resolved_species))
    if not samples_ok:
        run_blockers.append(t("run_blocker.missing_samples_tsv"))
    if len(fastq_rel) == 0:
        run_blockers.append(t("run_blocker.no_fastq"))
    if not output_write_ok:
        run_blockers.append(t("run_blocker.output_not_writable"))

    with st.expander(t("summary.overview.title", lang=lang), expanded=False):
        st.caption(t("summary.overview.desc", lang=lang))
        st.caption(f"{t('summary.run_id', lang=lang)}: {run_id}")
        st.caption(f"{t('summary.run_dirname', lang=lang)}: {run_dirname}")
        st.caption(t("info.run_dir", path=display_run_dir))
        st.caption(t("info.resolved_species", species=resolved_species))
        st.text_area(t("summary.config_preview", lang=lang), yaml.safe_dump(payload, sort_keys=False), height=220, disabled=True)
        st.text_area(t("summary.samples_preview", lang=lang), samples_preview, height=220, disabled=True)

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
            st.caption(t("label.config_stat", path=str(config_path), size=stat.st_size, mtime=mtime))
        if output_write_detail and not output_write_ok:
            st.code(output_write_detail)

    st.markdown(f"**{t('summary.actions.title', lang=lang)}**")
    st.caption(t("summary.actions.desc", lang=lang))

    save_disabled = bool(invalid)
    validate_disabled = bool(invalid) or not config_ok
    dry_run_disabled = bool(run_blockers)
    run_in_progress = st.session_state.get("run_status") == "running"
    open_existing_mode = st.session_state.run_mode == "open_existing"
    run_disabled = run_in_progress or (bool(run_blockers) and not open_existing_mode) or (open_existing_mode and not run_exists)
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
        st.error("Save is disabled because:")
        for reason in common_disable_errors:
            st.markdown(f"- {reason}")
    if validate_disabled and not st.session_state.get("validation_ok") and common_disable_errors:
        st.warning("Validation is blocked because:")
        for reason in common_disable_errors:
            st.markdown(f"- {reason}")
    if dry_run_disabled and common_disable_errors:
        st.warning("Trial-run is blocked because:")
        for reason in common_disable_errors:
            st.markdown(f"- {reason}")

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
                _write_config_and_samples(payload_to_save, rows_norm, st.session_state.paired)
                config_path, samples_path, config_ok, samples_ok = _check_saved_outputs()
                st.code(_path_info(config_path))
                st.code(_path_info(samples_path))
                if config_ok and samples_ok:
                    st.session_state.saved = True
                    st.session_state.run_config_touched = False
                    st.session_state.validation_ok = False
                    _set_op_log(
                        "save",
                        "success",
                        f"{_path_info(config_path)}\n{_path_info(samples_path)}",
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
                    _set_op_log("save", "error", ", ".join(missing), rc=1, set_active=True)
                    st.error(t("error.save_failed_missing", missing=", ".join(missing)))
                    st.error(t("error.output_mount_wrong"))
        except Exception:
            st.session_state.saved = False
            _set_op_log("save", "error", "save failed", rc=1, set_active=True)
            st.error(t("error.save_failed_generic"))
        entries = _list_output_dir()
        st.write(t("label.output_contents"))
        st.code("\n".join(entries) if entries else t("label.empty"))
    if save_disabled:
        st.caption(t("msg.save_disabled_short"))

    if validate_clicked:
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
            st.session_state.validation_ok = True
            st.success(t("success.validate_ok"))
            naming_issue = _check_fastp_output_naming(run_dir if run_dir.exists() else OUTPUT_ROOT, st.session_state.paired)
            if naming_issue:
                st.session_state.validation_ok = False
                st.warning(t("warn.fastp_naming_mismatch"))
        else:
            st.session_state.validation_ok = False
            st.error(t("error.validate_failed", code=code))
    if validate_disabled:
        msg = t("msg.validate_needs_save") if not config_ok else t("msg.validate_needs_fix")
        st.caption(msg)

    if dryrun_clicked:
        cmd = _build_snakemake_base_cmd(run_dir, OUTPUT_ROOT / "config.yaml", 1) + ["-n", "--", "report"]
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
    if dry_run_disabled:
        st.caption(t("msg.dryrun_blocked"))

    if run_clicked:
        st.session_state.run_guard = None
        st.session_state.auto_recover_incomplete = False
        st.session_state.auto_recover_cleanup = False
        if open_existing_mode and run_exists:
            existing_report = run_dir / "report" / "report.html"
            st.session_state.run_dir = str(run_dir)
            if existing_report.exists():
                st.session_state.run_status = "success"
                st.session_state.run_rc = 0
                st.session_state.run_log = t("msg.open_existing_report")
                _set_op_log("run", "success", st.session_state.run_log, rc=0, set_active=True)
            else:
                st.session_state.run_status = "stopped"
                st.session_state.run_rc = 0
                st.session_state.run_log = f"{t('msg.open_existing_report')}\nreport missing: {existing_report}"
                _set_op_log("run", "stopped", st.session_state.run_log, rc=0, set_active=True)
            st.rerun()

        run_dir = _prepare_run_dir(st.session_state.run_mode, run_dir, run_exists)
        saved_cfg_path = OUTPUT_ROOT / "config.yaml"
        saved_cfg = _load_yaml(saved_cfg_path)
        run_cfg = _write_run_config(run_dir, saved_cfg or payload)
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
        run_cfg_path = saved_cfg_path if saved_cfg_path.exists() else run_cfg
        guard = _pre_run_guard(run_dir, run_cfg_path, int(run_config.get("threads") or 1), run_id)
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
            int(run_config.get("threads") or 1),
            run_dir,
            run_cfg_path,
            extra_args,
        )
        _set_op_log("run", "running", "$ " + " ".join(st.session_state.get("run_cmd") or []), rc=None, set_active=True)
        st.rerun()
    if run_disabled:
        st.caption(t("msg.run_blocked"))

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
    op_logs = st.session_state.get("op_logs", {})
    op_status = st.session_state.get("op_status", {})
    active_meta = op_status.get(active_op, {})
    st.caption(t("summary.logs.latest", lang=lang, ts=active_meta.get("ts", "-"), status=active_meta.get("status", "-")))
    st.text_area(
        t("label.run_output"),
        value=op_logs.get(active_op) or t("label.no_output"),
        height=300,
        disabled=True,
    )

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
                lines = [line for line in out_text.splitlines() if line.strip()][:3]
                if lines:
                    st.code("\n".join(lines))
            st.caption(t("label.next_steps"))
            if run_dir:
                st.code("\n".join(_failure_debug_commands(run_dir)))
            else:
                st.code("snakemake -n ...\nsnakemake --rerun-incomplete ...\nsnakemake --unlock ...")
        if log_path:
            st.caption(t("label.snakemake_log", path=log_path))
        with st.expander(t("summary.guard_details.title", lang=lang)):
            st.text_area(t("label.dryrun_output"), out_text or t("label.no_output"), height=220)

    if run_blockers and st.session_state.run_mode != "open_existing":
        st.error(t("error.run_disabled"))
        st.write("\n".join(sorted(set(run_blockers))))

    run_status = st.session_state.get("run_status", "idle")
    run_log_text = st.session_state.get("run_log", "")
    if run_status == "running":
        _set_op_log("run", "running", run_log_text or "running...", rc=None)
    elif run_status in ("success", "failed", "stopped"):
        _set_op_log("run", run_status, run_log_text or t("label.no_output"), rc=st.session_state.get("run_rc"))
    active_run_dir = Path(st.session_state.run_dir) if st.session_state.get("run_dir") else None
    report_path = (active_run_dir / "report" / "report.html") if active_run_dir else (OUTPUT_ROOT / "report" / "report.html")
    if run_status != "idle" or run_log_text:
        if st.session_state.get("run_cmd"):
            st.code("$ " + " ".join(st.session_state.run_cmd))
        if run_status == "running":
            st.info(t("status.run_running"))
            if st.button(t("btn.stop_run")):
                _stop_run_process()
                st.rerun()
            st.text_area(t("label.run_output_live"), run_log_text or t("label.no_output"), height=280)
        elif run_status == "success":
            st.success(t("status.run_success"))
            if run_log_text:
                with st.expander(t("summary.run_output_details.title", lang=lang)):
                    st.text_area(t("label.run_output"), run_log_text or t("label.no_output"), height=280)
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
            st.error(f"Cause: {failure['cause']}")
            st.warning(f"Action: {failure['action']}")
            if st.session_state.get("run_cmd_path"):
                st.caption(f"Command file: {st.session_state.get('run_cmd_path')}")
            if st.session_state.get("run_version_path"):
                st.caption(f"Snakemake version file: {st.session_state.get('run_version_path')}")
            if st.session_state.get("run_stdout_log_path"):
                st.caption(f"stdout log: {st.session_state.get('run_stdout_log_path')}")
            if st.session_state.get("run_stderr_log_path"):
                st.caption(f"stderr log: {st.session_state.get('run_stderr_log_path')}")
            primary = log_info.get("primary")
            if primary:
                st.caption(f"Most important log: {primary['path']} ({_human(primary['size'])})")
            candidates = log_info.get("candidates") or []
            if candidates:
                preview = [f"{item['path']} ({_human(item['size'])})" for item in candidates[:10]]
                st.caption("Related logs:")
                st.code("\n".join(preview))
            if active_run_dir:
                st.caption("Debug commands")
                st.code("\n".join(_failure_debug_commands(active_run_dir)))
            with st.expander(t("summary.run_output_details.title", lang=lang)):
                st.text_area(t("label.run_output"), run_log_text or t("label.no_output"), height=280)

            if summary.get("key") == "msg.run.incomplete_files":
                incomplete_files = extract_incomplete_files(run_log_text) or []
                if st.session_state.get("auto_recover_incomplete") and not st.session_state.get("auto_recover_cleanup"):
                    cfg_path = Path(st.session_state.get("run_config_path") or "") if st.session_state.get("run_config_path") else (active_run_dir / "run" / "config_resolved.yaml")
                    if cfg_path.exists():
                        if incomplete_files:
                            cmd = [
                                "python",
                                "-m",
                                "snakemake",
                                "--directory",
                                str(active_run_dir),
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
                            int(run_config.get("threads") or 1),
                            active_run_dir,
                            cfg_path,
                            ["--rerun-incomplete"],
                        )
                        st.rerun()
                st.warning(t("msg.incomplete_short"))
                if incomplete_files:
                    st.code("\n".join(incomplete_files[:20]) + (f"\n... (+{len(incomplete_files)-20})" if len(incomplete_files) > 20 else ""))
                st.caption(t("help.incomplete_recover"))

                if st.button(t("btn.rerun_incomplete")):
                    cfg_path = Path(st.session_state.get("run_config_path") or "") if st.session_state.get("run_config_path") else (active_run_dir / "run" / "config_resolved.yaml")
                    if not cfg_path.exists():
                        st.error(t("error.recover_missing_config"))
                    else:
                        _start_run_report(
                            int(run_config.get("threads") or 1),
                            active_run_dir,
                            cfg_path,
                            ["--rerun-incomplete"],
                        )
                        st.rerun()

                if st.button(t("btn.clean_incomplete_continue")):
                    cfg_path = Path(st.session_state.get("run_config_path") or "") if st.session_state.get("run_config_path") else (active_run_dir / "run" / "config_resolved.yaml")
                    if not cfg_path.exists():
                        st.error(t("error.recover_missing_config"))
                    else:
                        if incomplete_files:
                            cmd = [
                                "python",
                                "-m",
                                "snakemake",
                                "--directory",
                                str(active_run_dir),
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
                            int(run_config.get("threads") or 1),
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
                    cfg_path = Path(st.session_state.get("run_config_path") or "") if st.session_state.get("run_config_path") else (active_run_dir / "run" / "config_resolved.yaml")
                    if not cfg_path.exists():
                        st.error(t("error.recover_missing_config"))
                    else:
                        _start_run_report(
                            int(run_config.get("threads") or 1),
                            active_run_dir,
                            cfg_path,
                            ["--forcerun", "fastp", "--rerun-incomplete"],
                        )
                        st.rerun()

        if run_status in ("success", "failed", "stopped") and active_run_dir:
            with st.expander(t("label.advanced")):
                st.caption(t("help.recover"))
                if st.button(t("btn.recover")):
                    cfg_path = Path(st.session_state.get("run_config_path") or "") if st.session_state.get("run_config_path") else (active_run_dir / "run" / "config_resolved.yaml")
                    if not cfg_path.exists():
                        st.error(t("error.recover_missing_config"))
                    else:
                        code, output = _run_cmd_logged(
                            [
                                "python",
                                "-m",
                                "snakemake",
                                "--directory",
                                str(active_run_dir),
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
