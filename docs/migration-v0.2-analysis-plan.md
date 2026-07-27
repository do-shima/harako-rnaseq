# Migration: v0.2 analysis plans

New session and run-local configs freeze `analysis_plan` policy version 1.
The plan participates in run identity and Resume/Recover uses the frozen plan,
not current UI state.

Legacy frozen runs are not rewritten:

- A legacy design that meets the current differential gate may resume with a
  transient compatibility plan and a warning. Its run ID is unchanged.
- A legacy design below the gate cannot resume inferential processing or be
  silently converted in place. Create a new run to use QC-only mode. Existing
  files and completed reports remain available.

Snakemake and R recount the frozen sample table. A mismatch with a stored plan
is a blocking error rather than an automatic mode change.
