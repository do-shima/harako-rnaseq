import os
import re
import subprocess
from pathlib import Path

import streamlit as st
import yaml


INPUT_ROOT = Path("/input")
OUTPUT_ROOT = Path("/output")


def _scan_fastq(root: Path):
    exts = (".fastq", ".fastq.gz", ".fq", ".fq.gz")
    files = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and path.name.lower().endswith(exts):
                files.append(path)
    return sorted(files)


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


def _infer_pair(name: str):
    patterns = [
        (r"(.*)(?:_R?1|_1)(\.[^.]+(\.gz)?)$", r"\1_R2\2"),
        (r"(.*)(?:_R?1|_1)(\.[^.]+(\.gz)?)$", r"\1_2\2"),
    ]
    for pat, repl in patterns:
        if re.match(pat, name):
            return re.sub(pat, repl, name)
    return ""


def _auto_pair(rows, available):
    available_set = set(available)
    for row in rows:
        if row.get("fastq2"):
            continue
        fq1 = row.get("fastq1", "")
        if not fq1:
            continue
        candidate = _infer_pair(fq1)
        if candidate and candidate in available_set:
            row["fastq2"] = candidate
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
            values = [row.get("sample", ""), row.get("condition", ""), row.get("fastq1", "")]
            if paired:
                values.append(row.get("fastq2", ""))
            handle.write("\t".join(values) + "\n")
    return out_path


def _write_config(payload):
    output_dir = OUTPUT_ROOT
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "config.yaml"
    with out_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)
    return out_path


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


st.set_page_config(page_title="RNA-seq Init UI", layout="wide")

if "step" not in st.session_state:
    st.session_state.step = 0
if "rows" not in st.session_state:
    st.session_state.rows = []
if "paired" not in st.session_state:
    st.session_state.paired = False

steps = ["Project", "Samples", "Reference", "Advanced", "Summary"]

st.title("RNA-seq Init (Web UI)")
st.caption("Input is fixed to /input, output is fixed to /output.")

col1, col2 = st.columns([3, 1])
with col1:
    st.progress((st.session_state.step + 1) / len(steps))
with col2:
    st.write(f"Step {st.session_state.step + 1} / {len(steps)}: {steps[st.session_state.step]}")


def _nav_buttons():
    left, right = st.columns(2)
    with left:
        if st.button("Back", disabled=st.session_state.step == 0):
            st.session_state.step -= 1
            st.rerun()
    with right:
        if st.button("Next", disabled=st.session_state.step == len(steps) - 1):
            st.session_state.step += 1
            st.rerun()


if st.session_state.step == 0:
    st.subheader("Project / Basic")
    engine = st.selectbox("Engine", ["real", "stub"], index=0, key="engine")
    paired = st.checkbox("Paired-end reads", value=st.session_state.paired)
    st.session_state.paired = paired
    threads = st.number_input("Threads", min_value=1, max_value=64, value=1, step=1, key="threads")
    st.write(f"Input root: `{INPUT_ROOT}`")
    st.write(f"Output root: `{OUTPUT_ROOT}`")
    _nav_buttons()

elif st.session_state.step == 1:
    st.subheader("Samples")
    fastq_files = _scan_fastq(INPUT_ROOT)
    fastq_rel = [_rel(p) for p in fastq_files]
    st.write(f"FASTQ files found: {len(fastq_rel)}")
    if st.button("Auto-pair"):
        st.session_state.rows = _auto_pair(st.session_state.rows, fastq_rel)

    if not st.session_state.rows:
        for fq in fastq_rel:
            st.session_state.rows.append({"sample": Path(fq).stem, "condition": "", "fastq1": fq, "fastq2": ""})

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

    edited = st.data_editor(
        st.session_state.rows,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )
    st.session_state.rows = [{k: row.get(k, "") for k in cols} for row in edited]

    missing = []
    for idx, row in enumerate(st.session_state.rows, start=1):
        fq1 = row.get("fastq1", "")
        fq2 = row.get("fastq2", "")
        if not fq1 or fq1 not in fastq_rel:
            missing.append(f"row {idx}: fastq1 not found ({fq1})")
        if st.session_state.paired and (not fq2 or fq2 not in fastq_rel):
            missing.append(f"row {idx}: fastq2 not found ({fq2})")
    if missing:
        st.warning("Missing or invalid FASTQ paths:\n" + "\n".join(missing))

    _nav_buttons()

elif st.session_state.step == 2:
    st.subheader("Reference")
    mode = st.selectbox("Reference mode", ["fasta_gtf", "preset", "transcripts_only"], index=0, key="ref_mode")
    fasta, gtf = _scan_refs(INPUT_ROOT)
    fasta_rel = [_rel(p) for p in fasta]
    gtf_rel = [_rel(p) for p in gtf]

    if mode == "preset":
        st.selectbox("Species preset", ["mouse", "human", "rat"], index=0, key="ref_species")
    elif mode == "transcripts_only":
        st.selectbox("Transcripts FASTA", fasta_rel, key="ref_transcripts")
    else:
        st.selectbox("Transcripts FASTA", fasta_rel, key="ref_transcripts")
        st.selectbox("Genome FASTA", fasta_rel, key="ref_genome")
        st.selectbox("GTF", gtf_rel, key="ref_gtf")

    _nav_buttons()

elif st.session_state.step == 3:
    st.subheader("Advanced")
    enable_enrich = st.checkbox("Enable enrichment", value=False, key="enrich_enable")
    if enable_enrich:
        methods = st.multiselect("Methods", ["ORA", "GSEA"], default=["ORA", "GSEA"], key="enrich_methods")
        alpha = st.number_input("Alpha (FDR)", min_value=0.0, max_value=1.0, value=0.05, step=0.01, key="enrich_alpha")
        lfc = st.number_input("Min abs(log2FC)", value=0.0, step=0.5, key="enrich_lfc")
        top_terms = st.number_input("Top terms", min_value=1, max_value=100, value=15, step=1, key="enrich_top")
        rank_metric = st.selectbox("Rank metric", ["stat"], index=0, key="enrich_rank")
    _nav_buttons()

else:
    st.subheader("Summary")
    conditions = _get_conditions(st.session_state.rows)
    col_left, col_right = st.columns(2)
    with col_left:
        left = st.selectbox("Contrast A", conditions, index=0 if conditions else 0, key="contrast_a", disabled=len(conditions) == 0)
    with col_right:
        right = st.selectbox("Contrast B", conditions, index=1 if len(conditions) > 1 else 0, key="contrast_b", disabled=len(conditions) == 0)

    contrasts = _build_contrast(st.session_state.rows, left, right)

    ref_mode = st.session_state.get("ref_mode", "fasta_gtf")
    ref_block = {}
    if ref_mode == "preset":
        ref_preset = st.session_state.get("ref_species", "mouse")
    else:
        ref_preset = None
        if ref_mode == "transcripts_only":
            ref_block["transcripts_fasta"] = st.session_state.get("ref_transcripts", "")
        else:
            ref_block["transcripts_fasta"] = st.session_state.get("ref_transcripts", "")
            ref_block["genome_fasta"] = st.session_state.get("ref_genome", "")
            ref_block["gtf"] = st.session_state.get("ref_gtf", "")

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
    if contrasts:
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
    with col_a:
        if st.button("Save"):
            samples_path = _write_samples(st.session_state.rows, st.session_state.paired)
            config_path = _write_config(payload)
            st.success(f"Saved: {config_path} and {samples_path}")
    with col_b:
        if st.button("Validate"):
            code, output = _run_cmd(
                ["python", "-m", "app", "validate", "--config", str(OUTPUT_ROOT / "config.yaml"),
                 "--input", str(INPUT_ROOT), "--output", str(OUTPUT_ROOT)]
            )
            st.text_area("Validate output", output or "(no output)", height=200)
            if code == 0:
                st.success("Validation OK")
            else:
                st.error(f"Validation failed (exit {code})")
    with col_c:
        if st.button("Dry-run"):
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
