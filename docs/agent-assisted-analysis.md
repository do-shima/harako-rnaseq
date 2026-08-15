# Codex-assisted Harako analysis

This guide shows how Codex or another local automation tool can coordinate
review steps around Harako. Harako validates and executes the supported
scientific workflow; automation tools do not determine analysis eligibility or
replace Harako's execution path. Harako does not require or embed an OpenAI API
client, and this guide does not imply endorsement or certification by OpenAI.

## Complete example

The user states:

- `Con_Hard_1` and `Con_Hard_2` are `control`;
- `STZ_Hard_1` and `STZ_Hard_2` are `STZ`;
- use mouse GRCm39;
- use full-length RNA-seq;
- use `control` as the reference;
- show the plan before execution.

Inspect filenames and pairing metadata without opening sequence records:

```bash
python -m app agent inspect-input --input /input --output inspection.json
python -m app agent propose-samples --inspection inspection.json --output samples.tsv --report sample-proposal.json
```

Show `sample-proposal.json` to the user. After the user confirms the pairing
and stated conditions, create:

```text
sample	condition
Con_Hard_1	control
Con_Hard_2	control
STZ_Hard_1	STZ
STZ_Hard_2	STZ
```

Then materialize and plan:

```bash
python -m app agent propose-samples --inspection inspection.json --condition-map conditions.tsv --output samples.tsv --report approved-samples.json --force
python -m app agent plan --samples samples.tsv --input /input --output /output --project-name stz-hard --library-protocol full_length --species mouse --ref-preset mouse_ensembl_grcm39 --contrast-mode ref --contrast-ref control --threads 8 --plan harako-plan.yaml
python -m app agent validate-plan --plan harako-plan.yaml
python -m app agent dry-run --plan harako-plan.yaml
```

Present the samples, condition counts, library protocol, reference identity
and checksum state, analysis mode, contrast pairs, inactive options, warnings,
unresolved items, and approval hash. Stop until the user approves that exact
hash. A dry run is not approval.

```bash
python -m app agent execute --plan harako-plan.yaml --approve <EXACT_APPROVAL_HASH>
python -m app agent status --run-dir /output/data_out/<run_id>
python -m app agent artifacts --run-dir /output/data_out/<run_id>
python -m app agent context --run-dir /output/data_out/<run_id> --output agent-context.json
python -m app agent post-analysis-init --run-dir /output/data_out/<run_id> --name pathway-review --question "Summarize stress-response pathways"
```

Additional R or Python scripts belong only inside the returned post-analysis
workspace. They must label their outputs as agent- or user-generated rather
than Harako core results.

## Real-data pilot notes

The development interface was exercised on one local paired-end mouse pilot:
24 FASTQ files formed 12 unambiguous pairs, and the user explicitly assigned
three samples to each of four conditions. The working public command sequence
was:

```text
inspect-input
-> propose-samples
-> explicit condition map
-> plan
-> validate-plan
-> dry-run
-> exact approval hash review
-> execute
-> status
-> artifacts
-> context
-> post-analysis-init
```

The pilot used the checksum-verified `mouse_ensembl_grcm39` release-113
reference, 12 threads, pairwise contrasts, and enrichment. Pairwise mode does
not use one group as a global reference: the plan must display and receive
approval for every resolved unordered pair. In this four-condition pilot that
meant six contrast pairs. A requested reference condition remains relevant
only when `--contrast-mode ref` is selected.

The plan was executable with no unresolved items, the real Snakemake dry run
passed, and execution began only after the user returned the exact displayed
approval hash. `status` reported completion; counts, TPM, DESeq2, PCA,
sample-distance, enrichment, and the self-contained HTML report were present.
An additional descriptive summary was created under a sibling
`post_analysis/<analysis_id>/` workspace, and the hashes recorded for selected
core Run artifacts remained unchanged.

Paths containing spaces must be quoted as one shell argument, including Docker
bind-mount specifications. Pairing that is not unambiguous remains unresolved
and must be corrected explicitly before planning. The first use of a pinned
reference can take substantially longer because reference download and Salmon
index creation are required; neither step changes the approval contract.

## Reusable Codex instruction template

```text
Operate Harako locally through `python -m app agent`.

Never read or upload FASTQ sequence content merely to configure Harako. Inspect
filenames and metadata, then show all proposed sample IDs, R1/R2 pairing, and
condition assignments. Do not infer conditions or full-length versus 3′-tag
protocol. Ask me to approve conditions, library protocol, reference, and
contrasts before planning.

Create the canonical plan, run `validate-plan` and `dry-run`, and summarize all
warnings and unresolved items. Never execute without my explicit approval of
the exact current approval_hash. If any execution-relevant value changes,
regenerate the plan and ask again.

Treat the frozen Harako Run and its outputs as read-only. Use status,
artifacts, and context to inspect it. Never present QC-only output as evidence
of differential expression. Put any additional R/Python work only under
the workspace created by post-analysis-init, and clearly distinguish Harako
outputs from agent-generated interpretations.
```

See [Agent-ready interface contract](agent-workflow.md) for schemas, safety
rules, and exit codes.
