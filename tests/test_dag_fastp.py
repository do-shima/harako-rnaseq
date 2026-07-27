import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def _extract_rule_block(text, rule_name):
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.startswith(f"rule {rule_name}:"):
            start = idx + 1
            break
    if start is None:
        return []
    block = []
    for line in lines[start:]:
        if line.startswith("rule ") and line.endswith(":"):
            break
        block.append(line.strip())
    return block


def _run_dry(engine):
    repo = Path(__file__).resolve().parents[1]
    outdir = repo / "tests" / f"out_dag_{engine}"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cfg = {
        "engine": engine,
        "species": "mouse",
        "samples": ["sample1"],
        "input": str(repo / "tests" / "data"),
        "output": str(outdir),
        "fastq": {"sample1": "sample1.fastq.gz"},
        "conditions": {"sample1": "A"},
        "analysis_plan": {
            "schema_version": 1,
            "policy_version": 1,
            "mode": "qc_only",
            "structurally_valid": True,
            "eligible_for_de": False,
            "reason_code": "single_condition",
            "condition_counts": {"A": 1},
            "total_samples": 1,
            "contrast_allowed": False,
            "enrichment_allowed": False,
        },
        "ref": {
            "transcripts_fasta": "transcripts.fa",
            "genome_fasta": "genome.fa",
            "gtf": "genes.gtf",
        },
    }
    cfg_path = outdir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "snakemake",
        "--directory",
        str(outdir),
        "-s",
        "workflow/Snakefile",
        "--configfile",
        str(cfg_path),
        "--config",
        f"input={repo / 'tests' / 'data'}",
        f"output={outdir}",
        "--cores",
        "1",
        "-n",
        "-p",
        "report",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise SystemExit(f"snakemake -n failed for engine={engine}:\n{output}")

    fastp_path = outdir / "fastp" / "sample1.fastq"
    salmon_block = _extract_rule_block(output, "salmon_quant")
    fastp_block = _extract_rule_block(output, "fastp")

    if not fastp_block:
        raise SystemExit(f"fastp rule missing in dry-run output for engine={engine}")
    if not salmon_block:
        raise SystemExit(f"salmon_quant rule missing in dry-run output for engine={engine}")

    salmon_text = " ".join(salmon_block)
    if str(fastp_path) not in salmon_text:
        raise SystemExit(
            f"fastp output not wired into salmon_quant for engine={engine}. "
            f"expected {fastp_path} in salmon_quant input."
        )


def main():
    for engine in ("stub", "real"):
        _run_dry(engine)


if __name__ == "__main__":
    main()
