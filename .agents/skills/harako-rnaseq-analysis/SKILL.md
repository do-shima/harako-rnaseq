---
name: harako-rnaseq-analysis
description: Safely orchestrates local Harako-RNAseq FASTQ inspection, explicit sample and condition review, explicit library-protocol selection, canonical planning, dry run, approval-controlled execution, run inspection, and isolated post-analysis. Use when a user wants Codex or another local coding agent to run or inspect Harako-RNAseq.
---

# Harako RNA-seq analysis

Use Harako as the scientific execution authority. Coordinate only through the
stable `python -m app agent` interface.

## Workflow

1. Run `inspect-input` on the requested input directory. Inspect filenames,
   paths, sizes, and pairing metadata without reading FASTQ sequence records.
2. Run `propose-samples` to propose sample IDs and R1/R2 pairing.
3. Show every pairing, ambiguity, warning, and unresolved item. Never resolve
   ambiguous pairing silently.
4. Ask the user to provide or confirm every sample-to-condition assignment.
5. Ask the user to select exactly one library protocol explicitly:
   `full_length` or `three_prime_tag`.
6. Ask the user to confirm species, reference preset, contrast mode, reference
   condition or selected contrasts, enrichment, threads, project name, and
   output root.
7. Run `plan` to build the canonical plan.
8. Run `validate-plan`.
9. Run `dry-run`. A dry run is not execution approval.
10. Present samples, conditions, library protocol, reference identity and
    checksum state, analysis mode, contrasts, enrichment state, warnings,
    unresolved items, plan ID, and approval hash.
11. Stop and wait for explicit approval of the exact current approval hash.
12. Run `execute --approve <exact-current-approval-hash>` only after the user
    returns or explicitly confirms that exact hash. Revalidate the unchanged
    plan immediately before execution.
13. Inspect the run with `status`, `artifacts`, and `context`.
14. Create additional work only with `post-analysis-init`.
15. Treat the Harako core run, frozen inputs, and core outputs as read-only.

## Non-negotiable boundaries

- Never infer biological conditions, control groups, or biological
  independence.
- Never infer full-length versus 3′-tag protocol from filenames, accessions,
  read length, library names, platform, or metadata.
- Never reuse an approval hash after any plan change or use a generic yes flag.
- Never edit frozen run inputs or overwrite Harako core outputs.
- Never present QC-only output as evidence of differential expression.
- Never send FASTQ contents, patient data, credentials, unpublished sample
  identifiers, confidential metadata, or private paths to an external model.
- Do not build or require an MCP server, OpenAI SDK, Anthropic SDK, provider
  API, API key, wrapper CLI, or background service.

## Historical plans and runs

- Old schema-v1 agent plans without `library_protocol` may be inspected and
  hash-verified, but they are not executable and must be regenerated before
  dry run or execution.
- Never infer or insert a protocol into a historical agent plan.
- `legacy_unspecified` applies only to historical frozen runs, never to an old
  agent plan.

## References

- [Agent workflow contract](../../../docs/agent-workflow.md)
- [Agent-assisted example](../../../docs/agent-assisted-analysis.md)
- [Scientific methods](../../../docs/scientific-methods.md)
- [Limitations](../../../docs/limitations.md)
