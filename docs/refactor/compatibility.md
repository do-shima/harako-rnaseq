# Refactor compatibility statement

No migration is required.

| Surface | Result |
|---|---|
| CLI | `python -m app`, commands, primary options, help surface, and exit translation preserved |
| GUI | five-step flow, draft isolation, labels, validation, run/recovery actions, and report access preserved |
| Agent | ten commands, interface/schema versions, JSON fields, errors, plan IDs, approval hashes, and exact-hash approval preserved |
| Workflow | Snakemake, rule names, inputs/outputs, resume, real/stub behavior, and scientific route preserved |
| Runs | run identity inputs, frozen configuration, manifests, metadata, status, artifacts, and directory layout preserved |
| Outputs | stable filenames, TSV/JSON schemas, `report/report.html`, and self-contained report preserved |
| References | preset IDs, aliases, releases, assemblies, cache resolution, custom-reference behavior, and all 12 SHA-256 values preserved |
| Science | sample/condition order, protocol behavior, DE/QC-only eligibility, contrasts, tximport/TPM/DESeq2/enrichment behavior unchanged |
| Docker | one all-in-one amd64 image, runtime user/mount/entrypoint, locks, and tool versions preserved |
| Windows | path normalization, launcher, PowerShell/host tests, and session/run paths preserved |

Compatibility facades intentionally retain established Python import paths
while delegating to the new core, service, and adapter modules.
