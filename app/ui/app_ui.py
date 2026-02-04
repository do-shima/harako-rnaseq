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


INPUT_ROOT = Path("/input")
OUTPUT_ROOT = Path("/output")
REPO_ROOT = Path(__file__).resolve().parents[2]
REF_MANIFEST_PATH = REPO_ROOT / "workflow" / "ref_manifest.yaml"
UI_MOUNT_NOTE = "Input=/input and Output=/output must be mounted. Start with `just app` after setting INPUT/OUT."
FASTQ_EXTS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")
RUN_LOG_MAX_CHARS = 200000
RUNS_ROOT = OUTPUT_ROOT / "data_out"
JST = timezone(timedelta(hours=9), name="JST")


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
        return
    if isinstance(state, list):
        st.session_state.rows_raw = _coerce_rows_raw(state)
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


def _validate_rows(rows, fastq_rel, paired):
    issues = []
    seen = set()
    for idx, row in enumerate(rows, start=1):
        sample = _clean_cell(row.get("sample", ""))
        cond = _clean_cell(row.get("condition", ""))
        fq1 = _normalize_input_value(_clean_cell(row.get("fastq1", "")))
        fq2 = _normalize_input_value(_clean_cell(row.get("fastq2", "")))
        if not sample:
            issues.append(f"row {idx}: sample missing")
        if sample in seen:
            issues.append(f"row {idx}: duplicate sample {sample}")
        seen.add(sample)
        if not cond:
            issues.append(f"row {idx}: condition missing")
        if not fq1:
            issues.append(f"row {idx}: fastq1 missing")
        elif fq1 not in fastq_rel and not _ref_exists(fq1):
            issues.append(f"row {idx}: fastq1 not found ({fq1})")
        if paired:
            if not fq2:
                issues.append(f"row {idx}: fastq2 missing")
            elif fq2 not in fastq_rel and not _ref_exists(fq2):
                issues.append(f"row {idx}: fastq2 not found ({fq2})")
    return issues


def _validate_refs(ref_mode, ref_block, refs_rel, ref_preset):
    errors = []
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])
    if ref_mode in ("fasta_gtf", "preset_cache"):
        for key in ("transcripts_fasta", "genome_fasta", "gtf"):
            val = _normalize_input_value(ref_block.get(key) or "")
            if not val:
                errors.append(f"missing {key} (not selected)")
                continue
            if key == "gtf":
                if val not in gtf_rel and not _ref_exists(val):
                    errors.append(f"gtf not found ({val})")
            else:
                if val not in fasta_rel and not _ref_exists(val):
                    errors.append(f"{key} not found ({val})")
    elif ref_mode == "transcripts_only":
        val = _normalize_input_value(ref_block.get("transcripts_fasta") or "")
        if not val:
            errors.append("missing transcripts_fasta (not selected)")
        elif val not in fasta_rel and not _ref_exists(val):
            errors.append(f"transcripts_fasta not found ({val})")
    elif ref_mode == "preset":
        if not ref_preset:
            errors.append("missing ref preset")
    return errors


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
                f"sample '{sample_out or sample_key}' has conflicting condition values {unique_conditions}; using '{condition}'."
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


def _mount_status():
    fastq_rel = st.session_state.fastq_rel
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])
    st.write(f"/input scan: FASTQ={len(fastq_rel)} FASTA={len(fasta_rel)} GTF={len(gtf_rel)}")
    if st.button("Test /output write"):
        ok, detail = _output_write_test()
        if ok:
            st.success("/output is writable.")
        else:
            st.error("/output is not writable. Check OUT mount and permissions.")
            if detail:
                st.code(detail)


def _host_mount_info():
    host_input = (os.environ.get("HOST_INPUT") or "").strip() or "unknown"
    host_out = (os.environ.get("HOST_OUT") or "").strip() or "unknown"
    st.caption(
        f"Host INPUT: {host_input} | Container INPUT: {INPUT_ROOT} (read-only)\n"
        f"Host OUT: {host_out} | Container OUT: {OUTPUT_ROOT} (writable)"
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


def _cache_ref_paths(preset, release):
    base = OUTPUT_ROOT / "refs_cache" / preset / release
    return {
        "transcripts_fasta": base / "transcripts.fa.gz",
        "genome_fasta": base / "genome.fa.gz",
        "gtf": base / "annotation.gtf.gz",
    }


def _cache_status(paths):
    rows = []
    ok = True
    for key, path in paths.items():
        exists = path.exists()
        if not exists:
            ok = False
        size = path.stat().st_size if exists else 0
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone(JST).strftime("%Y-%m-%d %H:%M:%S %Z") if exists else "-"
        rows.append({"file": key, "path": str(path), "exists": exists, "size": size, "updated_jst": mtime})
    return ok, rows


def _fetch_refs(preset, release):
    cmd = [
        "python",
        str(REPO_ROOT / "scripts" / "fetch_reference_preset.py"),
        "--preset",
        preset,
        "--release",
        release,
        "--cache-dir",
        str(OUTPUT_ROOT / "refs_cache"),
        "--manifest",
        str(REF_MANIFEST_PATH),
    ]
    return _run_cmd(cmd)


def _new_run_id():
    now = datetime.now(JST)
    short = hashlib.sha1(f"{time.time_ns()}".encode("utf-8")).hexdigest()[:6]
    return f"run_{now.strftime('%Y%m%d_%H%M')}JST_{short}"


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


def _compute_input_fingerprint(config_path: Path, samples_path: Path, fastq_rel):
    payload = {
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest() if config_path.exists() else "",
        "samples_sha256": hashlib.sha256(samples_path.read_bytes()).hexdigest() if samples_path.exists() else "",
        "fastq": _fingerprint_fastq(fastq_rel),
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_run_metadata(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _find_runs_by_fingerprint(fingerprint: str):
    matches = []
    if not RUNS_ROOT.exists():
        return matches
    for run_dir in sorted(RUNS_ROOT.glob("run_*"), reverse=True):
        meta_path = run_dir / "run" / "metadata.json"
        if not meta_path.exists():
            continue
        metadata = _load_run_metadata(meta_path)
        if metadata.get("input_fingerprint") == fingerprint:
            matches.append((run_dir, metadata))
    return matches


def _write_run_metadata(run_dir: Path, metadata: dict):
    meta_dir = run_dir / "run"
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return meta_path


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


def _prepare_run_dir(mode: str, fingerprint: str, existing_runs):
    if mode == "resume" and existing_runs:
        return existing_runs[0][0]
    if mode == "open_last" and existing_runs:
        return existing_runs[0][0]
    run_dir = RUNS_ROOT / _new_run_id()
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_run_config(run_dir: Path, payload: dict):
    run_cfg = dict(payload)
    run_cfg["output"] = str(run_dir)
    run_cfg["sample_table"] = str(OUTPUT_ROOT / "metadata" / "samples.tsv")
    cfg_path = run_dir / "config_resolved.yaml"
    cfg_path.write_text(yaml.safe_dump(run_cfg, sort_keys=False), encoding="utf-8")
    return cfg_path


def _run_cmd(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output.strip()


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
    handle = st.session_state.get("run_handle")
    if handle:
        try:
            handle.close()
        except Exception:
            pass
    st.session_state.run_handle = None
    st.session_state.run_proc = None


def _start_run_report(engine: str, threads: int, run_dir: Path, config_path: Path, extra_args=None):
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "ui_run_report.log"
    log_path.write_text("", encoding="utf-8")
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
        f"engine={engine}",
        "--cores",
        str(int(threads)),
        "-p",
        "--latency-wait",
        "60",
    ]
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend(["--", "report"])
    handle = log_path.open("a", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT, text=True, env=env)
    st.session_state.run_proc = proc
    st.session_state.run_handle = handle
    st.session_state.run_log_path = str(log_path)
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
    log_path_raw = st.session_state.get("run_log_path", "")
    if log_path_raw:
        log_path = Path(log_path_raw)
        st.session_state.run_log = _tail_text(_read_text(log_path))
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
    page_title="RNA-seq Init UI",
    layout="wide",
    menu_items={"Get help": None, "Report a bug": None, "About": None},
)

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
    st.session_state.paired = False
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
if "run_log_path" not in st.session_state:
    st.session_state.run_log_path = ""
if "run_dir" not in st.session_state:
    st.session_state.run_dir = ""
if "run_config_path" not in st.session_state:
    st.session_state.run_config_path = ""
if "use_custom_refs" not in st.session_state:
    st.session_state.use_custom_refs = False
if "ref_species" not in st.session_state:
    st.session_state.ref_species = "mouse"
if "ref_release" not in st.session_state:
    st.session_state.ref_release = "pinned"
if "ref_preset_name" not in st.session_state:
    st.session_state.ref_preset_name = ""
if "run_mode" not in st.session_state:
    st.session_state.run_mode = "start_new"

if not st.session_state.fastq_rel or not st.session_state.refs_rel["fasta"]:
    fastq_rel, refs_rel = _scan_input(INPUT_ROOT)
    st.session_state.fastq_rel = fastq_rel
    st.session_state.refs_rel = refs_rel

steps = ["Project", "Samples", "Reference", "Advanced", "Summary"]
ss = st.session_state
ss.step = _clamp_step(int(ss.step))
ss.step_radio = ss.step

st.title("RNA-seq Init (Web UI)")
st.caption("Input is fixed to /input, output is fixed to /output.")
st.info(UI_MOUNT_NOTE)
_host_mount_info()

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


if st.session_state.step == 0:
    st.subheader("Project / Basic")
    _mount_status()
    engine = st.selectbox("Engine", ["real", "stub"], index=0, key="engine")
    paired = st.checkbox("Paired-end reads", value=st.session_state.paired)
    if paired != st.session_state.paired:
        st.session_state.paired = paired
    threads = st.number_input("Threads", min_value=1, max_value=64, value=1, step=1, key="threads")
    st.write(f"Input root: `{INPUT_ROOT}`")
    st.write(f"Output root: `{OUTPUT_ROOT}`")
    if st.button("Refresh input scan"):
        fastq_rel, refs_rel = _scan_input(INPUT_ROOT)
        st.session_state.fastq_rel = fastq_rel
        st.session_state.refs_rel = refs_rel

elif st.session_state.step == 1:
    st.subheader("Samples")
    fastq_rel = st.session_state.fastq_rel
    st.write(f"FASTQ files found: {len(fastq_rel)}")
    if len(fastq_rel) == 0:
        st.error("No FASTQ files found under /input. Mount input data and refresh scan.")
        st.stop()

    st.checkbox("Auto-fill condition from sample", key="autofill_conditions")
    if not st.session_state.rows_initialized:
        st.session_state.rows_raw = _build_initial_rows(
            fastq_rel,
            st.session_state.paired,
            st.session_state.autofill_conditions,
        )
        st.session_state.rows_initialized = True

    if st.button("Auto-pair"):
        paired_rows = _auto_pair(_coerce_rows_raw(st.session_state.rows_raw), fastq_rel)
        canonical_rows, canonical_warnings = _canonicalize_rows_after_autopair(paired_rows, fastq_rel)
        st.session_state.rows_raw = canonical_rows
        st.session_state.auto_pair_warnings = canonical_warnings

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
                r2_in_fastq1.append(f"row {idx} ({row.get('sample', '')})")
        if r2_in_fastq1:
            issues.append("fastq1 looks like read2 in: " + ", ".join(r2_in_fastq1))
    auto_pair_warnings = st.session_state.get("auto_pair_warnings", [])
    if auto_pair_warnings:
        st.warning("Auto-pair canonicalization warnings:\n" + "\n".join(auto_pair_warnings))
    if issues:
        st.warning("Fix the following issues before saving:\n" + "\n".join(issues))

elif st.session_state.step == 2:
    st.subheader("Reference")
    manifest = _load_ref_manifest()
    st.checkbox("Use custom refs from /input", key="use_custom_refs")
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])

    if not st.session_state.use_custom_refs:
        st.session_state.ref_mode = "preset_cache"
        species = st.selectbox("Species", ["mouse", "human", "rat"], key="ref_species")
        presets = _species_presets(manifest, species)
        if not presets:
            st.error("No presets found in ref manifest.")
            st.stop()
        if st.session_state.ref_preset_name not in presets:
            st.session_state.ref_preset_name = presets[0]
        st.selectbox("Ref preset", presets, key="ref_preset_name")
        st.selectbox("Release", ["pinned", "latest"], key="ref_release")

        preset = st.session_state.ref_preset_name
        release = st.session_state.ref_release
        cache_paths = _cache_ref_paths(preset, release)
        cache_ok, rows = _cache_status(cache_paths)
        st.write(f"Cache directory: `{OUTPUT_ROOT / 'refs_cache' / preset / release}`")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if st.button("Fetch refs", disabled=cache_ok):
            code, output = _fetch_refs(preset, release)
            st.text_area("Fetch refs output", output or "(no output)", height=180)
            if code == 0:
                st.success("Reference fetch completed.")
                st.rerun()
            else:
                fetch_out = output or ""
                is_http_403 = (code == 43) or ("HTTP Error 403" in fetch_out) or ("HTTP 403" in fetch_out)
                if is_http_403:
                    st.error("Reference fetch failed: remote server returned HTTP 403 (Forbidden).")
                    st.warning(
                        "Try custom refs as fallback: place files under `/input/refs` and enable "
                        "`Use custom refs from /input`."
                    )
                    st.code(
                        "/input/refs/transcripts.fa.gz\n"
                        "/input/refs/genome.fa.gz\n"
                        "/input/refs/annotation.gtf.gz"
                    )
                else:
                    st.error(f"Reference fetch failed (exit {code})")

        if cache_ok:
            st.session_state.ref_transcripts = str(cache_paths["transcripts_fasta"])
            st.session_state.ref_genome = str(cache_paths["genome_fasta"])
            st.session_state.ref_gtf = str(cache_paths["gtf"])
            st.caption("Using cached preset refs under /output/refs_cache.")
        else:
            st.warning("Fetch refs to enable Save/Run.")
    else:
        mode = st.selectbox("Reference mode", ["fasta_gtf", "transcripts_only"], index=0, key="ref_mode")
        if mode in ("fasta_gtf", "transcripts_only") and not fasta_rel:
            st.error("No FASTA found under /input. Mount references and refresh scan.")
            st.stop()
        if mode == "fasta_gtf" and not gtf_rel:
            st.error("No GTF found under /input. Mount references and refresh scan.")
            st.stop()
        if mode == "transcripts_only":
            _ensure_ref_default("ref_transcripts", fasta_rel, ["transcript", "cdna"])
            st.selectbox("Transcripts FASTA", fasta_rel, key="ref_transcripts")
        else:
            _ensure_ref_default("ref_transcripts", fasta_rel, ["transcript", "cdna"])
            _ensure_ref_default("ref_genome", fasta_rel, ["genome"])
            _ensure_ref_default("ref_gtf", gtf_rel, ["gtf"])
            st.selectbox("Transcripts FASTA", fasta_rel, key="ref_transcripts")
            st.selectbox("Genome FASTA", fasta_rel, key="ref_genome")
            st.selectbox("GTF", gtf_rel, key="ref_gtf")

elif st.session_state.step == 3:
    st.subheader("Contrast + Advanced")
    levels = _get_conditions(st.session_state.rows_raw)
    st.write("Condition levels:", ", ".join(levels) if levels else "(none)")
    contrast_mode = st.selectbox("Contrast mode", ["ref", "pairwise", "select", "legacy"], index=0, key="contrast_mode")
    st.session_state.contrast_pairs = st.session_state.get("contrast_pairs", [])
    st.session_state.contrast_legacy = st.session_state.get("contrast_legacy", "")

    if contrast_mode == "ref":
        st.selectbox("Reference condition", levels, index=0 if levels else 0, key="contrast_ref", disabled=len(levels) == 0)
    elif contrast_mode == "pairwise":
        pass
    elif contrast_mode == "select":
        col_left, col_right, col_add = st.columns([2, 2, 1])
        with col_left:
            left = st.selectbox("A", levels, key="pair_left", disabled=len(levels) == 0)
        with col_right:
            right = st.selectbox("B", levels, key="pair_right", disabled=len(levels) == 0)
        with col_add:
            if st.button("Add pair"):
                if left and right and left != right:
                    st.session_state.contrast_pairs.append([left, right])
        if st.session_state.contrast_pairs:
            st.write("Selected pairs:")
            for idx, pair in enumerate(st.session_state.contrast_pairs):
                cols = st.columns([4, 1])
                cols[0].write(f"{pair[0]} vs {pair[1]}")
                if cols[1].button("Remove", key=f"pair_{idx}"):
                    st.session_state.contrast_pairs.pop(idx)
                    st.rerun()
    else:
        st.text_input("Legacy contrasts (comma-separated A_vs_B)", key="contrast_legacy")

    enable_enrich = st.checkbox("Enable enrichment", value=False, key="enrich_enable")
    if enable_enrich:
        methods = st.multiselect("Methods", ["ORA", "GSEA"], default=["ORA", "GSEA"], key="enrich_methods")
        alpha = st.number_input("Alpha (FDR)", min_value=0.0, max_value=1.0, value=0.05, step=0.01, key="enrich_alpha")
        lfc = st.number_input("Min abs(log2FC)", value=0.0, step=0.5, key="enrich_lfc")
        top_terms = st.number_input("Top terms", min_value=1, max_value=100, value=15, step=1, key="enrich_top")
        rank_metric = st.selectbox("Rank metric", ["stat"], index=0, key="enrich_rank")

else:
    st.subheader("Summary")
    _mount_status()
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
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])
    if ref_mode in ("transcripts_only", "fasta_gtf"):
        _ensure_ref_default("ref_transcripts", fasta_rel, ["transcript", "cdna"])
        if ref_mode == "fasta_gtf":
            _ensure_ref_default("ref_genome", fasta_rel, ["genome"])
            _ensure_ref_default("ref_gtf", gtf_rel, ["gtf"])
    st.caption(
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
    ref_block = {}
    ref_preset = None
    if ref_mode == "preset_cache":
        ref_preset = st.session_state.get("ref_preset_name", "")
        ref_block["transcripts_fasta"] = _normalize_ref(st.session_state.get("ref_transcripts", ""))
        ref_block["genome_fasta"] = _normalize_ref(st.session_state.get("ref_genome", ""))
        ref_block["gtf"] = _normalize_ref(st.session_state.get("ref_gtf", ""))
    elif ref_mode == "transcripts_only":
        ref_block["transcripts_fasta"] = _normalize_ref(st.session_state.get("ref_transcripts", ""))
    else:
        ref_block["transcripts_fasta"] = _normalize_ref(st.session_state.get("ref_transcripts", ""))
        ref_block["genome_fasta"] = _normalize_ref(st.session_state.get("ref_genome", ""))
        ref_block["gtf"] = _normalize_ref(st.session_state.get("ref_gtf", ""))

    payload = {
        "engine": st.session_state.get("engine", "real"),
        "samples": [row.get("sample", "") for row in rows_raw if row.get("sample")],
        "input": str(INPUT_ROOT),
        "output": str(OUTPUT_ROOT),
        "sample_table": str(OUTPUT_ROOT / "metadata" / "samples.tsv"),
        "threads": int(st.session_state.get("threads", 1)),
        "ref": ref_block,
    }
    if ref_preset:
        payload["ref_preset"] = ref_preset
        payload["ref_release"] = st.session_state.get("ref_release", "pinned")
        payload["species"] = st.session_state.get("ref_species", "mouse")
    elif use_custom_refs:
        payload["species"] = st.session_state.get("ref_species", "")
    if contrast_mode:
        payload["contrast_mode"] = contrast_mode
    if contrast_mode == "ref" and contrast_ref:
        payload["contrast_ref"] = contrast_ref
    if contrast_mode == "select" and contrast_pairs:
        payload["contrast_pairs"] = contrast_pairs
    if contrast_mode == "legacy" and contrasts:
        payload["contrasts"] = contrasts
    if st.session_state.get("enrich_enable"):
        payload["enrichment"] = {
            "enable": True,
            "methods": st.session_state.get("enrich_methods", ["ORA", "GSEA"]),
            "alpha": float(st.session_state.get("enrich_alpha", 0.05)),
            "lfc": float(st.session_state.get("enrich_lfc", 0.0)),
            "top_terms": int(st.session_state.get("enrich_top", 15)),
            "rank_metric": st.session_state.get("enrich_rank", "stat"),
        }

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
        invalid.append("samples missing")
    engine = st.session_state.get("engine", "real")
    if engine == "real" and len(conditions) < 2:
        invalid.append("need at least two condition levels for engine=real")
    if contrast_mode == "ref" and (not contrast_ref or contrast_ref not in conditions):
        invalid.append("invalid contrast_ref")
    if contrast_mode == "select":
        for a, b in contrast_pairs:
            if a not in conditions or b not in conditions:
                invalid.append(f"invalid pair {a}_vs_{b}")
    if contrast_mode == "legacy":
        for item in legacy_list:
            if "_vs_" in item:
                a, b = item.split("_vs_", 1)
                if a not in conditions or b not in conditions:
                    invalid.append(f"invalid legacy {item}")
    fastq_rel = st.session_state.fastq_rel
    row_issues = _validate_rows(rows_raw, fastq_rel, st.session_state.paired)
    if row_issues:
        invalid.extend(row_issues)

    ref_errors = _validate_refs(ref_mode, ref_block, st.session_state.refs_rel, ref_preset)
    if ref_errors:
        if any(err.startswith("missing ") for err in ref_errors):
            st.error("Reference not selected. Go back to Reference step.")
        fasta_rel = st.session_state.refs_rel.get("fasta", [])
        gtf_rel = st.session_state.refs_rel.get("gtf", [])
        candidates_info = f"FASTA candidates: {len(fasta_rel)}, GTF candidates: {len(gtf_rel)}"
        invalid.extend(ref_errors)
        st.error("Reference issues:\n" + "\n".join(sorted(set(ref_errors))) + f"\n\n{candidates_info}")
    if invalid:
        st.error("Save is disabled due to:")
        st.code("\n".join(map(str, invalid)))
        st.warning("Fix issues above to enable Save/Dry-run.")
        if st.button("Go to Reference"):
            st.session_state.step = 2
            st.rerun()

    config_path, samples_path, config_ok, samples_ok = _check_saved_outputs()
    output_write_ok, output_write_detail = _output_write_test()
    fingerprint = ""
    matching_runs = []
    if config_ok and samples_ok:
        fingerprint = _compute_input_fingerprint(config_path, samples_path, fastq_rel)
        matching_runs = _find_runs_by_fingerprint(fingerprint)

    run_options = ["start_new"]
    if matching_runs:
        run_options.extend(["open_last", "resume"])
    if st.session_state.run_mode not in run_options:
        st.session_state.run_mode = run_options[0]
    st.radio(
        "Run behavior",
        options=run_options,
        key="run_mode",
        format_func=lambda v: {
            "start_new": "Start new run directory",
            "open_last": "Open last report only (no compute)",
            "resume": "Resume last matching run (--rerun-incomplete style)",
        }[v],
        horizontal=True,
    )
    if matching_runs:
        st.caption(f"Found {len(matching_runs)} previous run(s) with same input fingerprint.")
        st.code("\n".join([str(item[0]) for item in matching_runs[:8]]))

    preview_run_dir = (
        matching_runs[0][0]
        if st.session_state.run_mode in ("open_last", "resume") and matching_runs
        else (RUNS_ROOT / "[new run_id]")
    )
    st.caption(f"Current run dir: {preview_run_dir}")

    run_blockers = list(invalid)
    if not config_ok:
        run_blockers.append("missing /output/config.yaml (save first)")
    if not samples_ok:
        run_blockers.append("missing /output/metadata/samples.tsv (save first)")
    if len(fastq_rel) == 0:
        run_blockers.append("No FASTQ found under /input. Confirm Docker mounts: -v <host>:/input:ro")
    if not output_write_ok:
        run_blockers.append("cannot write to /output (mount/permissions issue)")

    st.caption(
        "Run precheck: "
        f"config_ok={config_ok} samples_ok={samples_ok} fastq_count={len(fastq_rel)} output_writable={output_write_ok}"
    )
    if output_write_detail and not output_write_ok:
        st.code(output_write_detail)

    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        if st.button("Save", disabled=bool(invalid)):
            try:
                rows_norm = _normalize_rows(
                    rows_raw,
                    st.session_state.paired,
                    fastq_rel,
                    st.session_state.autofill_conditions,
                )
                save_issues = _validate_rows(rows_norm, fastq_rel, st.session_state.paired)
                if save_issues:
                    st.error("Cannot save due to normalized row issues:")
                    st.code("\n".join(save_issues))
                else:
                    payload_to_save = dict(payload)
                    payload_to_save["samples"] = [row.get("sample", "") for row in rows_norm if row.get("sample")]
                    _write_config_and_samples(payload_to_save, rows_norm, st.session_state.paired)
                    config_path, samples_path, config_ok, samples_ok = _check_saved_outputs()
                    st.write("Save results:")
                    st.code(_path_info(config_path))
                    st.code(_path_info(samples_path))
                    if config_ok and samples_ok:
                        st.session_state.saved = True
                        st.success("Saved OK")
                    else:
                        st.session_state.saved = False
                        missing = []
                        if not config_ok:
                            missing.append(str(config_path))
                        if not samples_ok:
                            missing.append(str(samples_path))
                        st.error("Save failed: missing or empty -> " + ", ".join(missing))
                        st.error("Output mount looks wrong. Check that OUT is mounted to /output and is writable.")
            except Exception as e:
                st.session_state.saved = False
                st.exception(e)
            entries = _list_output_dir()
            st.write("/output contents:")
            st.code("\n".join(entries) if entries else "(empty)")

    if not config_ok:
        st.warning("Save first to generate /output/config.yaml and /output/metadata/samples.tsv before Validate.")
    with col_b:
        if st.button("Validate", disabled=bool(invalid) or not config_ok):
            code, output = _run_cmd(
                ["python", "-m", "app", "validate", "--config", str(config_path), "--input", str(INPUT_ROOT), "--output", str(OUTPUT_ROOT)]
            )
            st.text_area("Validate output", output or "(no output)", height=200)
            if code == 0:
                st.success("Validation OK")
            else:
                st.error(f"Validation failed (exit {code})")
    with col_c:
        if st.button("Dry-run", disabled=bool(invalid) or not config_ok):
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
            code, output = _run_cmd(cmd)
            st.text_area("Dry-run output", output or "(no output)", height=200)
            if code == 0:
                st.success("Dry-run OK")
            else:
                st.error(f"Dry-run failed (exit {code})")
    with col_d:
        run_in_progress = st.session_state.get("run_status") == "running"
        open_last_mode = st.session_state.run_mode == "open_last"
        run_disabled = run_in_progress or (bool(run_blockers) and not open_last_mode) or (open_last_mode and not matching_runs)
        if st.button("Run (report)", disabled=run_disabled):
            if open_last_mode and matching_runs:
                st.session_state.run_dir = str(matching_runs[0][0])
                st.session_state.run_status = "success"
                st.session_state.run_rc = 0
                st.session_state.run_log = "Open last report selected. No compute executed.\n"
                st.rerun()

            run_dir = _prepare_run_dir(st.session_state.run_mode, fingerprint, matching_runs)
            run_cfg = _write_run_config(run_dir, payload)
            now_utc = datetime.now(timezone.utc)
            metadata = {
                "created_at_utc": now_utc.isoformat(),
                "created_at_jst": now_utc.astimezone(JST).strftime("%Y-%m-%dT%H:%M:%S%z"),
                "git_rev": _git_rev(),
                "input_fingerprint": fingerprint,
                "species": st.session_state.get("ref_species", ""),
                "ref_preset": st.session_state.get("ref_preset_name", ""),
                "threads": int(st.session_state.get("threads", 1)),
                "engine": st.session_state.get("engine", "real"),
            }
            _write_run_metadata(run_dir, metadata)
            _start_run_report(
                st.session_state.get("engine", "real"),
                int(st.session_state.get("threads", 1)),
                run_dir,
                run_cfg,
                ["--rerun-incomplete"] if st.session_state.run_mode == "resume" else [],
            )
            st.rerun()

    if run_blockers and st.session_state.run_mode != "open_last":
        st.error("Run is disabled due to:")
        st.code("\n".join(sorted(set(run_blockers))))

    run_status = st.session_state.get("run_status", "idle")
    run_log_text = st.session_state.get("run_log", "")
    active_run_dir = Path(st.session_state.run_dir) if st.session_state.get("run_dir") else None
    report_path = (active_run_dir / "report" / "report.html") if active_run_dir else (OUTPUT_ROOT / "report" / "report.html")
    if active_run_dir:
        st.caption(f"Active run dir: {active_run_dir}")
    if run_status != "idle" or run_log_text:
        if run_status == "running":
            st.info("Run status: running")
            if st.button("Stop run"):
                _stop_run_process()
                st.rerun()
        elif run_status == "success":
            st.success("Run status: success")
        elif run_status == "stopped":
            st.warning(f"Run status: stopped (exit {st.session_state.get('run_rc')})")
        else:
            st.error(f"Run status: failed (exit {st.session_state.get('run_rc')})")
            st.warning("Check run_dir/logs and /output/.snakemake/log for detailed failure logs.")

        st.text_area("Run output (live)", run_log_text or "(no output yet)", height=280)

        if run_status == "success":
            st.success(f"Report: {report_path}")
            st.info("For host path opening, use `just open-out` or README open-out guidance.")
            if report_path.exists():
                if st.button("Check self-contained report"):
                    code, output = _run_cmd(
                        [
                            "python",
                            "/app/scripts/check_report_selfcontained.py",
                            "--report",
                            str(report_path),
                        ]
                    )
                    st.text_area("Self-contained check output", output or "(no output)", height=180)
                    if code == 0:
                        st.success("Self-contained report OK")
                    else:
                        st.error(f"Self-contained check failed (exit {code})")

    if st.session_state.get("run_status") == "running":
        time.sleep(0.5)
        st.rerun()
