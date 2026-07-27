# Architecture

Harako-RNAseq is a local, single-user application packaged as one Docker image.

## Application layers

- Streamlit provides the bilingual graphical interface.
- Neutral Python modules handle validation, sample normalization, reference
  resolution, analysis eligibility, configuration, and run identity.
- Snakemake owns workflow scheduling, resumability, and stable output targets.
- Real scripts run fastp, Salmon, tximport, DESeq2, optional enrichment, and
  R Markdown reporting.
- Stub scripts provide small offline smoke fixtures and are never presented as
  scientific results.

## Session and run state

Browser draft state is isolated below
`/output/ui_sessions/<ui_session_id>/`. It includes the editable configuration,
sample table, UI state, effective configuration, and session logs.

Starting a run creates a run directory below `/output/data_out/`. The run ID
is derived from the executable manifest payload, including the normalized
sample table, reference provenance, and frozen `analysis_plan`.

The run-local `run/config_resolved.yaml` is immutable input for Resume and
Recover. Current UI state does not replace a frozen configuration.

## References

`workflow/ref_manifest.yaml` is the source of truth for canonical preset IDs,
legacy aliases, provider/assembly/release metadata, URLs, and SHA256 hashes.
The resolver prefers canonical caches, verifies compatible legacy caches in
place, and records resolved container paths and cache provenance.

Custom references remain outside the built-in manifest trust claim.

## Analysis plan

`app/analysis_eligibility.py` produces the policy-versioned plan. Snakemake and
R recount the frozen sample table and reject a plan mismatch instead of
changing modes silently.

The workflow preserves stable DESeq2 output paths in both modes.
`deseq2/status.json` distinguishes actual artifacts from placeholders and is
the downstream source of truth for enrichment and reporting.

## Reporting

The report rule consumes workflow artifacts, DESeq2 status, reference
provenance, and captured versions. The generated HTML is checked for external
resources so it can be opened independently of the running application.

## Security boundary

Harako assumes one trusted local user controlling Docker, the mounted inputs,
and the output directory. It does not provide authentication, tenant
isolation, authorization, encrypted storage, or hosted-service hardening.
Do not expose the Streamlit port to untrusted networks.
