# Module inventory and dependency audit

This inventory describes the pre-refactor structure at commit
`332abc4f4a3e6d1bf61cec87b48d4a995c9657f7`. Classification is architectural,
not a statement that a file is removable.

## Application modules

| Path | Responsibility before refactor | Classification | Public contract | Main coverage |
|---|---|---|---|---|
| `app/__main__.py` | invokes the root Typer application | interface | `python -m app` | CLI and smoke tests |
| `app/cli.py` | Typer commands plus config, validation, reference, manifest, and process logic | mixed interface/application/adapter | all root CLI commands and exit behavior | CLI, validation, smoke, reference tests |
| `app/agent_cli.py` | Typer JSON command handlers and exit translation | interface | ten agent commands and compatibility aliases | `test_agent_cli.py` |
| `app/agent.py` | inspection, proposal, planning, approval, execution, status, artifacts, context, workspace | mixed application/domain/adapter | agent JSON semantics | `test_agent_cli.py`, agent smoke |
| `app/agent_contracts.py` | canonical JSON, hashes, schema validation, document I/O | mixed domain/adapter | schema v1, plan ID, approval hash | agent tests |
| `app/analysis_eligibility.py` | DE/QC-only policy and frozen-plan consistency | domain | `analysis_plan` semantics | eligibility and integration tests |
| `app/library_protocol.py` | protocol constants and legacy frozen-run resolution | domain | full-length, 3-prime, legacy distinction | protocol tests |
| `app/reference_presets.py` | reference identity, aliases, release lookup, checksum/cache provenance | mixed domain/adapter | built-in reference IDs and checksums | reference tests |
| `app/run.py` | Snakemake argv, work directory, subprocess execution | adapter | CLI launcher behavior | smoke and command tests |
| `app/version.py` | current version | domain constant | version output and release metadata | release tests |

## Streamlit modules

| Path | Responsibility before refactor | Classification | Public contract | Main coverage |
|---|---|---|---|---|
| `app/ui/app_ui.py` | page composition, all page sections, state, I/O, references, run creation, process lifecycle, recovery, results | mixed interface/application/adapter | GUI page flow and labels | UI helper/config/session tests, doctor |
| `app/ui/state.py` | advanced state, validation transitions, session paths, persisted-state helpers | mixed UI state/adapter | session-scoped draft behavior | UI state/session tests |
| `app/ui/scan.py` | pure path normalization, FASTQ discovery, read-side parsing, pairing candidates | domain/application despite UI path | FASTQ semantics | UI helper and agent tests |
| `app/ui/samples_table.py` | sample normalization, pairing, validation, enrichment eligibility, TSV writing, editor callback | mixed domain/interface/adapter | sample order/conditions | UI helper and eligibility tests |
| `app/ui/config_builder.py` | pure normalized effective-config payload construction | application | effective config fields | UI payload/integration tests |
| `app/ui/run.py` | Snakemake execution, frozen config, metadata, run identity, recovery/status formatting | mixed application/adapter/presentation | immutable run and resume semantics | run/session/integration tests |
| `app/ui/refs.py` | manifest loading and presentation lists | mixed application/adapter | GUI reference selection | reference/UI tests |
| `app/ui/error_messages.py` | log classification and localized error summary | presentation | user-visible error categories | error tests |
| `app/ui/i18n.py` | locale loading and formatting | presentation/adapter | English/Japanese labels | i18n tests |
| `app/ui/logging.py` | UI event and command log writes | adapter | support/debug logs | indirect UI coverage |
| `app/ui/launcher_ui.py` | separate launch-command generator UI | interface | launcher behavior | launcher tests/doctor |

## Workflow and analysis scripts

| Path or group | Responsibility | Classification | Contract relation | Coverage |
|---|---|---|---|---|
| `workflow/Snakefile` | DAG, stable rules, config/sample/reference resolution, real/stub routing | workflow interface plus mixed domain/adapter | rule names, inputs, outputs, resume | Docker tests and smoke |
| `workflow/scripts/build_gentrome.py` | gentrome build helper | workflow adapter | Salmon reference output | workflow tests |
| `workflow/scripts/*_stub.py` | workflow-local deterministic stubs | test/runtime adapter | stub engine semantics | smoke |
| `scripts/tximport_real.R` | tximport, public count/TPM files, internal `txi.rds` | scientific runtime | numerical and path contract | real-R fixtures |
| `scripts/deseq2_real.R` | differential and QC-only DESeq2 construction/output | scientific runtime | statistical contract | real-R fixtures |
| `scripts/deseq2_qc_real.R` | descriptive QC artifacts | scientific runtime | QC filenames/content | real-R fixtures |
| `scripts/enrichment_run.R` | guarded ORA/GSEA outputs | scientific runtime | enrichment contract | enrichment fixture |
| `scripts/report_real.Rmd`, `workflow/report.qmd` | self-contained report generation | report interface | `report/report.html` | report tests/smoke |
| `scripts/*_stub.py` | deterministic scientific stubs | test/runtime adapter | stub output contract | smoke and contract tests |
| `scripts/fetch_reference_preset.py`, `fetch_refs_ensembl.sh` | checksum-pinned reference acquisition | adapter | reference cache contract | fetch/reference tests |
| `scripts/srr_fetch.py` | confirmed public-accession acquisition | adapter/interface | documented acquisition boundary | local SRA tests |
| `scripts/check_*`, `verify_*`, `collect_*`, `review_*` | qualification, release, license, security checks | maintainer tooling | release gates | focused maintainer tests and CI |
| `scripts/install_*`, `lock_requirements.sh` | build/dependency tooling | build adapter | image/tool versions | Docker/portability tests |
| `tools/launcher/*` | desktop launcher helpers | interface/adapter | current launcher | launcher and docs coverage |

## Tests and fixtures

Tests are grouped by the contract they protect rather than treated as
production modules:

- CLI/config: `test_validate_minimal.py`, CLI/reference/portability modules.
- Agent: `test_agent_cli.py`, `test_agent_skill.py`, agent smoke scripts, legacy
  schema-v1 fixture.
- Domain/science: eligibility, protocol, reference, tximport/DESeq2,
  enrichment, QC-only, and report fixtures.
- Run/UI: config payload, session/frozen config, UI helper, i18n, error, and
  public-log tests.
- Build/release/site: Docker metadata, workflows, licenses, security,
  release-readiness, docs, and site tests.

No test or fixture was classified as dead merely because another test covers a
nearby success path.

## Pre-refactor dependency findings

The principal dependency direction was:

```text
Typer CLI ----> app.run -----------------> subprocess
     |             ^
     |             |
     +------ mixed CLI validation/reference/manifest logic

agent CLI ---> app.agent ---> app.ui.scan
                    |-------> app.ui.run ---> subprocess/filesystem
                    `-------> app.cli (late imports)

Streamlit app_ui ---> UI helper modules
       |-----------> subprocess/Popen
       `-----------> filesystem and run metadata writes
```

Findings:

- Agent-neutral code depended on the UI package for FASTQ parsing and frozen
  run writes.
- Agent execution depended on internal CLI implementation through late imports,
  while the root CLI registered the agent CLI.
- `app/ui/app_ui.py` directly started processes and wrote draft/run files.
- `app/ui/run.py` combined workflow execution, run-contract persistence,
  identity, recovery, and presentation formatting.
- FASTQ extension and scanning logic appeared independently in `app/cli.py`,
  `app/ui/scan.py`, and agent orchestration.
- Manifest/run identity logic appeared in both CLI and UI run code.
- Snakemake argv construction appeared in `app/run.py` and `app/ui/run.py`,
  with orchestration in `app/ui/app_ui.py`.
- The AST import audit found an effective CLI/agent cycle caused by late agent
  imports of CLI internals. UI package imports were also too broad to establish
  a clean domain boundary.

## Direct side-effect concentration before refactor

| Module | Observed direct write/process sites |
|---|---:|
| `app/ui/app_ui.py` | 19 |
| `app/ui/run.py` | 18 |
| `app/cli.py` | 11 |
| `app/agent.py` | 10 |
| `app/run.py` | 3 |
| `app/ui/logging.py` | 3 |
| `app/agent_contracts.py` | 2 |
| `app/ui/samples_table.py` | 1 |

Counts are an AST-assisted audit aid, not proof that a site is wrong or dead.
They identify the boundaries to move behind application services/adapters.

## Post-refactor ownership

| Path/group | Responsibility after refactor | Classification | Compatibility/coverage |
|---|---|---|---|
| `app/core/` | FASTQ semantics, analysis policy, library protocol, canonical serialization | domain | old module paths re-export; eligibility/protocol/agent tests |
| `app/services/agent_inputs.py` | inspection, explicit condition map, sample-table normalization | application service | agent schema/CLI tests and smoke |
| `app/services/agent_planning.py` | plan/reference/contrast resolution and non-mutating validation | application service | plan/hash/legacy-v1 tests |
| `app/services/agent_execution.py` | dry run and exact-hash execution gate | application service | approval and execution tests |
| `app/services/run_inspection.py` | status, artifact inventory, sanitized context | application service | status/artifact/context tests |
| `app/services/post_analysis.py` | isolated workspace initialization | application service | isolation tests |
| `app/services/{configuration,validation,pipeline_execution,run_contract,provenance}.py` | shared CLI/GUI/agent orchestration | application service | CLI, session/run, provenance, smoke |
| `app/adapters/{filesystem,process,snakemake,environment}.py` | OS/filesystem/process/workflow effects | adapter | characterization, UI, CLI, Docker smoke |
| `app/commands/` and `app/cli.py` | Typer declarations, options, output, exit translation | interface | CLI tests/help smoke |
| `app/agent.py` and `app/agent_cli.py` | compatibility exports and JSON/Typer adapter | interface/facade | agent tests and smoke |
| `app/ui/pages/` | Project, Samples, Reference, and Analysis presentation | interface | UI helper/session/i18n tests and GUI doctor |
| `app/ui/state.py` | centralized session defaults and state transitions | interface state adapter | session/state tests |
| `app/ui/app_ui.py` | Streamlit composition plus stateful Summary transaction | interface/composition | UI tests, smoke, GUI doctor |

The post-refactor import audit has no interface-to-core reverse dependency,
no core import of Streamlit/Typer/subprocess, no agent-neutral UI import, and
no CLI/agent cycle. Direct Snakemake process creation is confined to the
Snakemake adapter; general process capture/streaming is confined to adapters.
