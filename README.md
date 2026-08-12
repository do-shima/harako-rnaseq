# Harako-RNAseq

<p align="center">
  <img src="icon/Harako-logo.png" alt="Harako-RNAseq logo" width="220">
</p>

[Japanese README](README.ja.md) | [Documentation](docs/index.md)

Project website: <https://do-shima.github.io/harako-rnaseq/>

Harako-RNAseq is a Docker-based graphical workflow for reproducible, local
bulk RNA-seq analysis using fastp, Salmon, tximport, DESeq2, and self-contained
HTML reporting.

**Public beta | Source-available | Academic and permitted noncommercial use**

Harako is intended for researchers and analysts running small-to-medium bulk
RNA-seq studies on a local workstation. It is a local, single-user application,
not a hosted multi-user service. Windows with Docker Desktop and Ubuntu/Linux
with Docker are verified. The current image architecture is `linux/amd64`;
macOS has not yet been verified for this release.

Users remain responsible for experimental design, biological independence,
reference selection, privacy, and scientific interpretation. Harako is not a
substitute for expert review.

## Overview

The Streamlit GUI prepares a normalized sample table, selects a verified
reference or custom files, freezes a reproducible run configuration, and
starts a resumable Snakemake workflow. Harako supports single-end and
paired-end FASTQ input plus supported SRA/ENA acquisition workflows for human,
mouse, and rat studies.

The workflow produces gene-level tximport counts and TPM after Salmon
transcript quantification. DESeq2 uses counts, never TPM. Designs below the
minimum differential-expression replication policy continue in an explicit
QC-only mode without fabricated inferential statistics.

## Features

- FASTQ discovery with selected-subdirectory scanning.
- Editable sample table and paired-end auto-pairing.
- Consistent condition normalization with manual review.
- Checksum-verified Ensembl presets for human, mouse, and rat.
- Custom transcript FASTA, genome FASTA, and GTF support.
- fastp preprocessing and Salmon transcript quantification.
- Gene-level tximport counts and descriptive TPM.
- DESeq2 differential-expression mode for eligible designs.
- QC-only mode for structurally valid unsupported designs.
- Optional enrichment when inferential DE results are available.
- Session-isolated drafts and immutable run-local configuration.
- Reproducible run identity, provenance, logs, and captured versions.
- Bilingual English/Japanese Streamlit interface.
- Self-contained HTML report with no required external web assets.

## Quickstart

Harako currently builds its Docker image locally. The first build can take
substantial time because it installs R and Bioconductor dependencies.

### Ubuntu and Linux

```bash
git clone https://github.com/do-shima/harako-rnaseq.git
cd harako-rnaseq
just app
```

### Windows PowerShell

```powershell
git clone https://github.com/do-shima/harako-rnaseq.git
Set-Location harako-rnaseq
just app-ps
```

Start Docker or Docker Desktop before running the launcher. When `INPUT` and
`OUT` are omitted, Harako uses repository-local `input/` and `output/`
directories. Open `http://127.0.0.1:8501`.

See [Installation](docs/installation.md) for explicit mounts, resources,
platform status, port forwarding, and first-build guidance.

## Typical workflow

1. **Project:** name the study and select input subdirectories.
2. **Samples:** review FASTQ discovery, pairing, sample IDs, and conditions.
3. **Reference files:** select a built-in Ensembl preset or custom files.
4. **Advanced:** choose applicable contrasts and enrichment settings.
5. **Summary:** use Save, Validate, Dry-run, then Run.

Each browser session keeps its draft state separate. Starting a run freezes the
normalized sample table, executable configuration, analysis plan, and reference
provenance under that run. Resume and Recover use this frozen configuration,
not later UI edits.

See [Using Harako-RNAseq](docs/usage.md) for the GUI and run lifecycle, or
[SRA and ENA input](docs/sra-ena.md) for accession acquisition.

## Controlled agent-ready interface

**v0.3.0-beta.1** includes a controlled machine-readable CLI for local
automation tools such as Codex. Biological conditions are never inferred:
sample assignments must be explicit, and execution requires approval of the
exact deterministic plan hash. Harako remains the scientific execution engine
and the interface does not replace scientific review.

Harako remains fully usable without an agent and contains no OpenAI client,
model call, API key, or cloud AI dependency. See the
[agent workflow and safety contract](docs/agent-workflow.md) and the complete
[Codex-assisted example](docs/agent-assisted-analysis.md).

## Supported analysis modes

### Differential-expression analysis

Inferential differential expression requires:

- at least two distinct conditions; and
- at least two valid samples in every condition.

Eligible runs retain the configured contrast behavior. Enrichment can run only
when inferential DE statistics are available and its own prerequisites pass.

### QC-only analysis

Structurally valid one-condition designs or designs with fewer than two samples
in any condition run in QC-only mode. They retain preprocessing,
quantification, gene-level counts and TPM, descriptive normalization when
technically possible, applicable PCA and sample-distance QC, and reporting.

QC-only mode does not run contrasts, produce p-values or adjusted p-values,
interpret volcano/MA plots, or run enrichment. `deseq2/results.tsv` is
header-only; `deseq2/status.json` records the mode and actual artifact
availability.

Two samples per condition is only a minimum software gate. It is not a power
calculation and does not establish biological independence or design quality.

## Main outputs

Every run retains stable workflow artifacts, including:

- `fastp/`: processed reads and fastp JSON/HTML QC.
- `salmon/<sample>/quant.sf`: transcript quantification.
- `tximport/txi.tsv`: gene-level count matrix.
- `tximport/gene_tpm.tsv`: descriptive gene-level TPM when available.
- `deseq2/status.json`: analysis mode and artifact availability.
- `deseq2/results.tsv`: DE rows, or a stable header only in QC-only mode.
- `deseq2/normalized_counts.tsv`: descriptive normalized counts.
- `report/report.html`: self-contained analysis report.
- `run/`: frozen configuration, sample metadata, manifest, logs, and versions.

Exact paths and mode-dependent behavior are documented in the
[Output reference](docs/output-reference.md).

## Documentation

Start with the [documentation index](docs/index.md).

- [Installation and resources](docs/installation.md)
- [GUI usage and recovery](docs/usage.md)
- [SRA/ENA acquisition](docs/sra-ena.md)
- [Scientific methods](docs/scientific-methods.md)
- [Reference presets](docs/reference-presets.md)
- [Outputs](docs/output-reference.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Advanced usage](docs/advanced-usage.md)
- [Agent-ready workflow](docs/agent-workflow.md)
- [Architecture](docs/architecture.md)
- [Support matrix](docs/support-matrix.md)
- [Limitations](docs/limitations.md)

## System requirements

- Git, Docker with a Linux engine, and `just`.
- A browser with local access to port 8501.
- A currently verified Windows Docker Desktop or Ubuntu/Linux Docker host.
- An amd64-capable Docker environment for the current image.
- Sufficient memory and disk for FASTQ, uncompressed fastp intermediates,
  reference caches, Salmon indexes, quantification, and reports.

Native non-Docker execution and hosted multi-user deployment are not supported.
macOS Intel has not yet been verified, and the current image is not a native
Apple Silicon/arm64 image. See the [support matrix](docs/support-matrix.md).

## Scientific limitations

- The default model is condition-based and does not automatically represent
  batch, pairing, repeated measures, or other covariates.
- Passing the DE eligibility gate does not guarantee adequate power or valid
  biological replication.
- Salmon quantifies transcripts; tximport summarizes to genes.
- DESeq2 uses gene-level counts, not TPM.
- Built-in hashes identify exact reference files but do not prove that an
  assembly is appropriate for a study.
- Custom-reference compatibility remains the user's responsibility.
- Small-to-medium dataset positioning is operational guidance, not a hard
  biological size boundary.

Review [Scientific methods](docs/scientific-methods.md) and
[Limitations](docs/limitations.md) before interpreting results.

## License and permitted use

Harako-RNAseq is source-available under the
[PolyForm Noncommercial License 1.0.0](LICENSE).

It may be used, modified, and redistributed for permitted noncommercial
purposes, including academic, educational, and public research use, subject to
the license terms.

Commercial use, commercial services, resale, and use for an anticipated
commercial application are not granted by this license and require a separate
written license or permission. See [Commercial licensing](COMMERCIAL_LICENSE.md).

Third-party tools and libraries used by or distributed with Harako-RNAseq
remain subject to their respective licenses. See
[Third-Party Notices](THIRD_PARTY_NOTICES.md).

## Origins and acknowledgements

Harako-RNAseq was inspired by the
[ikra](https://github.com/yyoshiaki/ikra) RNA-seq pipeline centered on Salmon.
Harako-RNAseq is an independently implemented project that extends this concept
with a graphical user interface, cross-platform Docker operation, reproducible
run management, differential-expression and quality-control workflows, and
self-contained reporting. Harako-RNAseq is not an official successor to, or
endorsed by, the ikra project.

### AI-assisted development

Development of Harako-RNAseq was assisted by OpenAI Codex for implementation,
refactoring, test generation, documentation, debugging, and code review.
All scientific interpretations, architectural decisions, validation,
licensing decisions, and release decisions were made and approved by the
project maintainer. AI-generated suggestions were reviewed before inclusion
in the repository.

This acknowledgement does not imply endorsement, sponsorship, or certification
of Harako-RNAseq by OpenAI.

The engineering provenance audit is documented in
[docs/provenance.md](docs/provenance.md).

## Citation

If you use Harako-RNAseq, cite the software release using
[CITATION.cff](CITATION.cff). The current public-beta version is
`0.3.0-beta.1`.

## Support and issue reporting

Read [SUPPORT.md](SUPPORT.md) before opening a public
[GitHub Issue](https://github.com/do-shima/harako-rnaseq/issues). Include the
Harako version or commit, OS, Docker version, launch command, pipeline stage,
expected and actual behavior, and sanitized logs or support-bundle details.

Never upload FASTQ files, patient information, credentials, confidential
paths, or identifiable sample data to a public issue. Security vulnerabilities
use the private route in [SECURITY.md](SECURITY.md), not ordinary support.
