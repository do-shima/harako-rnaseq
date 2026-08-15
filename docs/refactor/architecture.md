# Full architecture refactor

This maintainer record describes the internal refactor that started at
`332abc4f4a3e6d1bf61cec87b48d4a995c9657f7`. It changes internal dependency
direction, not Harako's public or scientific contracts.

## Before

The root CLI, agent application module, and Streamlit application each mixed
interface code with sample/reference/run logic and operating-system effects.
Agent-neutral code imported UI helpers, CLI and agent internals formed a late
import cycle, and both CLI and GUI assembled or launched Snakemake commands.
`app/ui/app_ui.py` also wrote draft/run state and managed process handles.

```text
CLI --------> mixed CLI logic --------> subprocess/filesystem
agent CLI --> app.agent --> UI/CLI internals
Streamlit --> app_ui mixed page/domain/run/process logic
```

## After

```text
Streamlit pages       Typer CLI       agent JSON CLI
          \              |              /
           +------ application services ------+
                          |
                    app/core domain
                          |
          filesystem / process / Snakemake adapters
                          |
                  unchanged Snakemake DAG
```

- `app/core/` owns analysis eligibility, FASTQ identity/pairing primitives,
  protocol rules, and canonical serialization. It imports neither Streamlit,
  Typer, Snakemake, nor `subprocess`.
- `app/services/` owns input inspection, explicit sample proposal, planning,
  validation, approval-controlled execution, frozen run creation, provenance,
  status/artifact inspection, and post-analysis initialization.
- `app/adapters/` contains filesystem mutation, process execution, host/cgroup
  detection, and Snakemake command/process behavior.
- `app/commands/`, `app/cli.py`, `app/agent_cli.py`, and `app/ui/pages/` adapt
  user input and present service results.
- `app/agent.py`, `app/run.py`, `app/analysis_eligibility.py`,
  `app/library_protocol.py`, and `app/ui/scan.py` remain explicit compatibility
  facades for existing import paths.

The only remaining large UI module is `app/ui/app_ui.py`. Project, Samples,
Reference, and Analysis pages are extracted. The Summary page remains together
because its Save → Validate → Dry run → Run, resume/recover, live process, and
log rendering sequence is one stateful transaction. Its scientific decisions,
filesystem writes, run metadata, and Snakemake launch are delegated to services
and adapters; splitting the presentation further without a UI-contract change
would add a large callback/service-locator surface.

## Frozen compatibility

The refactor does not change command names/options/exit codes, agent schema or
hashing, FASTQ/sample ordering, reference identities/checksums, run identity,
run directory layout, Snakemake rules/outputs, report location, analysis-plan
policy, full-length/3′-tag behavior, or numerical analysis scripts. Existing
frozen runs require no migration.

## Workflow and maintainer tooling review

The Snakefile, R/scientific scripts, Dockerfile, dependency locks, public just
recipes, and GitHub Actions were reviewed against their callers. They were
left unchanged: remaining duplication is contract-specific (real versus stub,
host versus container qualification, or release versus runtime checks).
Consolidating it would increase compatibility risk without improving the
interface/core boundary. Validation strength, image behavior, workflow rules,
and publishing permissions are unchanged.
