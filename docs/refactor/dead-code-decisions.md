# Dead-code decision table

Static searches identify candidates only. Deletion requires reference checks,
dynamic-use review, targeted tests, full qualification, and canonical-output
comparison.

| Candidate | Evidence reviewed | Current decision | Deletion commit | Reason retained or removed |
|---|---|---|---|---|
| Compatibility helper functions in `app/ui/app_ui.py` | wrappers are imported directly by existing tests and may be callback targets | compatibility-only, retain initially | — | preserve import and Streamlit callback behavior while implementations move |
| Compatibility aliases in `app/agent_cli.py` | not shown as primary commands but protect earlier local automation | compatibility-only, retain | — | agent public compatibility; not registered as obsolete primary commands |
| `scripts/check_public_beta_candidate.py` | no direct just/docs reference; imports release-readiness logic | retained pending deprecation | — | may be invoked manually by release maintainers |
| `scripts/create_release_approval_template.py` | no static caller | retained due to dynamic-use uncertainty | — | release utility can be invoked directly |
| `scripts/fetch_copyleft_r_sources.py` and `verify_copyleft_r_sources.py` | Dockerfile invokes them by module name, so filename-only search under-reports use | current-app-only, retain | — | image corresponding-source gate |
| `scripts/release_approvals.py` | imported by release scripts/tests even where filename text is absent | current-app-only, retain | — | release approval policy |
| `scripts/review_sbom_license_assertions.py` | CI/release use may invoke the module directly | retained pending full CI audit | — | supply-chain gate; removal risk exceeds benefit |
| Duplicate-looking stub helpers in `scripts/` and `workflow/scripts/` | names overlap but SHA-256 differs and workflow references both paths | current-app-only, retain until semantic comparison | — | path and behavior are workflow contracts |
| Legacy frozen-run protocol handling | explicit tests and public compatibility requirement | compatibility-only, retain | — | old runs must remain readable and preserve matrix handoff |
| Historical schema-v1 agent plan handling | legacy fixture and hash tests | compatibility-only, retain | — | old plan IDs and approval hashes must remain inspectable |
| 18 unreferenced helpers in `app/ui/app_ui.py` | AST call count plus searches across app, tests, workflow, scripts, justfile, CI, docs, and release tooling; targeted and full host tests | deleted | `81848ac` | no callback, session-state, dynamic, workflow, support, or compatibility use |
| `app/agent.py` implementation body | public imports and agent CLI depend on module path | compatibility-only facade | `112904b` | implementation moved to focused services; imports retained |
| `app/run.py`, `app/analysis_eligibility.py`, `app/library_protocol.py`, `app/ui/scan.py` | existing tests/import paths and potential downstream local automation | compatibility-only facades | `99011cd` | preserve established Python imports while centralizing implementation |
| Summary-page presentation in `app/ui/app_ui.py` | live process/session callbacks and Save/Validate/Dry run/Run/recovery semantic tests | current-app-only, retain | — | further mechanical splitting would create a large callback registry without moving domain effects |

The table will be updated at each removal milestone. “No deletion” is the
correct result for any candidate that fails even one required evidence gate.
