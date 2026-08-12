# Changelog

Notable changes to Harako-RNAseq are recorded here.

## 0.3.0-beta.1 - Unreleased

### Added

- Agent-neutral `python -m app agent` namespace for metadata-only FASTQ
  inspection, reviewable sample proposals, canonical YAML plans, JSON Schema
  validation, Snakemake dry-run, explicit approval-hash confirmation, status,
  typed artifacts, and sanitized local-agent context.
- Isolated post-analysis workspaces that reference immutable Harako runs
  without modifying core artifacts or copying FASTQ files.
- Repository-local Codex Skill that orchestrates the stable CLI while keeping
  condition assignment and execution approval explicit.

### Security and data boundaries

- Plans reject arbitrary command fields and do not contain FASTQ sequence
  content.
- No OpenAI client, API key, model call, telemetry, upload, or remote execution
  dependency was added to Harako.

## 0.2.0-beta.1 - 2026-07-29

### Added

- Streamlit workflow for local, single-user bulk RNA-seq analysis.
- Session-isolated draft state and immutable run-local configuration.
- Windows and Ubuntu/Linux Docker launch paths.
- FASTQ discovery, paired-end matching, condition normalization, and SRA/ENA
  acquisition.
- Checksum-verified Ensembl reference presets for human, mouse, and rat, plus
  custom-reference support.
- fastp preprocessing, Salmon transcript quantification, tximport gene-level
  counts and TPM, and DESeq2 analysis.
- Explicit QC-only mode for designs that do not meet the minimum differential-
  expression replication gate.
- Optional enrichment when inferential differential-expression results exist.
- Self-contained HTML reports with reference, tool, and analysis provenance.
- Public-beta CI, container metadata, dependency inventory, SBOM, provenance,
  and gated GHCR publication workflows.

### Changed

- Legacy reference identifiers resolve to factual canonical Ensembl presets
  while existing verified cache directories remain reusable in place.
- Windows local `file:` URI handling now preserves drive and UNC semantics.

### Security and licensing

- Harako-RNAseq is source-available under the PolyForm Noncommercial License
  1.0.0.
- Direct runtime license notices and Salmon corresponding-source material are
  included in the container.
- ikra inspiration and OpenAI Codex-assisted development are acknowledged
  without authorship or endorsement claims.

[Unreleased]: https://github.com/do-shima/harako-rnaseq/compare/v0.2.0-beta.1...HEAD
[0.3.0-beta.1]: https://github.com/do-shima/harako-rnaseq/compare/v0.2.0-beta.1...HEAD
[0.2.0-beta.1]: https://github.com/do-shima/harako-rnaseq/releases/tag/v0.2.0-beta.1
