# Agent-ready interface contract

The `python -m app agent` namespace is a development interface targeted for
`v0.3.0-beta.1`. The released public beta remains `v0.2.0-beta.1`. Harako does
not embed an LLM, OpenAI client, API key, cloud upload, chat UI, MCP server, or
Codex SDK. The interface is vendor-neutral and all operations remain local.

Harako remains the scientific execution authority. An agent may orchestrate
the review steps, but cannot replace sample validation, reference resolution,
analysis eligibility, contrast resolution, enrichment eligibility, the frozen
run configuration, or Snakemake execution.

## Safety contract

1. Harako does not infer biological conditions.
2. Sample-to-condition assignments require explicit user input.
3. Proposed FASTQ pairing remains visible and reviewable.
4. Planning, validation, and dry-run do not execute an analysis.
5. Execution requires `--approve` with the exact current approval hash.
6. Core run inputs are frozen before scientific execution.
7. Additional analyses belong in a separate `post_analysis/` workspace.
8. Agents treat core run outputs as read-only scientific evidence.
9. FASTQ sequence contents are not needed to configure Harako and should not
   be sent to an external model.
10. Patient identifiers and confidential metadata must not be placed in agent
    prompts, context files, or public logs.
11. An agent may explain or propose statistics, but Harako's supported design
    remains authoritative for core execution.
12. An agent must not silently change a reference, condition, contrast,
    resource, or analysis mode after approval.

The minimum differential-expression gate remains at least two conditions with
at least two samples in every condition. It is not a power calculation or
evidence of biological independence. Runs below the gate use QC-only mode and
do not report p-values or adjusted p-values.

## Command sequence

```bash
python -m app agent inspect-input --input /input --output inspection.json
python -m app agent propose-samples --inspection inspection.json --output samples.tsv --report proposal.json
python -m app agent propose-samples --inspection inspection.json --condition-map conditions.tsv --output samples.tsv --force
python -m app agent plan --samples samples.tsv --input /input --output /output --project-name study01 --species mouse --ref-preset mouse_ensembl_grcm39 --contrast-mode ref --contrast-ref control --threads 8 --plan harako-plan.yaml
python -m app agent validate-plan --plan harako-plan.yaml
python -m app agent dry-run --plan harako-plan.yaml
python -m app agent execute --plan harako-plan.yaml --approve <APPROVAL_HASH>
python -m app agent status --run-dir /output/data_out/<run_id>
python -m app agent artifacts --run-dir /output/data_out/<run_id>
python -m app agent context --run-dir /output/data_out/<run_id> --output agent-context.json
python -m app agent post-analysis-init --run-dir /output/data_out/<run_id> --name pathway-review --question "Review stress-response pathways"
```

Every command writes one JSON object to stdout. Diagnostics and scientific
execution progress use stderr. Each response contains `schema_version` and
`harako_version`. Inspection reads names, relative paths, extensions, sizes,
and pairing metadata; it never opens FASTQ sequence records or hashes full
FASTQ files.

`propose-samples` creates only sample-ID and pairing proposals. Conditions stay
blank until an explicit two-column `sample<TAB>condition` map is supplied.
Ambiguous candidates remain in `unresolved`; Harako never silently selects one.
Existing output files require `--force`.

## Canonical plan and approval

The canonical YAML plan follows
`config/schemas/harako-agent-plan-v1.schema.json`. It contains:

- schema and Harako versions, plan ID, and creation time;
- input and output roots and project name;
- sample IDs, explicit conditions, FASTQ paths, and pairing status;
- requested and canonical reference identity, assembly, expected paths,
  checksum state, and provenance;
- the existing policy-versioned Harako `analysis_plan`;
- resolved contrasts and enrichment state;
- threads, execution engine, requested options, warnings, and unresolved
  items;
- `approval_required` and `approval_hash`.

The plan ID and approval hash are SHA256 values over canonical JSON. Creation
time, warnings, unresolved review messages, and dictionary insertion order are
excluded. Samples, conditions, FASTQ paths, reference, analysis mode,
contrasts, enrichment, threads, output root, project name, and execution engine
are included. Any semantic change requires a new approval.

A plan may be written for review when conditions, contrasts, or a verified
reference are unresolved. Such a plan is not executable. `validate-plan`
checks JSON Schema, plan hashes, sample structure, FASTQ existence and pairing,
conditions, analysis-plan consistency, reference identity and checksums,
contrasts, enrichment, output writability, and resource sanity without
modifying the plan.

`dry-run` compiles the plan into an existing Harako configuration in temporary
storage and invokes the existing Snakemake dry-run. It creates no persistent
Run and does not count as approval.

`execute` recomputes the approval hash, validates again, freezes the ordinary
Harako configuration and sample table, records the approved canonical plan and
approval metadata, and delegates to the existing Harako/Snakemake execution
path. There is no generic `--yes`, implicit approval, or environment-variable
approval.

## Status, artifacts, and context

`status` uses the frozen configuration, manifest, agent execution record,
workflow artifacts, logs, and `deseq2/status.json`. A `results.tsv` file alone
does not establish successful differential expression. States are `planned`,
`running`, `completed`, `failed`, `interrupted`, or `unknown`.

`artifacts` returns only allowlisted Harako artifact types with run-relative
paths, sizes, generation state, applicability, analysis mode, and descriptions.
QC-only inferential artifacts are marked inapplicable, not failed.

`context` creates a sanitized local index containing project/run identity,
sample IDs and conditions, analysis mode, contrasts, reference provenance,
tool versions, typed artifacts, output-schema notes, warnings, and limitations.
It excludes FASTQ contents, environment variables, credentials, patient
identifiers, unrestricted tracebacks, and host-absolute artifact paths. It is
not intended for automatic cloud upload.

## Post-analysis isolation

`post-analysis-init` creates a sibling workspace:

```text
post_analysis/<analysis_id>/
  analysis.yaml
  input_manifest.json
  README.md
  scripts/
  figures/
  tables/
  reports/
  logs/
  environment/
```

The workspace records the question, creation time, source Run ID, analysis
mode, selected read-only artifacts, and practical hashes. It does not copy
FASTQ files, execute generated code, or modify the approved plan, frozen
configuration, tximport/DESeq2 outputs, or core report. Harako results and
agent-generated analysis remain explicitly distinguished.

## Exit codes

- `0`: success;
- `2`: invalid input or invalid plan;
- `3`: unresolved plan or missing/mismatched approval;
- `4`: dry-run or pipeline execution failure;
- `5`: requested Run or artifact source not found.

Errors are not converted to exit-code zero. Agent plans are optional, existing
v0.2 configurations remain valid, and the GUI remains the primary interface
for ordinary users.
