# Harako-RNAseq documentation

This index separates public usage, scientific interpretation, operations, and
maintainer guidance for the Harako-RNAseq public beta.

## Getting started

- [Installation](installation.md): Docker, just, platform setup, and resources.
- [First run and GUI usage](usage.md): the five-page workflow and run lifecycle.
- [SRA/ENA input](sra-ena.md): Run Selector tables and accession acquisition.
- [Support matrix](support-matrix.md): verified and unverified environments.

## Scientific methods

- [Scientific methods](scientific-methods.md): fastp, Salmon, tximport, DESeq2,
  QC-only mode, contrasts, and enrichment.
- [Analysis-plan migration](migration-v0.2-analysis-plan.md): frozen analysis
  policy and legacy-run behavior.
- [Reference presets](reference-presets.md): canonical Ensembl bundles,
  aliases, assemblies, and checksums.
- [Reference boundary](refs-boundary.md): resolution and trust boundaries.
- [Reference preset migration](migration-v0.2-reference-presets.md): legacy
  configuration and cache compatibility.
- [Output reference](output-reference.md): stable artifacts and status files.
- [Limitations](limitations.md): scientific and operational limitations.
- [Harako and nf-core/rnaseq](comparison-nf-core-rnaseq.md): concise scope and
  workflow comparison.

## Operations

- [Troubleshooting](troubleshooting.md): launch, mount, workflow, reference, and
  report recovery.
- [Resume and recovery](usage.md#resume-recover-and-existing-reports).
- [Storage requirements](installation.md#resources-and-storage).
- [Advanced usage](advanced-usage.md): CLI, Snakemake, custom references, and
  maintainer checks.
- [Agent-ready workflow](agent-workflow.md): machine-readable planning,
  explicit approval, status, artifacts, and post-analysis safety boundaries.
- [Codex-assisted analysis](agent-assisted-analysis.md): complete local
  orchestration example and reusable instruction template.
- [Container image](container-image.md): published GHCR tags, architecture,
  and verification.
- [Security and supply chain](security-and-supply-chain.md): locks, notices,
  SBOM, and provenance.
- [Public-beta feedback](beta-feedback.md): feedback scope and privacy rules.
- [Release checklist](release-checklist.md).

## Maintainers

- [Contributing](../CONTRIBUTING.md).
- [Site screenshot provenance](site-screenshot-provenance.md).
- [Terminology guide](terminology.md).
- [Architecture](architecture.md).
- [Reference checksum maintenance](advanced-usage.md#reference-checksum-maintenance).
- [Analysis-plan migration](migration-v0.2-analysis-plan.md).
- [Reference migration](migration-v0.2-reference-presets.md).
- [Development provenance](provenance.md).
- [Release publishing](release-publishing.md).
- [Transitive license review](transitive-license-review.md).
- [v0.2.0-beta.1 vulnerability review](vulnerability-review-v0.2.0-beta.1.md).
- [v0.3.0-beta.1 vulnerability review](vulnerability-review-v0.3.0-beta.1.md).
- [v0.3.0-beta.2 vulnerability review](vulnerability-review-v0.3.0-beta.2.md).
- [Public-beta launch runbook](public-beta-launch-runbook.md).
- [v0.2.0-beta.1 ref disposition](releases/v0.2.0-beta.1-ref-disposition.md).
- [v0.2.0-beta.1 release notes](releases/v0.2.0-beta.1.md).
- [v0.3.0-beta.1 release notes](releases/v0.3.0-beta.1.md).
- [v0.3.0-beta.2 release notes](releases/v0.3.0-beta.2.md).
- [v0.3.0-beta.1 qualification plan](releases/v0.3.0-beta.1-plan.md).

Project support and governance are described in
[SUPPORT.md](../SUPPORT.md), [SECURITY.md](../SECURITY.md), and
[COMMERCIAL_LICENSE.md](../COMMERCIAL_LICENSE.md).
