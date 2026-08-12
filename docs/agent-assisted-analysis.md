# Codex-assisted Harako analysis

This guide shows how Codex or another local agent can orchestrate Harako while
Harako remains the scientific execution authority. It does not require or
embed an OpenAI API client, and it does not imply endorsement or certification
by OpenAI.

## Complete example

The user states:

- `Con_Hard_1` and `Con_Hard_2` are `control`;
- `STZ_Hard_1` and `STZ_Hard_2` are `STZ`;
- use mouse GRCm39;
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
python -m app agent plan --samples samples.tsv --input /input --output /output --project-name stz-hard --species mouse --ref-preset mouse_ensembl_grcm39 --contrast-mode ref --contrast-ref control --threads 8 --plan harako-plan.yaml
python -m app agent validate-plan --plan harako-plan.yaml
python -m app agent dry-run --plan harako-plan.yaml
```

Present the samples, condition counts, reference identity and checksum state,
analysis mode, contrast pairs, inactive options, warnings, unresolved items,
and approval hash. Stop until the user approves that exact hash. Dry-run is not
approval.

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

## Reusable Codex instruction template

```text
Operate Harako locally through `python -m app agent`.

Never read or upload FASTQ sequence content merely to configure Harako. Inspect
filenames and metadata, then show all proposed sample IDs, R1/R2 pairing, and
condition assignments. Do not infer conditions. Ask me to approve conditions,
reference, and contrasts before planning.

Create the canonical plan, run validate-plan and dry-run, and summarize all
warnings and unresolved items. Never execute without my explicit approval of
the exact current approval_hash. If any execution-relevant value changes,
regenerate the plan and ask again.

Treat the frozen Harako Run and its outputs as read-only. Use status,
artifacts, and context to inspect it. Never present QC-only output as
differential-expression evidence. Put any additional R/Python work only under
the workspace created by post-analysis-init, and clearly distinguish Harako
outputs from agent-generated interpretations.
```

See [Agent-ready interface contract](agent-workflow.md) for schemas, safety
rules, and exit codes.
