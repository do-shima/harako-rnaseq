---
name: harako-rnaseq-analysis
description: Safely orchestrate local Harako-RNAseq FASTQ inspection, explicit sample-condition mapping, canonical planning, dry-run, approved execution, run inspection, sanitized context, and isolated post-analysis.
---

# Harako RNA-seq analysis

Harako is the scientific execution engine. Use only its stable
`python -m app agent ...` interface for orchestration.

1. Run `inspect-input --input <dir> --output inspection.json`. Never open FASTQ sequence content merely to configure Harako.
2. Run `propose-samples --inspection inspection.json --output samples.tsv --report proposal.json`. Show every proposed sample ID and pairing.
3. Ask the user for every sample-to-condition assignment. Never infer conditions from filenames, directories, sample labels, or words such as control, WT, KO, male, female, treated, or disease.
4. Write a two-column condition map using the user's explicit instructions, then rerun `propose-samples` with `--condition-map` and `--force`.
5. Ask the user to confirm species, reference preset, contrast mode/reference, enrichment, resources, project name, and output root.
6. Run `plan`, `validate-plan`, and `dry-run`. Show pairing, conditions, reference checksum state, analysis mode, contrasts, warnings, unresolved items, and `approval_hash`.
7. Stop and wait. Planning, validation, dry-run, or silence is not approval.
8. Execute only with `execute --approve <exact-current-approval_hash>`. If any semantic value changes, regenerate the plan and ask again.
9. Inspect with `status`, `artifacts`, and `context`. Treat `deseq2/status.json` as authoritative for inferential availability.
10. Initialize additional work with `post-analysis-init`; create scripts and outputs only inside that workspace.

Never change approved labels, reference, contrasts, resources, or analysis mode;
bypass approval; edit frozen Run inputs or outputs; expose secrets or patient
identifiers; or present QC-only artifacts as differential-expression evidence.
The minimum replication gate does not establish power or biological
independence.

Read `../../../docs/agent-workflow.md` and
`../../../docs/agent-assisted-analysis.md` for the complete contracts.
