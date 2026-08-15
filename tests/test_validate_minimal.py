import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "tests" / "data"


def _write_yaml(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def _run_validate(config_path, input_dir, output_dir):
    cmd = [
        sys.executable,
        "-m",
        "app",
        "validate",
        "--config",
        str(config_path),
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
        "--skip-toolcheck",
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    if not INPUT_DIR.exists():
        raise SystemExit("tests/data not found")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        output_dir = tmp / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        sample_table = tmp / "samples.tsv"
        sample_table.write_text(
            "sample\tcondition\tfastq1\n"
            "sample1\tA\tsample1.fastq\n"
            "sample2\tB\tsample2.fastq\n",
            encoding="utf-8",
        )

        config_transcripts_only = tmp / "config_transcripts_only.yaml"
        _write_yaml(
            config_transcripts_only,
            {
                "engine": "real",
                "library_protocol": "full_length",
                "input": str(INPUT_DIR),
                "output": str(output_dir),
                "sample_table": str(sample_table),
                "contrast_mode": "select",
                "contrast_pairs": [["A", "B"]],
                "ref": {"transcripts_fasta": "transcripts.fa"},
            },
        )
        result = _run_validate(config_transcripts_only, INPUT_DIR, output_dir)
        if result.returncode != 0:
            raise SystemExit(f"transcripts_only validate failed:\n{result.stdout}\n{result.stderr}")

        config_fasta_gtf = tmp / "config_fasta_gtf.yaml"
        _write_yaml(
            config_fasta_gtf,
            {
                "engine": "real",
                "library_protocol": "full_length",
                "input": str(INPUT_DIR),
                "output": str(output_dir),
                "sample_table": str(sample_table),
                "contrast_mode": "pairwise",
                "ref": {
                    "transcripts_fasta": "transcripts.fa",
                    "genome_fasta": "genome.fa",
                    "gtf": "genes.gtf",
                },
            },
        )
        result = _run_validate(config_fasta_gtf, INPUT_DIR, output_dir)
        if result.returncode != 0:
            raise SystemExit(f"fasta_gtf validate failed:\n{result.stdout}\n{result.stderr}")

        config_legacy = tmp / "config_legacy.yaml"
        _write_yaml(
            config_legacy,
            {
                "engine": "real",
                "library_protocol": "full_length",
                "input": str(INPUT_DIR),
                "output": str(output_dir),
                "sample_table": str(sample_table),
                "contrast_mode": "legacy",
                "contrasts": ["A_vs_B"],
                "ref": {"transcripts_fasta": "transcripts.fa"},
            },
        )
        result = _run_validate(config_legacy, INPUT_DIR, output_dir)
        if result.returncode == 0:
            raise SystemExit("legacy contrast unexpectedly validated successfully")
        if "Legacy contrasts" not in (result.stdout + result.stderr):
            raise SystemExit("legacy contrast error message missing")


if __name__ == "__main__":
    main()
