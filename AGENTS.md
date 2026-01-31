# Project: rnaseq_pipeline (Docker + Snakemake)

Goals
- Provide a single entrypoint: `python -m app run ...` (run.py is OK too).
- Workflow engine must remain Snakemake for resumability.
- Alignment is optional: default none; explicit --align star|hisat2 enables it.
- References:
  - Presets: human/mouse=GENCODE, rat=Ensembl.
  - Use a pinned ref manifest file (no hard-coded URLs in code).
  - Support user-provided FASTA+GTF.
  - Salmon index: decoy-aware when genome is available; fallback to transcripts-only.
- Outputs: under `out/` with stable paths; never change output paths without migration notes.
- Always provide a static HTML report: `out/report/report.html` (MultiQC + summary).
- Provide `just build`, `just smoke`, `just run` targets. Smoke must finish end-to-end without network download.

Constraints
- Do not commit large data. Keep tests small (KB–MB).
- Keep Dockerfile single-image (all-in-one) for now.
- Any new feature must update README and smoke tests.
