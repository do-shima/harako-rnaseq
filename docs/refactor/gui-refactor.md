# GUI refactor report

## Original responsibilities

`app/ui/app_ui.py` contained every wizard page, session defaults, FASTQ and
sample glue, reference selection/fetch UI, resource detection, configuration
writes, run metadata writes, Snakemake process creation, recovery, logs, and
results presentation.

## Extracted structure

- `app/ui/pages/project.py`: engine, layout, protocol, threads, mount state.
- `app/ui/pages/samples.py`: subdirectory selection, pairing/editor display,
  and issue presentation.
- `app/ui/pages/reference.py`: preset/custom-reference selection, cache state,
  fetch progress, and reference status presentation.
- `app/ui/pages/analysis.py`: mode explanation, contrasts, and enrichment UI.
- `app/ui/state.py`: centralized, copied session defaults and idempotent state
  initialization.
- `app/services/run_contract.py`: frozen configuration, run metadata, and run
  directory preparation.
- `app/adapters/{filesystem,process,snakemake,environment}.py`: direct effects.

## State and action flow

Draft state remains under `/output/ui_sessions/<ui_session_id>/`; frozen state
remains under the run's `run/` directory. Initialization preserves existing
session values and copies mutable defaults. Page changes still invalidate the
same draft validation state. Save, Validate, Dry run, Run, Resume, Recover, and
Open existing retain their order and gating, but direct process construction
and file mutation no longer occur in the Streamlit composition module.

Domain/input/workflow errors continue through the existing localized error
presentation. Live process status and recovery diagnostics are unchanged.

## Preserved UX and visible changes

Page order, primary labels, widget keys, default values, disabled states,
approval gating, report access, and English/Japanese text are preserved. There
is no visual redesign. The refactor makes no intentional visible change.
