# Using Harako-RNAseq

## Five-page GUI flow

Launch with `just app` on Ubuntu/Linux or `just app-ps` on Windows, then work
through the five pages.

### 1. Project

Set a project name and select the input subdirectories to scan. The project
name is normalized for the run-directory name and retained in the frozen run
configuration. Selecting subdirectories limits discovery without moving input
files.

### 2. Samples

Review discovered FASTQ files and edit sample, condition, `fastq1`, and
`fastq2`. Auto-pair recognizes common read-one/read-two naming patterns.

Condition auto-fill removes only a trailing replicate suffix such as `_1`,
`-2`, or `_rep3`. Run accessions such as `SRR14340927` remain unchanged.
Always verify condition assignments; filenames do not establish biological
replication or independence.

### 3. Reference files

Select a checksum-verified built-in Ensembl preset or provide custom
transcript FASTA, genome FASTA, and GTF paths. The UI displays provider,
assembly, annotation release, cache source, and verification state.

See [Reference presets](reference-presets.md) for canonical IDs and legacy
aliases.

### 4. Advanced

Choose contrast and enrichment settings when differential expression is
eligible. Harako retains requested Advanced values when the design changes to
QC-only, but the frozen executable plan does not apply contrasts or
enrichment in that run.

### 5. Summary

Review the effective configuration and analysis mode, then use:

1. Save
2. Validate
3. Dry-run
4. Run

Sample or configuration edits mark prior validation stale. Run starts only
after the current saved configuration validates.

## Analysis modes

Differential-expression mode requires at least two conditions and at least two
samples in every condition. Structurally valid designs below this minimum run
in QC-only mode. QC-only retains preprocessing, quantification, gene-level
counts and TPM, descriptive normalization when possible, applicable QC, and
the report, but does not run contrasts or enrichment.

This minimum gate is not a power calculation and does not prove biological
independence or an adequate design. See [Scientific methods](scientific-methods.md)
and [Limitations](limitations.md).

## Contrasts and enrichment

Differential mode supports a reference condition, pairwise contrasts, or
explicit selected pairs. Check the displayed direction before running.

Enrichment requires both available inferential DE statistics and its own
configuration prerequisites. It is unavailable in QC-only mode and is not
inferred from the presence of `deseq2/results.tsv`.

## Resume, recover, and existing reports

Each new run freezes its executable configuration under the run directory.
Resume and Recover use that immutable configuration, not the current browser
draft.

- Resume continues an interrupted compatible run.
- Recover uses the frozen run configuration after a recoverable failure.
- Open existing report remains available for a completed report.
- Eligible legacy runs without `analysis_plan` may resume with a compatibility
  warning.
- Ineligible legacy runs must be recreated as a new QC-only run; old files are
  not rewritten.

Do not manually edit a frozen run configuration. Use a new run when changing
samples, references, analysis mode, or other identity-bearing settings.

## Reports and outputs

The primary artifact is the self-contained HTML report under the run's
`report/report.html`. It summarizes samples, references, fastp, Salmon,
gene-level counts and TPM availability, analysis mode, QC, and applicable DE
or enrichment results.

`deseq2/status.json` is the machine-readable source of truth for analysis mode
and artifact availability. In QC-only mode, `deseq2/results.tsv` contains its
stable header and zero result rows.

See the [Output reference](output-reference.md) for stable paths and
[Troubleshooting](troubleshooting.md) for recovery guidance.
