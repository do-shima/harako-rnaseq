import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "srr_fetch.py"


def _write_fastq_gz(path: Path, read_name: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"@{read_name}\nACGT\n+\n!!!!\n".encode("utf-8")
    with gzip.open(path, "wb") as handle:
        handle.write(payload)
    return hashlib.md5(path.read_bytes()).hexdigest()


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_run_table_mixed_layout_condition_default_blank():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        repo = tmp / "repo"
        repo.mkdir(parents=True, exist_ok=True)

        src = tmp / "src"
        md5_r1 = _write_fastq_gz(src / "A_1.fastq.gz", "A1")
        md5_r2 = _write_fastq_gz(src / "A_2.fastq.gz", "A2")
        md5_b = _write_fastq_gz(src / "B.fastq.gz", "B1")

        table = tmp / "SraRunTable.txt"
        table.write_text(
            "Run\tSampleName\tGroup\n"
            "SRR100001\tAlpha sample\tCase\n"
            "ERR200002\tBeta.Sample\tControl\n",
            encoding="utf-8",
        )

        fixture = tmp / "ena_fixture.json"
        fixture.write_text(
            json.dumps(
                {
                    "SRR100001": {
                        "run_accession": "SRR100001",
                        "library_layout": "PAIRED",
                        "fastq_ftp": f"file://{(src / 'A_1.fastq.gz').as_posix()};file://{(src / 'A_2.fastq.gz').as_posix()}",
                        "fastq_md5": f"{md5_r1};{md5_r2}",
                    },
                    "ERR200002": {
                        "run_accession": "ERR200002",
                        "library_layout": "SINGLE",
                        "fastq_ftp": f"file://{(src / 'B.fastq.gz').as_posix()}",
                        "fastq_md5": md5_b,
                    },
                }
            ),
            encoding="utf-8",
        )

        cmd = [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo),
            "--input-file",
            str(table),
            "--ena-fixture",
            str(fixture),
            "--emit-run-id",
        ]
        result = _run(cmd)
        assert result.returncode == 0, result.stderr
        run_id = result.stdout.strip()
        assert run_id.startswith("run_"), run_id

        samples_tsv = repo / "data_in" / "srr" / run_id / "metadata" / "samples.tsv"
        lines = samples_tsv.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "sample\tcondition\tfastq1\tfastq2"
        assert "Alpha_sample\t\tfastq/Alpha_sample_R1.fastq.gz\tfastq/Alpha_sample_R2.fastq.gz" in lines
        assert any(line.startswith("Beta.Sample\t\tfastq/Beta.Sample_R1.fastq.gz\t") for line in lines), lines


def test_accession_list_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        repo = tmp / "repo"
        repo.mkdir(parents=True, exist_ok=True)

        src = tmp / "src"
        md5_r1 = _write_fastq_gz(src / "C.fastq.gz", "C1")

        accession_list = tmp / "runs.txt"
        accession_list.write_text("# comment\nDRR300003\n", encoding="utf-8")

        fixture = tmp / "ena_fixture.json"
        fixture.write_text(
            json.dumps(
                {
                    "DRR300003": {
                        "run_accession": "DRR300003",
                        "library_layout": "SINGLE",
                        "fastq_ftp": f"file://{(src / 'C.fastq.gz').as_posix()}",
                        "fastq_md5": md5_r1,
                    }
                }
            ),
            encoding="utf-8",
        )

        cmd = [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo),
            "--input-file",
            str(accession_list),
            "--ena-fixture",
            str(fixture),
            "--emit-run-id",
        ]
        result = _run(cmd)
        assert result.returncode == 0, result.stderr
        run_id = result.stdout.strip()

        samples_tsv = repo / "data_in" / "srr" / run_id / "metadata" / "samples.tsv"
        lines = samples_tsv.read_text(encoding="utf-8").splitlines()
        assert any(line.startswith("DRR300003\t\tfastq/DRR300003_R1.fastq.gz\t") for line in lines)


def main():
    test_run_table_mixed_layout_condition_default_blank()
    test_accession_list_mode()


if __name__ == "__main__":
    main()
