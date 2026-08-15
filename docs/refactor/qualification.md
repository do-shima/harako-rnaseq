# Refactor qualification record

The baseline is recorded in [baseline.md](baseline.md). Final results are
filled from the exact committed refactor candidate; an unexecuted check is not
reported as passing.

| Command or gate | Final result | Notes |
|---|---|---|
| Python compile | PASS | 134 Python files |
| full host pytest | PASS | 411 passed, 12 skipped, 2 pre-existing dependency warnings |
| agent smoke / verification | PASS | both baseline plan IDs and approval hashes matched exactly |
| smoke / verification | PASS | stable outputs and self-contained report present |
| release readiness | PASS | strict current-version gate; 12 reference hashes |
| `just ci-host` | PASS | 411 passed, 12 skipped |
| `just ci-docker` | PASS | 421 passed, 2 skipped; real R/scientific fixtures |
| GUI localhost/doctor | PASS | import doctor and live `/_stcore/health`; Streamlit 1.60.0 |
| canonical artifact comparison | PASS | baseline/final file inventory matched; 10 stable artifacts matched byte-for-byte |
| `git diff --check` | PASS | checked against the start commit and before final documentation commit |

Environment limitations remain the same as baseline: host Java and host
Snakemake are unavailable; supported Docker qualification supplies Snakemake,
R, and the scientific toolchain.

The final `rnaseq_pipeline:ci` image was
`sha256:5a4404ea68375fc0196034bd3524e6cfa0b49978feb45e611eacf9e25f158bc3`
(`amd64`, 1,186,296,134 bytes). It contained Python 3.11.15, R 4.5.0,
Snakemake 9.13.4, fastp 0.23.4, Salmon 1.10.0, DESeq2 1.48.2, and tximport
1.36.1.

Docker pytest covered real tximport and DESeq2, full-length and 3′-tag
handoffs, legacy frozen runs, differential and QC-only modes, schema-v1 agent
plans, report generation, and the existing output contracts. The baseline and
final deterministic stub comparison matched `fastp` FASTQ/JSON/HTML, Salmon
`quant.sf`, tximport counts, DESeq2 results/status/normalized counts, and both
QC summary files exactly. Timestamped logs, runtime provenance, and report HTML
were intentionally not byte-compared.
