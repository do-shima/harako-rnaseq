import os
import re
import subprocess
from pathlib import Path

import streamlit as st
import yaml


INPUT_ROOT = Path("/input")
OUTPUT_ROOT = Path("/output")
UI_MOUNT_NOTE = "Input=/input and Output=/output must be mounted. Choose host paths via the launcher or `just ui`."
FASTQ_EXTS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


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
        tag = match.group("tag").upper()
        return (
            match.group("prefix"),
            "1" if tag.endswith("1") else "2",
            bool(tag.startswith("R")),
            match.group("sep"),
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
    if not paired:
        return [_new_row(fq, condition_from_sample) for fq in fastq_rel]

    available = set(fastq_rel)
    rows = []
    used = set()
    r1_candidates = [fq for fq in fastq_rel if _is_r1(fq)]

    if r1_candidates:
        for fq in r1_candidates:
            if fq in used:
                continue
            mate = ""
            for candidate in _infer_pair_candidates(fq):
                if candidate in available:
                    mate = candidate
                    used.add(candidate)
                    break
            rows.append(_new_row(fq, condition_from_sample, mate))
            used.add(fq)
        for fq in fastq_rel:
            if fq in used or _read_side(fq) == "2":
                continue
            rows.append(_new_row(fq, condition_from_sample))
        return rows

    # Fallback: no obvious R1 names, keep all non-R2 files as individual rows.
    fallback = [fq for fq in fastq_rel if _read_side(fq) != "2"]
    if fallback:
        return [_new_row(fq, condition_from_sample) for fq in fallback]
    return [_new_row(fq, condition_from_sample) for fq in fastq_rel]


def _coerce_editor_rows(edited):
    if edited is None:
        return []
    if isinstance(edited, list):
        return edited
    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")
    return list(edited)


def _validate_rows(rows, fastq_rel, paired):
    issues = []
    seen = set()
    for idx, row in enumerate(rows, start=1):
        sample = row.get("sample", "")
        cond = row.get("condition", "")
        fq1 = _normalize_input_value(row.get("fastq1", ""))
        fq2 = _normalize_input_value(row.get("fastq2", ""))
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
    if ref_mode == "fasta_gtf":
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


def _auto_pair(rows, available):
    available_set = set(available)
    for row in rows:
        if row.get("fastq2"):
            continue
        fq1 = _normalize_input_value(row.get("fastq1", ""))
        if not fq1:
            continue
        for candidate in _infer_pair_candidates(fq1):
            if candidate in available_set:
                row["fastq2"] = candidate
                break
    return rows


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


def _run_cmd(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, output.strip()


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
if "rows" not in st.session_state:
    st.session_state.rows = []
if "rows_initialized" not in st.session_state:
    st.session_state.rows_initialized = False
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
        if st.session_state.rows:
            if paired:
                st.session_state.rows = _auto_pair(st.session_state.rows, st.session_state.fastq_rel)
        else:
            st.session_state.rows_initialized = False
    threads = st.number_input("Threads", min_value=1, max_value=64, value=1, step=1, key="threads")
    st.write(f"Input root: `{INPUT_ROOT}`")
    st.write(f"Output root: `{OUTPUT_ROOT}`")
    if st.button("Refresh input scan"):
        fastq_rel, refs_rel = _scan_input(INPUT_ROOT)
        st.session_state.fastq_rel = fastq_rel
        st.session_state.refs_rel = refs_rel
        st.session_state.rows = []
        st.session_state.rows_initialized = False

elif st.session_state.step == 1:
    st.subheader("Samples")
    fastq_rel = st.session_state.fastq_rel
    st.write(f"FASTQ files found: {len(fastq_rel)}")
    if len(fastq_rel) == 0:
        st.error("No FASTQ files found under /input. Mount input data and refresh scan.")
        st.stop()

    st.checkbox("Auto-fill condition from sample", key="autofill_conditions")
    if not st.session_state.rows_initialized:
        st.session_state.rows = _build_initial_rows(
            fastq_rel,
            st.session_state.paired,
            st.session_state.autofill_conditions,
        )
        st.session_state.rows_initialized = True

    if st.button("Auto-pair"):
        st.session_state.rows = _auto_pair(st.session_state.rows, fastq_rel)

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

    editor_rows = [{k: row.get(k, "") for k in cols} for row in st.session_state.rows]
    edited = st.data_editor(
        editor_rows,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        key="samples_editor",
    )
    edited_rows = _coerce_editor_rows(edited)
    normalized_rows = []
    for idx, row in enumerate(edited_rows):
        previous = st.session_state.rows[idx] if idx < len(st.session_state.rows) else {}
        normalized_rows.append(
            {
                "sample": row.get("sample", ""),
                "condition": row.get("condition", ""),
                "fastq1": _normalize_input_value(row.get("fastq1", "")),
                "fastq2": _normalize_input_value(row.get("fastq2", previous.get("fastq2", ""))),
            }
        )
    st.session_state.rows = normalized_rows

    issues = _validate_rows(st.session_state.rows, fastq_rel, st.session_state.paired)
    if st.session_state.paired:
        r2_in_fastq1 = []
        for idx, row in enumerate(st.session_state.rows, start=1):
            if _read_side(row.get("fastq1", "")) == "2":
                r2_in_fastq1.append(f"row {idx} ({row.get('sample', '')})")
        if r2_in_fastq1:
            issues.append("fastq1 looks like read2 in: " + ", ".join(r2_in_fastq1))
    if issues:
        st.warning("Fix the following issues before saving:\n" + "\n".join(issues))

elif st.session_state.step == 2:
    st.subheader("Reference")
    mode = st.selectbox("Reference mode", ["fasta_gtf", "preset", "transcripts_only"], index=0, key="ref_mode")
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])

    if mode in ("fasta_gtf", "transcripts_only") and not fasta_rel:
        st.error("No FASTA found under /input. Mount references and refresh scan.")
        st.stop()
    if mode == "fasta_gtf" and not gtf_rel:
        st.error("No GTF found under /input. Mount references and refresh scan.")
        st.stop()

    if mode == "preset":
        st.selectbox("Species preset", ["mouse", "human", "rat"], index=0, key="ref_species")
    elif mode == "transcripts_only":
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
    levels = _get_conditions(st.session_state.rows)
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
    conditions = _get_conditions(st.session_state.rows)
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
    if ref_mode == "preset":
        ref_preset = st.session_state.get("ref_species", "mouse")
    else:
        ref_preset = None
    if ref_mode == "transcripts_only":
        ref_block["transcripts_fasta"] = _normalize_ref(st.session_state.get("ref_transcripts", ""))
    else:
        ref_block["transcripts_fasta"] = _normalize_ref(st.session_state.get("ref_transcripts", ""))
        ref_block["genome_fasta"] = _normalize_ref(st.session_state.get("ref_genome", ""))
        ref_block["gtf"] = _normalize_ref(st.session_state.get("ref_gtf", ""))

    payload = {
        "engine": st.session_state.get("engine", "real"),
        "samples": [row.get("sample", "") for row in st.session_state.rows if row.get("sample")],
        "input": str(INPUT_ROOT),
        "output": str(OUTPUT_ROOT),
        "sample_table": str(OUTPUT_ROOT / "metadata" / "samples.tsv"),
        "threads": int(st.session_state.get("threads", 1)),
        "ref": ref_block,
    }
    if ref_preset:
        payload["ref_preset"] = ref_preset
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
        ["\t".join([row.get(k, "") for k in sample_header]) for row in st.session_state.rows]
    ))

    col_a, col_b, col_c = st.columns(3)
    invalid = []
    if not st.session_state.rows:
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
    row_issues = _validate_rows(st.session_state.rows, fastq_rel, st.session_state.paired)
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

    with col_a:
        if st.button("Save", disabled=bool(invalid)):
            try:
                _write_config_and_samples(payload, st.session_state.rows, st.session_state.paired)
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
    config_path = OUTPUT_ROOT / "config.yaml"
    config_exists = config_path.exists()
    if not config_exists:
        st.warning("Save first to generate /output/config.yaml and /output/metadata/samples.tsv before Validate.")
    with col_b:
        if st.button("Validate", disabled=bool(invalid) or not config_exists):
            code, output = _run_cmd(
                ["python", "-m", "app", "validate", "--config", str(config_path),
                 "--input", str(INPUT_ROOT), "--output", str(OUTPUT_ROOT)]
            )
            st.text_area("Validate output", output or "(no output)", height=200)
            if code == 0:
                st.success("Validation OK")
            else:
                st.error(f"Validation failed (exit {code})")
    with col_c:
        if st.button("Dry-run", disabled=bool(invalid) or not config_exists):
            cmd = [
                "python", "-m", "snakemake",
                "--directory", str(OUTPUT_ROOT),
                "-s", "workflow/Snakefile",
                "--configfile", str(OUTPUT_ROOT / "config.yaml"),
                "--config", "input=/input", "output=/output",
                "--cores", "1", "-n", "-p", "--", "report",
            ]
            code, output = _run_cmd(cmd)
            st.text_area("Dry-run output", output or "(no output)", height=200)
            if code == 0:
                st.success("Dry-run OK")
            else:
                st.error(f"Dry-run failed (exit {code})")
