import os
import re
import subprocess
import time
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st
import yaml

from app.ui.i18n import t
from app.ui.error_messages import extract_incomplete_files, summarize_error
from app.ui.config_builder import build_config_payload, normalize_engine, normalize_species

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


def _format_bytes(value: int):
    if value is None:
        return "-"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


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
                return int(raw)
            except ValueError:
                pass
    mem_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if mem_limit.exists():
        try:
            value = int(_read_first_line(mem_limit))
            if value > 0:
                return value
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
        "species": "mouse",
        "threads": 1,
        "engine": "stub",
        "paired": False,
        "ref_preset": "",
        "ref_release": "pinned",
        "ref_manifest": str(REF_MANIFEST_PATH),
        "ref_cache_dir": str(OUTPUT_ROOT / "refs_cache"),
    }


def _run_config_snapshot(state=None):
    state = state or st.session_state.get(RUN_CONFIG_KEY, {})
    return {
        "species": normalize_species(state.get("species")),
        "threads": int(state.get("threads") or 1),
        "engine": normalize_engine(state.get("engine")),
        "paired": bool(state.get("paired", False)),
        "ref_preset": state.get("ref_preset", ""),
        "ref_release": state.get("ref_release", ""),
    }


def _run_config_status():
    if st.session_state.get("validation_ok") and not st.session_state.get("run_config_touched"):
        return "ready"
    if st.session_state.get("saved") and not st.session_state.get("run_config_touched"):
        return "saved"
    return "draft"


def _ref_state_snapshot():
    return {
        "use_custom_refs": bool(st.session_state.get("use_custom_refs", False)),
        "ref_mode": st.session_state.get("ref_mode", ""),
        "ref_transcripts": st.session_state.get("ref_transcripts", ""),
        "ref_genome": st.session_state.get("ref_genome", ""),
        "ref_gtf": st.session_state.get("ref_gtf", ""),
        "ref_preset": _get_run_config().get("ref_preset", ""),
        "ref_release": _get_run_config().get("ref_release", ""),
    }


def _log_ui_event(event: str, data: dict):
    try:
        log_dir = OUTPUT_ROOT / "run"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "ui_events.log"
        payload = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        payload.update(data or {})
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def _log_debug(event: str, before: dict, after: dict):
    try:
        changed = sorted([k for k in set(before) | set(after) if before.get(k) != after.get(k)])
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "before": before,
            "after": after,
            "changed_keys": changed,
        }
        log_dir = OUTPUT_ROOT / "run"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "ui_debug.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False))
    except Exception:
        return


def _read_persisted_state(key: str) -> str:
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


def _write_persisted_state(key: str, value: str):
    try:
        st.query_params[key] = value
    except Exception:
        st.experimental_set_query_params(**{key: value})


def _get_run_config():
    if RUN_CONFIG_KEY not in st.session_state:
        st.session_state[RUN_CONFIG_KEY] = _run_config_defaults()
    return st.session_state[RUN_CONFIG_KEY]


def updateRunConfig(patch: dict):
    state = _get_run_config()
    before = dict(state)
    state.update(patch or {})
    state["species"] = normalize_species(state.get("species")) or "mouse"
    state["engine"] = normalize_engine(state.get("engine")) or "stub"
    state["paired"] = bool(state.get("paired", False))
    try:
        state["threads"] = max(1, int(str(state.get("threads")).strip()))
    except Exception:
        state["threads"] = 1
    after = dict(state)
    if before != after:
        st.session_state.run_config_touched = True
        st.session_state.validation_ok = False
        st.session_state.saved = False
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
    for key, value in (incoming or {}).items():
        if overwrite or base.get(key) in ("", None, [], {}):
            base[key] = value
    return base


def _restore_run_config():
    if st.session_state.get("run_config_loaded"):
        return
    state = _run_config_defaults()
    stored = _read_persisted_state(RUN_CONFIG_STORAGE_KEY)
    source = "default"
    saved_cfg = _load_config_yaml()
    saved_ui_state = _load_ui_state_json()

    if saved_cfg:
        _merge_run_config(
            state,
            {
                "species": saved_cfg.get("species"),
                "engine": saved_cfg.get("engine"),
                "threads": saved_cfg.get("threads"),
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
    payload = json.dumps(state, sort_keys=True)
    if payload != st.session_state.get("run_config_last_saved"):
        _write_persisted_state(RUN_CONFIG_STORAGE_KEY, payload)
        st.session_state.run_config_last_saved = payload


def _scan_fastq(root: Path):
    exts = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
    files = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and path.name.lower().endswith(exts):
                files.append(path)
    return sorted(files)


def _scan_input(root: Path):
    fastq_files = _scan_fastq(root)
    fastq_rel = [_rel(p) for p in fastq_files]
    fasta, gtf = _scan_refs(root)
    refs_rel = {
        "fasta": [_rel(p) for p in fasta],
        "gtf": [_rel(p) for p in gtf],
    }
    return fastq_rel, refs_rel


def _fastq_read_counts(fastq_rel):
    r1 = 0
    r2 = 0
    unknown = 0
    for fq in fastq_rel or []:
        side = _read_side(fq)
        if side == "1":
            r1 += 1
        elif side == "2":
            r2 += 1
        else:
            unknown += 1
    return {"r1": r1, "r2": r2, "unknown": unknown}


def _scan_refs(root: Path):
    fasta_exts = (".fa", ".fa.gz", ".fasta", ".fasta.gz")
    gtf_exts = (".gtf", ".gtf.gz")
    fasta = []
    gtf = []
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if name.endswith(fasta_exts):
                fasta.append(path)
            if name.endswith(gtf_exts):
                gtf.append(path)
    return sorted(fasta), sorted(gtf)


def _rel(path: Path):
    try:
        return str(path.relative_to(INPUT_ROOT))
    except ValueError:
        return str(path)


def _normalize_input_value(value: str):
    if not value:
        return ""
    return value.strip().replace("\\", "/")


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
    normalized = _normalize_input_value(path_value)
    path = Path(normalized)
    parent = path.parent.as_posix()
    if parent == ".":
        parent = ""
    filename = path.name
    lower = filename.lower()
    for ext in FASTQ_EXTS:
        if lower.endswith(ext):
            return parent, filename[:-len(ext)], filename[-len(ext):]
    stem, ext = os.path.splitext(filename)
    return parent, stem, ext


def _split_read_suffix(stem: str):
    match = re.match(r"(?i)^(?P<prefix>.+?)(?P<sep>[._-])(?P<tag>R?[12])$", stem)
    if match:
        prefix = match.group("prefix")
        tag = match.group("tag").upper()
        sep = match.group("sep")
        is_plain_numeric = (tag in ("1", "2")) and (sep in ("_", ".", "-"))
        if is_plain_numeric:
            # `_1/_2` style can mean replicate index; treat it as read suffix only
            # when it looks like a true read marker context.
            looks_like_accession = bool(re.match(r"(?i)^(SRR|ERR|DRR|GSM|SRS|SRX|SAMN|PRJ)", prefix))
            has_nested_delimiter = any(ch in prefix for ch in ("_", ".", "-"))
            if not (looks_like_accession or has_nested_delimiter):
                return stem, "", False, ""
        return (
            prefix,
            "1" if tag.endswith("1") else "2",
            bool(tag.startswith("R")),
            sep,
        )
    match = re.match(r"(?i)^(?P<prefix>.+?)(?P<tag>R[12])$", stem)
    if match:
        tag = match.group("tag").upper()
        return (match.group("prefix"), "1" if tag.endswith("1") else "2", True, "")
    return stem, "", False, ""


def _read_side(path_value: str):
    _, stem, _ = _split_fastq_name(path_value)
    _, read, _, _ = _split_read_suffix(stem)
    return read


def _is_r1(path_value: str):
    return _read_side(path_value) == "1"


def _sample_base(path_value: str):
    _, stem, _ = _split_fastq_name(path_value)
    prefix, read, _, _ = _split_read_suffix(stem)
    if read:
        return prefix
    return stem


def _join_path(parent: str, filename: str):
    if not parent:
        return filename
    return f"{parent}/{filename}"


def _infer_pair_candidates(name: str):
    parent, stem, ext = _split_fastq_name(name)
    prefix, read, has_r, sep = _split_read_suffix(stem)
    if not read:
        return []

    target_read = "2" if read == "1" else "1"
    token_order = [f"R{target_read}", target_read] if has_r else [target_read, f"R{target_read}"]
    separators = []
    if sep:
        separators.append(sep)
    for alt in ("_", ".", "-"):
        if alt not in separators:
            separators.append(alt)

    suffixes = []
    if not sep:
        suffixes.extend(token_order)
    for candidate_sep in separators:
        suffixes.extend([f"{candidate_sep}{token}" for token in token_order])

    candidates = []
    seen = set()
    for suffix in suffixes:
        candidate = _join_path(parent, f"{prefix}{suffix}{ext}")
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


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
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def _coerce_rows_raw(rows):
    normalized = []
    for row in rows or []:
        normalized.append(
            {
                "sample": _clean_cell(row.get("sample", "")),
                "condition": _clean_cell(row.get("condition", "")),
                "fastq1": _normalize_input_value(_clean_cell(row.get("fastq1", ""))),
                "fastq2": _normalize_input_value(_clean_cell(row.get("fastq2", ""))),
            }
        )
    return normalized


def _normalize_rows(rows_raw, paired: bool, fastq_rel, autofill_conditions: bool):
    available_set = set(fastq_rel)
    rows_norm = []
    for row in _coerce_rows_raw(rows_raw):
        fastq1 = row.get("fastq1", "")
        fastq2 = row.get("fastq2", "")
        sample = row.get("sample", "")
        condition = row.get("condition", "")

        if not sample and fastq1:
            sample = _sample_base(fastq1)
        if not condition and autofill_conditions and sample:
            condition = sample

        if paired and not fastq2 and fastq1:
            for candidate in _infer_pair_candidates(fastq1):
                if candidate in available_set:
                    fastq2 = candidate
                    break
        if not paired:
            fastq2 = ""

        rows_norm.append(
            {
                "sample": sample,
                "condition": condition,
                "fastq1": fastq1,
                "fastq2": fastq2,
            }
        )
    return rows_norm


def _sync_rows_raw_from_editor():
    state = st.session_state.get("samples_editor")
    previous_rows = _coerce_rows_raw(st.session_state.get("rows_raw", []))

    # Streamlit may provide either full table values or delta-style editor state.
    if isinstance(state, pd.DataFrame):
        st.session_state.rows_raw = _coerce_rows_raw(state.to_dict("records"))
        st.session_state.run_config_touched = True
        st.session_state.validation_ok = False
        return
    if isinstance(state, list):
        st.session_state.rows_raw = _coerce_rows_raw(state)
        st.session_state.run_config_touched = True
        st.session_state.validation_ok = False
        return
    if not isinstance(state, dict):
        return

    rows = [dict(row) for row in previous_rows]

    for idx in sorted(state.get("deleted_rows", []), reverse=True):
        try:
            rows.pop(int(idx))
        except (ValueError, IndexError, TypeError):
            continue

    edited_rows = state.get("edited_rows", {})
    if isinstance(edited_rows, dict):
        for idx, delta in edited_rows.items():
            try:
                row_idx = int(idx)
            except (ValueError, TypeError):
                continue
            if row_idx < 0 or row_idx >= len(rows) or not isinstance(delta, dict):
                continue
            rows[row_idx].update(delta)

    for added in state.get("added_rows", []):
        if isinstance(added, dict):
            rows.append(added)

    st.session_state.rows_raw = _coerce_rows_raw(rows)
    st.session_state.run_config_touched = True
    st.session_state.validation_ok = False


def _validate_rows(rows, fastq_rel, paired):
    issues = []
    seen = set()
    for idx, row in enumerate(rows, start=1):
        sample = _clean_cell(row.get("sample", ""))
        cond = _clean_cell(row.get("condition", ""))
        fq1 = _normalize_input_value(_clean_cell(row.get("fastq1", "")))
        fq2 = _normalize_input_value(_clean_cell(row.get("fastq2", "")))
        if not sample:
            issues.append(t("row_issue.sample_missing", row=idx))
        if sample in seen:
            issues.append(t("row_issue.duplicate_sample", row=idx, sample=sample))
        seen.add(sample)
        if not cond:
            issues.append(t("row_issue.condition_missing", row=idx))
        if not fq1:
            issues.append(t("row_issue.fastq1_missing", row=idx))
        elif fq1 not in fastq_rel and not _ref_exists(fq1):
            issues.append(t("row_issue.fastq1_not_found", row=idx, fastq=fq1))
        if paired:
            if not fq2:
                issues.append(t("row_issue.fastq2_missing", row=idx))
            elif fq2 not in fastq_rel and not _ref_exists(fq2):
                issues.append(t("row_issue.fastq2_not_found", row=idx, fastq=fq2))
    return issues


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


def _row_sample_key(row):
    sample = _clean_cell(row.get("sample", "")).strip()
    if sample:
        return f"sample:{sample}"
    fq_seed = _normalize_input_value(_clean_cell(row.get("fastq1", ""))) or _normalize_input_value(_clean_cell(row.get("fastq2", "")))
    if fq_seed:
        return f"derived:{_sample_base(fq_seed)}"
    return "derived:"


def _auto_pair(rows, available):
    available_set = set(available)
    rows_out = _coerce_rows_raw(rows)

    used_fastq2 = set()
    paired_sample_keys = set()
    for row in rows_out:
        fq2 = _normalize_input_value(_clean_cell(row.get("fastq2", "")))
        if fq2:
            used_fastq2.add(fq2)
        fq1 = _normalize_input_value(_clean_cell(row.get("fastq1", "")))
        if fq1 and fq2:
            paired_sample_keys.add(_row_sample_key(row))

    for row in rows_out:
        fq1 = _normalize_input_value(_clean_cell(row.get("fastq1", "")))
        fq2 = _normalize_input_value(_clean_cell(row.get("fastq2", "")))
        if not fq1:
            continue
        # Idempotent behavior: never touch rows that already have pair values.
        if fq2:
            continue
        # Do not force-pair rows that already point to read2.
        if _read_side(fq1) == "2":
            continue

        sample_key = _row_sample_key(row)
        if sample_key in paired_sample_keys:
            continue

        for candidate in _infer_pair_candidates(fq1):
            if candidate not in available_set or candidate == fq1:
                continue
            if candidate in used_fastq2:
                continue
            row["fastq2"] = candidate
            used_fastq2.add(candidate)
            paired_sample_keys.add(sample_key)
            break

    return rows_out


def _normalized_sample_key(value: str):
    return _clean_cell(value).strip()


def _derive_sample_from_fastq(path_value: str, fastq_pool):
    fq = _normalize_input_value(path_value)
    if not fq:
        return ""
    parent, stem, _ = _split_fastq_name(fq)
    read_side = _read_side(fq)
    if not read_side:
        return stem
    for mate in _infer_pair_candidates(fq):
        if mate in fastq_pool:
            return _split_read_suffix(stem)[0]
    return stem


def _row_fastq_candidates(rows):
    candidates = []
    seen = set()
    for row in rows:
        for key in ("fastq1", "fastq2"):
            fq = _normalize_input_value(_clean_cell(row.get(key, "")))
            if not fq or fq in seen:
                continue
            seen.add(fq)
            candidates.append(fq)
    return candidates


def _pick_preferred_fastq(candidates, preferred_read: str):
    preferred = []
    neutral = []
    other = []
    for fq in candidates:
        side = _read_side(fq)
        if side == preferred_read:
            preferred.append(fq)
        elif side == "":
            neutral.append(fq)
        else:
            other.append(fq)
    for bucket in (preferred, neutral, other):
        if bucket:
            return bucket[0]
    return ""


def _canonicalize_rows_after_autopair(rows, available=None):
    grouped = {}
    order = []
    warnings = []
    fastq_pool = set(available or [])
    for row in _coerce_rows_raw(rows):
        fq1 = _normalize_input_value(_clean_cell(row.get("fastq1", "")))
        fq2 = _normalize_input_value(_clean_cell(row.get("fastq2", "")))
        if fq1:
            fastq_pool.add(fq1)
        if fq2:
            fastq_pool.add(fq2)

    for idx, row in enumerate(_coerce_rows_raw(rows), start=1):
        sample_key = _normalized_sample_key(row.get("sample", ""))
        if not sample_key:
            seed = row.get("fastq1", "") or row.get("fastq2", "")
            sample_key = _derive_sample_from_fastq(seed, fastq_pool) if seed else f"__row_{idx}"
        if sample_key not in grouped:
            grouped[sample_key] = []
            order.append(sample_key)
        grouped[sample_key].append(row)

    canonical = []
    for sample_key in order:
        members = grouped[sample_key]
        first_with_pair = next((row for row in members if row.get("fastq1") and row.get("fastq2")), None)
        baseline = first_with_pair or members[0]
        fastq_candidates = _row_fastq_candidates(members)

        conditions = []
        for row in members:
            cond = _clean_cell(row.get("condition", "")).strip()
            if cond:
                conditions.append(cond)
        condition = conditions[0] if conditions else ""
        explicit_samples = [_clean_cell(row.get("sample", "")).strip() for row in members if _clean_cell(row.get("sample", "")).strip()]
        sample_out = explicit_samples[0] if explicit_samples else ""
        unique_conditions = []
        for cond in conditions:
            if cond not in unique_conditions:
                unique_conditions.append(cond)
        if len(unique_conditions) > 1:
            warnings.append(
                t(
                    "warn.conflicting_conditions",
                    sample=sample_out or sample_key,
                    conditions=", ".join(unique_conditions),
                    chosen=condition,
                )
            )

        if first_with_pair:
            fastq1 = _normalize_input_value(first_with_pair.get("fastq1", ""))
            fastq2 = _normalize_input_value(first_with_pair.get("fastq2", ""))
            if not fastq1:
                fastq1 = _pick_preferred_fastq(fastq_candidates, "1")
            if not fastq2:
                fastq2 = _pick_preferred_fastq([fq for fq in fastq_candidates if fq != fastq1], "2")
        else:
            fastq1 = _pick_preferred_fastq(fastq_candidates, "1")
            if not fastq1 and fastq_candidates:
                fastq1 = fastq_candidates[0]
            fastq2 = _pick_preferred_fastq([fq for fq in fastq_candidates if fq != fastq1], "2")

        if not sample_out:
            seed = (
                _normalize_input_value(_clean_cell(baseline.get("fastq1", "")))
                or _normalize_input_value(_clean_cell(baseline.get("fastq2", "")))
                or fastq1
                or _normalize_input_value(_clean_cell(baseline.get("fastq2", "")))
            )
            sample_out = _derive_sample_from_fastq(seed, fastq_pool) if seed else ""

        if fastq1 and not condition and st.session_state.get("autofill_conditions", True):
            condition = sample_out or _sample_base(fastq1)

        canonical.append(
            {
                "sample": sample_out,
                "condition": condition,
                "fastq1": fastq1,
                "fastq2": "" if fastq2 == fastq1 else fastq2,
            }
        )

    return canonical, warnings


def _write_samples(rows, paired: bool):
    output_dir = OUTPUT_ROOT / "metadata"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "samples.tsv"
    header = ["sample", "condition", "fastq1"]
    if paired:
        header.append("fastq2")
    with out_path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            values = [
                row.get("sample", ""),
                row.get("condition", ""),
                _normalize_input_value(row.get("fastq1", "")),
            ]
            if paired:
                values.append(_normalize_input_value(row.get("fastq2", "")))
            handle.write("\t".join(values) + "\n")
    return out_path


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
    ok = input_ok and output_ok and output_writable and fastq_count > 0
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
    if not REF_MANIFEST_PATH.exists():
        return {}
    try:
        return yaml.safe_load(REF_MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _species_presets(manifest, species):
    presets = sorted((manifest.get("presets") or {}).keys())
    keys = [key for key in presets if key.lower().startswith(species.lower())]
    return keys or presets


def _preset_releases(manifest, preset):
    if not manifest or not preset:
        return []
    presets = manifest.get("presets") or {}
    release_block = presets.get(preset) or {}
    return sorted(release_block.keys())


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


def _human(n):
    size = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def _fingerprint_fastq(fastq_rel):
    items = []
    for rel in sorted(fastq_rel):
        p = INPUT_ROOT / rel
        if not p.exists():
            items.append({"path": rel, "exists": False})
            continue
        stat = p.stat()
        items.append(
            {
                "path": rel,
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    return items


def _build_manifest_payload(payload: dict, rows_raw, fastq_rel):
    return {
        "schema_version": 1,
        "config": _prune_empty(dict(payload)),
        "samples": _coerce_rows_raw(rows_raw),
        "fastq": _fingerprint_fastq(fastq_rel),
        "git_rev": _git_rev(),
    }


def _manifest_run_id(payload: dict):
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    return RUNS_ROOT / run_id


def _write_run_metadata(run_dir: Path, metadata: dict):
    meta_dir = run_dir / "run"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return meta_path


def _write_run_manifest(run_dir: Path, run_id: str, payload: dict):
    run_meta = run_dir / "run"
    run_meta.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    manifest_path = run_meta / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


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
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if isinstance(cmd, list) and any(str(part).lower() == "snakemake" for part in cmd):
        run_dir = _extract_run_dir_from_cmd(cmd)
        _write_snakemake_debug_files(run_dir, cmd, proc.stdout or "", proc.stderr or "")
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output.strip()


def _append_ui_command(cmd, work_id: str, label: str):
    try:
        log_dir = OUTPUT_ROOT / "run"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "ui_commands.log"
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "work_id": work_id,
            "label": label,
            "cmd": cmd,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return


def _run_cmd_logged(cmd, work_id: str, label: str):
    _append_ui_command(cmd, work_id, label)
    return _run_cmd(cmd)


def _extract_snakemake_log_path(text: str):
    if not text:
        return ""
    match = re.search(r"(/?\.snakemake[\\/]+log[\\/][^\s]+)", text)
    if match:
        return match.group(1)
    return ""


def _extract_run_dir_from_cmd(cmd):
    if not isinstance(cmd, list):
        return None
    for idx, token in enumerate(cmd):
        if token == "--directory" and idx + 1 < len(cmd):
            try:
                return Path(cmd[idx + 1])
            except Exception:
                return None
    return None


def _write_snakemake_debug_files(run_dir: Path, cmd, stdout_text: str, stderr_text: str):
    if run_dir is None:
        return
    try:
        run_meta = run_dir / "run"
        run_meta.mkdir(parents=True, exist_ok=True)
        (run_meta / "snakemake.cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
        (run_meta / "snakemake.stdout.log").write_text(stdout_text or "", encoding="utf-8")
        (run_meta / "snakemake.stderr.log").write_text(stderr_text or "", encoding="utf-8")
    except Exception:
        return


def _snakemake_log_candidates(run_dir: Path, limit: int = 10):
    if not run_dir or not run_dir.exists():
        return {"primary": None, "candidates": []}

    seen = set()
    collected = []

    def _add(path: Path):
        try:
            p = path.resolve()
        except Exception:
            p = path
        key = str(p)
        if key in seen or not path.exists() or not path.is_file():
            return
        seen.add(key)
        try:
            size = int(path.stat().st_size)
        except Exception:
            size = 0
        collected.append({"path": path, "size": size})

    snk_logs = sorted((run_dir / ".snakemake" / "log").glob("*.snakemake.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in snk_logs[:1]:
        _add(p)

    rule_logs = sorted((run_dir / "logs").glob("**/*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in rule_logs:
        if len(collected) >= limit:
            break
        _add(p)

    salmon_files = sorted((run_dir / "salmon").glob("**/*"), key=lambda p: p.stat().st_mtime, reverse=True) if (run_dir / "salmon").exists() else []
    for p in salmon_files:
        if len(collected) >= limit:
            break
        if p.is_file():
            _add(p)

    primary = collected[0] if collected else None
    return {"primary": primary, "candidates": collected[:limit]}


def _summarize_failure(text: str):
    raw = text or ""
    if "MissingInputException" in raw:
        return {
            "cause": "Input files are missing (fastp outputs were not generated, were deleted, or naming is inconsistent).",
            "action": "Rerun from fastp and verify R1/R2 naming and report input synchronization.",
            "kind": "missing_input",
        }
    if "IncompleteFilesException" in raw:
        return {
            "cause": "Previous outputs are marked incomplete.",
            "action": "Delete incomplete outputs and continue, or rerun with --rerun-incomplete.",
            "kind": "incomplete",
        }
    if "UnicodeDecodeError" in raw and "0x8b" in raw:
        return {
            "cause": "A gzip file is being read as plain text.",
            "action": "Use gzip-aware preprocessing and re-run from fastp.",
            "kind": "gzip_decode",
        }
    if "CalledProcessError" in raw or "non-zero exit status" in raw:
        return {
            "cause": "An external command exited with a non-zero code.",
            "action": "Inspect the failed rule logs for exact command and stderr details.",
            "kind": "called_process",
        }
    return {
        "cause": "Snakemake failed before report completion.",
        "action": "Inspect the logs below and rerun after fixing the root cause.",
        "kind": "generic",
    }


def _failure_debug_commands(run_dir: Path):
    p = str(run_dir)
    return [
        f"ls -lah {p}/.snakemake/log | tail -n 50",
        f"tail -n 200 {p}/.snakemake/log/*.snakemake.log",
        f"find {p}/logs -type f -maxdepth 3 -name \"*.log\" -print",
        "python -m snakemake --snakefile /app/workflow/Snakefile -n -p --reason --show-failed-logs "
        f"--configfiles /output/config.yaml --config input=/input output={p}",
    ]


def _build_snakemake_base_cmd(run_dir: Path, config_path: Path, threads: int):
    return [
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
        "--reason",
        "--show-failed-logs",
        "--latency-wait",
        "60",
    ]


def _pre_run_guard(run_dir: Path, config_path: Path, threads: int, work_id: str):
    base_cmd = _build_snakemake_base_cmd(run_dir, config_path, threads)
    dry_cmd = base_cmd + ["-n", "--", "report"]
    code, output = _run_cmd_logged(dry_cmd, work_id, "dry_run")
    if code == 0:
        return {"status": "ok", "output": output}

    text = output or ""
    if "Directory cannot be locked" in text or ".snakemake/lock" in text:
        unlock_cmd = base_cmd + ["--unlock"]
        _run_cmd_logged(unlock_cmd, work_id, "unlock")
        code2, output2 = _run_cmd_logged(dry_cmd, work_id, "dry_run_after_unlock")
        if code2 == 0:
            return {"status": "ok", "output": output2}
        return {"status": "lock", "output": output2 or output}

    if "IncompleteFilesException" in text or "Incomplete files" in text:
        files = extract_incomplete_files(text)
        return {"status": "incomplete", "output": text, "files": files}

    return {"status": "error", "output": text}


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
    cmd_path = run_meta / "snakemake.cmd.txt"
    stdout_path = run_meta / "snakemake.stdout.log"
    stderr_path = run_meta / "snakemake.stderr.log"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")
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
        "--reason",
        "--show-failed-logs",
        "--latency-wait",
        "60",
    ]
    cmd = [item for item in cmd if item]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(["--", "report"])
    cmd_path.write_text(" ".join(cmd), encoding="utf-8")
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
if "ref_mode" not in st.session_state:
    st.session_state.ref_mode = "fasta_gtf"
if "ref_transcripts" not in st.session_state:
    st.session_state.ref_transcripts = ""
if "ref_genome" not in st.session_state:
    st.session_state.ref_genome = ""
if "ref_gtf" not in st.session_state:
    st.session_state.ref_gtf = ""
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
if "run_cmd_path" not in st.session_state:
    st.session_state.run_cmd_path = ""
if "run_dir" not in st.session_state:
    st.session_state.run_dir = ""
if "run_config_path" not in st.session_state:
    st.session_state.run_config_path = ""
if "use_custom_refs" not in st.session_state:
    st.session_state.use_custom_refs = False
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

lang_options = ["en", "ja"]
lang_index = 0 if st.session_state.lang == "en" else 1
st.sidebar.selectbox(t("sidebar.language"), lang_options, index=lang_index, key="lang")

if not st.session_state.fastq_rel or not st.session_state.refs_rel["fasta"]:
    fastq_rel, refs_rel = _scan_input(INPUT_ROOT)
    st.session_state.fastq_rel = fastq_rel
    st.session_state.refs_rel = refs_rel

steps = ["Project", "Samples", "Reference files", "Advanced", "Summary"]
ss = st.session_state
ss.step = _clamp_step(int(ss.step))
ss.step_radio = ss.step

header_left, header_right = st.columns([3, 2])
with header_left:
    st.title("Harako-RNAseq Web UI")
    st.caption(t("info.subtitle_wizard"))
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
    st.session_state.step = _clamp_step(int(st.session_state.step_radio))


def _nav_buttons():
    nav_left, nav_mid, nav_right = st.columns([1, 3, 1])
    with nav_left:
        if st.button("Back", disabled=st.session_state.step <= 0):
            st.session_state.step = _clamp_step(st.session_state.step - 1)
            st.rerun()
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
            st.session_state.step = _clamp_step(st.session_state.step + 1)
            st.rerun()


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
        },
    )
    _log_debug("route_change", prev_snapshot or {}, current_snapshot or {})
st.session_state.last_step = current_step
st.session_state.last_run_config_snapshot = current_snapshot

summary_state = _get_run_config()
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
        fastq_rel, refs_rel = _scan_input(INPUT_ROOT)
        st.session_state.fastq_rel = fastq_rel
        st.session_state.refs_rel = refs_rel

elif st.session_state.step == 1:
    st.subheader(t("label.samples_step"))
    fastq_rel = st.session_state.fastq_rel
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
    if len(fastq_rel) == 0:
        st.error(t("error.no_fastq_files"))
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
            st.session_state.run_config_touched = True
            st.session_state.validation_ok = False
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
    st.markdown(
        t("info.editor_icon_guide"),
        unsafe_allow_html=True,
    )
    st.data_editor(
        editor_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        key="samples_editor",
        on_change=_sync_rows_raw_from_editor,
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
    manifest = _load_ref_manifest()
    st.checkbox(t("label.use_custom_refs"), key="use_custom_refs")
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])

    run_config = _get_run_config()
    ref_cache_root = _ref_cache_root()
    species_choices = [
        {"label": t("label.species_mouse_mm10"), "species": "mouse", "preset": "mouse_gencode_mm10"},
        {"label": t("label.species_mouse_mm39"), "species": "mouse", "preset": "mouse_gencode"},
        {"label": t("label.species_human_hg38"), "species": "human", "preset": "human_gencode"},
        {"label": t("label.species_rat_rn7"), "species": "rat", "preset": "rat_ensembl"},
    ]
    labels = [choice["label"] for choice in species_choices]
    preset_value = run_config.get("ref_preset", "")
    species_value = normalize_species(run_config.get("species"))
    if not st.session_state.use_custom_refs and preset_value:
        for choice in species_choices:
            if choice["preset"] == preset_value and choice["species"] != species_value:
                updateRunConfig({"species": choice["species"]})
                species_value = choice["species"]
                break
    selected_index = 0
    for idx, choice in enumerate(species_choices):
        if preset_value and choice["preset"] == preset_value:
            selected_index = idx
            break
        if not preset_value and choice["species"] == species_value:
            selected_index = idx
    species_label = st.selectbox(t("label.species_build"), labels, index=selected_index)
    selected = species_choices[labels.index(species_label)]
    if selected["species"] != species_value:
        updateRunConfig({"species": selected["species"]})
    if not st.session_state.use_custom_refs and selected["preset"] and selected["preset"] != preset_value:
        updateRunConfig({"ref_preset": selected["preset"]})
        preset_value = selected["preset"]

    if not st.session_state.use_custom_refs:
        presets_all = manifest.get("presets") or {}
        preset_available = preset_value in presets_all
        if not preset_available:
            st.warning(t("warn.preset_unavailable", preset=preset_value))
        release_options = _preset_releases(manifest, preset_value) if preset_available else ["pinned"]
        if not release_options:
            release_options = ["pinned"]
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
        )
        if release_choice != release_value:
            updateRunConfig({"ref_release": release_choice})
            release_value = release_choice

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
            st.dataframe(df_rows, use_container_width=True, hide_index=True)
            if not cache_ok:
                st.caption(t("msg.refs_download_needed"))

            overwrite_refs = st.checkbox(t("label.ref_download_overwrite"), value=False, key="ref_download_overwrite")
            fetch_disabled = (cache_ok and not overwrite_refs) or (not preset_available)

            if st.button(t("btn.download_refs"), disabled=fetch_disabled):
                code, output = _fetch_refs(preset, release, cache_root=ref_cache_root, overwrite=overwrite_refs)
                with st.expander(t("label.details")):
                    st.text_area(t("label.fetch_refs_output"), output or t("label.no_output"), height=180)
                if code == 0:
                    fastq_rel, refs_rel = _scan_input(INPUT_ROOT)
                    st.session_state.fastq_rel = fastq_rel
                    st.session_state.refs_rel = refs_rel
                    st.success(t("success.ref_fetch_completed"))
                    st.rerun()
                else:
                    st.error(_ref_fetch_error_message(code, output or ""))
                    st.warning(t("warn.ref_fetch_custom_fallback"))
                    st.code(
                        "refs/transcripts.fa.gz\n"
                        "refs/genome.fa.gz\n"
                        "refs/annotation.gtf.gz"
                    )

            if st.button(t("btn.download_refs_url"), disabled=fetch_disabled):
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
                        st.session_state.ref_mode = "preset_cache"
                        st.session_state.ref_transcripts = str(_cache_ref_paths(preset, release)["transcripts_fasta"])
                        st.session_state.ref_genome = str(_cache_ref_paths(preset, release)["genome_fasta"])
                        st.session_state.ref_gtf = str(_cache_ref_paths(preset, release)["gtf"])
                        fastq_rel, refs_rel = _scan_input(INPUT_ROOT)
                        st.session_state.fastq_rel = fastq_rel
                        st.session_state.refs_rel = refs_rel
                        status.update(label=t("success.ref_fetch_completed"), state="complete")
                        with st.expander(t("label.details")):
                            if stdout_extra:
                                st.text_area("Fetch refs (URL) stdout", "\n".join(stdout_extra), height=140)
                            if stderr:
                                st.text_area("Fetch refs (URL) stderr", stderr, height=140)
                        st.rerun()
                    else:
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
            st.session_state.ref_mode = "preset_cache"
            cache_paths = _cache_ref_paths(preset_value, release_value)
            st.session_state.ref_transcripts = str(cache_paths["transcripts_fasta"])
            st.session_state.ref_genome = str(cache_paths["genome_fasta"])
            st.session_state.ref_gtf = str(cache_paths["gtf"])
            st.caption(t("info.using_cached_refs"))
        else:
            st.session_state.ref_mode = "none"
            st.warning(t("warning.fetch_refs_to_enable"))
    else:
        mode = st.selectbox(t("label.reference_mode"), ["fasta_gtf", "transcripts_only"], index=0, key="ref_mode")
        if mode in ("fasta_gtf", "transcripts_only") and not fasta_rel:
            st.error(t("error.no_fasta"))
            st.stop()
        if mode == "fasta_gtf" and not gtf_rel:
            st.error(t("error.no_gtf"))
            st.stop()
        if mode == "transcripts_only":
            _ensure_ref_default("ref_transcripts", fasta_rel, ["transcript", "cdna"])
            st.selectbox(t("label.transcripts_fasta"), fasta_rel, key="ref_transcripts")
        else:
            _ensure_ref_default("ref_transcripts", fasta_rel, ["transcript", "cdna"])
            _ensure_ref_default("ref_genome", fasta_rel, ["genome"])
            _ensure_ref_default("ref_gtf", gtf_rel, ["gtf"])
            st.selectbox(t("label.transcripts_fasta"), fasta_rel, key="ref_transcripts")
            st.selectbox(t("label.genome_fasta"), fasta_rel, key="ref_genome")
            st.selectbox(t("label.gtf"), gtf_rel, key="ref_gtf")

        ref_block = {
            "transcripts_fasta": _normalize_ref(st.session_state.get("ref_transcripts", "")),
            "genome_fasta": _normalize_ref(st.session_state.get("ref_genome", "")),
            "gtf": _normalize_ref(st.session_state.get("ref_gtf", "")),
        }
        custom_ok, rows = _ref_status_table(mode, ref_block, "", "")
        df_rows = pd.DataFrame(rows)
        if not df_rows.empty:
            df_rows["status"] = df_rows["status"].map(
                {"present": t("status.present"), "missing": t("status.missing"), "invalid": t("status.invalid")}
            )
        st.dataframe(df_rows, use_container_width=True, hide_index=True)
        if not custom_ok:
            st.caption(t("msg.refs_download_needed"))

    current_ref_state = _ref_state_snapshot()
    prev_ref_state = st.session_state.get("last_ref_state")
    if prev_ref_state is not None and prev_ref_state != current_ref_state:
        st.session_state.run_config_touched = True
        st.session_state.validation_ok = False
        st.session_state.saved = False
    st.session_state.last_ref_state = current_ref_state

elif st.session_state.step == 3:
    st.subheader(t("label.advanced"))
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
    st.subheader(t("label.summary"))
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

    ref_mode = st.session_state.get("ref_mode", "fasta_gtf")
    use_custom_refs = bool(st.session_state.get("use_custom_refs", False))
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
    if ref_mode in ("transcripts_only", "fasta_gtf"):
        _ensure_ref_default("ref_transcripts", fasta_rel, ["transcript", "cdna"])
        if ref_mode == "fasta_gtf":
            _ensure_ref_default("ref_genome", fasta_rel, ["genome"])
            _ensure_ref_default("ref_gtf", gtf_rel, ["gtf"])
    with st.expander(t("label.details")):
        st.code(
            "ref_mode="
            + str(ref_mode)
            + " ref_transcripts="
            + str(st.session_state.get("ref_transcripts", ""))
            + " ref_genome="
            + str(st.session_state.get("ref_genome", ""))
            + " ref_gtf="
            + str(st.session_state.get("ref_gtf", ""))
            + " | candidates: FASTA="
            + str(len(fasta_rel))
            + " GTF="
            + str(len(gtf_rel))
        )
    run_config = _get_run_config()
    ref_block = {}
    ref_block_payload = {}
    ref_preset = None
    ref_release = run_config.get("ref_release") or "pinned"
    if ref_mode == "preset_cache":
        ref_preset = run_config.get("ref_preset", "")
        ref_block = {}
    elif ref_mode == "transcripts_only":
        ref_block["transcripts_fasta"] = _normalize_ref(st.session_state.get("ref_transcripts", ""))
    else:
        ref_block["transcripts_fasta"] = _normalize_ref(st.session_state.get("ref_transcripts", ""))
        ref_block["genome_fasta"] = _normalize_ref(st.session_state.get("ref_genome", ""))
        ref_block["gtf"] = _normalize_ref(st.session_state.get("ref_gtf", ""))
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

    st.write("config.yaml preview:")
    st.code(yaml.safe_dump(payload, sort_keys=False))

    st.write("samples.tsv preview:")
    preview_path = OUTPUT_ROOT / "metadata" / "samples.tsv"
    sample_header = ["sample", "condition", "fastq1"] + (["fastq2"] if st.session_state.paired else [])
    st.code("\t".join(sample_header) + "\n" + "\n".join(
        ["\t".join([row.get(k, "") for k in sample_header]) for row in rows_raw]
    ))

    if st.session_state.get("run_status") == "running":
        _poll_run_process()

    invalid = []
    if not rows_raw:
        invalid.append(t("invalid.samples_missing"))
    if engine not in ("real", "stub"):
        invalid.append(t("invalid.engine_invalid"))
    needs_two_conditions = engine == "real" and len(conditions) < 2
    if engine == "real":
        if needs_two_conditions:
            invalid.append(t("invalid.engine_need_two_conditions"))
        if contrast_mode == "ref" and (not contrast_ref or contrast_ref not in conditions):
            invalid.append(t("invalid.contrast_ref"))
        if contrast_mode == "select":
            for a, b in contrast_pairs:
                if a not in conditions or b not in conditions:
                    invalid.append(t("invalid.contrast_pair", a=a, b=b))
        if contrast_mode == "legacy":
            for item in legacy_list:
                if "_vs_" in item:
                    a, b = item.split("_vs_", 1)
                    if a not in conditions or b not in conditions:
                        invalid.append(t("invalid.contrast_legacy", item=item))
    fastq_rel = st.session_state.fastq_rel
    row_issues = _validate_rows(rows_raw, fastq_rel, st.session_state.paired)
    if row_issues:
        invalid.extend(row_issues)

    if ref_preset and not str(ref_preset).lower().startswith(resolved_species):
        invalid.append(t("invalid.ref_preset_species_mismatch", preset=ref_preset, species=resolved_species))
    manifest = _load_ref_manifest()
    if ref_mode == "preset_cache" and ref_preset and ref_preset not in (manifest.get("presets") or {}):
        invalid.append(t("invalid.ref_preset_unknown", preset=ref_preset))

    if engine == "real":
        ref_errors, ref_missing = _validate_refs(ref_mode, ref_block, st.session_state.refs_rel, ref_preset, ref_release)
        if ref_errors:
            if ref_missing:
                st.error(t("error.ref_not_selected"))
                st.warning("\n".join(_t_lines("msg.refs_missing")))
            fasta_rel = st.session_state.refs_rel.get("fasta", [])
            gtf_rel = st.session_state.refs_rel.get("gtf", [])
            candidates_info = f"FASTA candidates: {len(fasta_rel)}, GTF candidates: {len(gtf_rel)}"
            invalid.extend(ref_errors)
            st.error(
                t(
                    "error.reference_issues",
                    details="\n".join(sorted(set(ref_errors))),
                    candidates_info=candidates_info,
                )
            )
    if needs_two_conditions:
        st.warning("\n".join(_t_lines("msg.engine_need_two_conditions")))
    if invalid:
        st.error(t("error.save_disabled"))
        st.write("\n".join(map(str, invalid)))
        st.warning(t("warn.fix_issues_enable_save"))
        if st.button(t("btn.go_reference")):
            st.session_state.step = 2
            st.rerun()

    config_path, samples_path, config_ok, samples_ok = _check_saved_outputs()
    output_write_ok, output_write_detail = _output_write_test()
    saved_species = ""
    if config_ok:
        saved_cfg = _load_yaml(config_path)
        saved_species = (saved_cfg.get("species") or "").strip().lower()

    manifest_payload = _build_manifest_payload(payload, rows_raw, fastq_rel)
    run_id = _manifest_run_id(manifest_payload)
    st.session_state.run_id = run_id
    run_dir = _run_dir_for_id(run_id)
    run_manifest_path = run_dir / "run" / "manifest.json"
    run_exists = run_manifest_path.exists() or run_dir.exists()

    run_options = ["start_new"] if not run_exists else ["open_existing", "resume"]
    if st.session_state.run_mode not in run_options:
        st.session_state.run_mode = "resume" if run_exists else "start_new"
    st.radio(
        "Run behavior",
        options=run_options,
        key="run_mode",
        format_func=lambda v: {
            "start_new": "Start new run directory",
            "open_existing": "Open existing report only (no compute)",
            "resume": "Resume existing run (--rerun-incomplete style)",
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
    st.caption(f"Run id: {run_id}")
    try:
        display_run_dir = run_dir.relative_to(OUTPUT_ROOT)
    except ValueError:
        display_run_dir = run_dir
    st.caption(t("info.run_dir", path=display_run_dir))
    st.caption(t("info.resolved_species", species=resolved_species))

    run_blockers = list(invalid)
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

    with st.expander(t("label.precheck_details")):
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

    save_disabled = bool(invalid)
    if st.button(t("btn.save_bilingual"), disabled=save_disabled):
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
                with st.expander(t("label.details")):
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
                    st.error(t("error.save_failed_missing", missing=", ".join(missing)))
                    st.error(t("error.output_mount_wrong"))
        except Exception:
            st.session_state.saved = False
            st.error(t("error.save_failed_generic"))
        entries = _list_output_dir()
        st.write(t("label.output_contents"))
        st.code("\n".join(entries) if entries else t("label.empty"))
    if save_disabled:
        st.caption(t("msg.save_disabled_short"))

    validate_disabled = bool(invalid) or not config_ok
    if st.button(t("btn.validate_bilingual"), disabled=validate_disabled):
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
        st.code("$ " + " ".join(cmd))
        code, output = _run_cmd_logged(cmd, st.session_state.get("run_id", ""), "validate_manual")
        with st.expander(t("label.details")):
            st.text_area(t("label.validate_output"), output or t("label.no_output"), height=200)
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

    dry_run_disabled = bool(run_blockers)
    if st.button(t("btn.dry_run_bilingual"), disabled=dry_run_disabled):
        cmd = [
            "python",
            "-m",
            "snakemake",
            "--directory",
            str(OUTPUT_ROOT),
            "-s",
            "workflow/Snakefile",
            "--configfile",
            str(OUTPUT_ROOT / "config.yaml"),
            "--config",
            "input=/input",
            "output=/output",
            "--cores",
            "1",
            "-n",
            "-p",
            "--",
            "report",
        ]
        st.code("$ " + " ".join(cmd))
        code, output = _run_cmd_logged(cmd, st.session_state.get("run_id", ""), "dry_run_manual")
        with st.expander(t("label.details")):
            st.text_area(t("label.dryrun_output"), output or t("label.no_output"), height=200)
        if code == 0:
            st.success(t("success.dryrun_ok"))
        else:
            st.error(t("error.dryrun_failed", code=code))
    if dry_run_disabled:
        st.caption(t("msg.dryrun_blocked"))

    run_in_progress = st.session_state.get("run_status") == "running"
    open_existing_mode = st.session_state.run_mode == "open_existing"
    run_disabled = run_in_progress or (bool(run_blockers) and not open_existing_mode) or (open_existing_mode and not run_exists)
    if st.button(t("btn.run_bilingual"), disabled=run_disabled):
        st.session_state.run_guard = None
        st.session_state.auto_recover_incomplete = False
        st.session_state.auto_recover_cleanup = False
        if open_existing_mode and run_exists:
            st.session_state.run_dir = str(run_dir)
            st.session_state.run_status = "success"
            st.session_state.run_rc = 0
            st.session_state.run_log = t("msg.open_existing_report")
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
        st.rerun()
    if run_disabled:
        st.caption(t("msg.run_blocked"))

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
        with st.expander(t("label.details")):
            st.text_area(t("label.dryrun_output"), out_text or t("label.no_output"), height=220)

    if run_blockers and st.session_state.run_mode != "open_existing":
        st.error(t("error.run_disabled"))
        st.write("\n".join(sorted(set(run_blockers))))

    run_status = st.session_state.get("run_status", "idle")
    run_log_text = st.session_state.get("run_log", "")
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
                with st.expander(t("label.details")):
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
            with st.expander(t("label.details")):
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
