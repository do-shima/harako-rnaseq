# Release Checklist

Scientific analysis plan:
- [ ] Eligibility policy tests cover invalid, QC-only, and differential designs.
- [ ] New frozen configs and manifests contain the same `analysis_plan`.
- [ ] QC-only smoke produces `deseq2/status.json` and a header-only `results.tsv`.
- [ ] Differential and QC-only reports remain self-contained.
- [ ] Enrichment is absent from the QC-only DAG.

Pre-flight:
- `just build`
- `just doctor-ui`
- `python -m pytest tests/test_ui_session_run_config.py tests/test_ui_public_log_resolution.py tests/test_ui_refactor_utils.py tests/test_i18n.py`

Manual UI checks:
- Two-session isolation: start session A and session B, change `project_name` or sample table in A, refresh both, confirm files stay isolated under `/output/ui_sessions/<ui_session_id>/...` and B is unchanged.
- Frozen run config: start a run, confirm `<run_dir>/run/config_resolved.yaml` exists, change current UI config, then `Resume` or `Recover` the same run and confirm it still uses the frozen run-local config.
- Public-safe errors: run normal mode with `HARAKO_DEV_UI` unset, trigger a failure, confirm the page shows translated summaries without raw traceback text or host-absolute paths.
- Open existing gating: choose a run with no `<run_dir>/report/report.html` and confirm `Open existing report only` is unavailable; only `Resume` and log inspection paths should remain.
- `project_name` persistence: set a custom project name, refresh/rerun, reopen the same run, and confirm the name persists in the UI and frozen config.
- Branding: confirm the app header logo renders and generated `report/report.html` includes the expected Harako branding.
- Enrichment gating: confirm `n=1` or one-replicate-per-condition inputs keep enrichment disabled with the expected warning; confirm valid replicate counts enable it.

Launcher checks:
- Ubuntu/Linux: `just app`
- macOS: record validation evidence before changing its support status
- Windows PowerShell: `just app-ps`

CI and container release gates:

- [ ] The maintainer approves every author/committer identity exposed by
  reachable history; `.mailmap` does not remove raw historical metadata.
- [x] Historical local-path disclosure was rejected and the affected history
  was removed in an isolated mirror.
- [ ] Schema 2 approval verifies the evidence hash, rewritten base, current
  zero-occurrence audit, and main-only publication scope.
- [ ] The new private candidate repository contains only sanitized `main`; old
  tags and unique/development branches remain private-archive-only.
- [ ] Reachable-history, large-blob, branch/tag, and confidential-data reviews
  have no unresolved public-release blocker.
- [ ] `python-tests`, `windows-path-tests`, `governance-docs`,
  `docker-tests`, and `release-readiness` pass.
- [ ] The strict readiness check passes for the release version and tag.
- [ ] Runtime license inventory has no unresolved direct dependency.
- [x] Transitive `NOASSERTION` entries are classified and the ten exact R
  source archives verify against installed versions and pinned hashes.
- [ ] The exact release-candidate image has a reviewed vulnerability scan.
- [ ] The scan is no more than seven days old and matches the exact candidate
  image ID; all High findings are dispositioned and no Critical blocker remains.
- [ ] The image contains Harako licensing/citation/provenance files, fastp's
  notice, Salmon's GPL/source, and the exact ten-package R source bundle.
- [ ] Image inspection reports `linux/amd64` and the expected OCI metadata.
- [ ] BuildKit provenance and SBOM are enabled for the pushed image.
- [ ] A prerelease receives its exact tag and `beta`, never `latest`.
- [ ] GitHub attestation covers the digest returned by the push.
- [ ] Repository and GHCR package visibility are public before announcing the
  image.
- [ ] Only the new sanitized repository is made public; the old repository
  remains private as an archive.

See [release publishing](release-publishing.md) for manual GitHub steps.

Run outcome checks:
- Successful run: confirm `report/report.html` opens, output tabs render, and run logs are discoverable from the failure/success UI.
- Missing-report run: confirm the UI does not offer report-only open before `report/report.html` exists.
- Dev diagnostics: run with `HARAKO_DEV_UI=1` and confirm the dev expander shows `ui_session_id`, `run_id`, session config path, run-local config path, and validation summary.
