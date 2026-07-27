# Harako-RNAseq maintainer guidance

This file describes development constraints for maintainers and coding agents.
It is not end-user documentation.

## Architecture

- Keep `python -m app run ...` as the application entry point.
- Keep Snakemake as the workflow engine and preserve resumability.
- Keep the single all-in-one Docker image until an intentional migration.
- Keep Streamlit draft state session-scoped below
  `/output/ui_sessions/<ui_session_id>/`.
- Keep run inputs immutable below each run's `run/` directory.
- Built-in references are checksum-pinned Ensembl bundles with canonical IDs
  and backward-compatible aliases.
- `analysis_plan` is the source of truth for differential versus QC-only mode.
- The static self-contained report remains at `report/report.html` relative to
  each run directory.

Alignment modes, BAM output, MultiQC, hosted multi-user deployment, and native
arm64 images are not currently implemented. Do not advertise them.

## Change discipline

- Preserve stable output filenames and run-directory compatibility. Any
  contract change requires tests, documentation, and migration notes.
- Do not commit large biological data. Fixtures must remain KB-to-MB scale.
- Behavior changes require focused regression and smoke coverage.
- Scientific changes require explicit assumptions, integration tests, and
  limitations documentation.
- Public-facing changes require synchronized English and Japanese claims.
- Use "source-available", "public beta", and "academic/noncommercial use";
  do not describe Harako as open source or OSI-approved.
- Keep one purpose per branch and pull request.
- Do not perform Git add, commit, tag, push, merge, or visibility changes
  automatically unless the user explicitly requests that operation.

Run `just smoke`, `just verify-smoke`, relevant pytest suites, and
`git diff --check` before proposing a behavior or release change.
