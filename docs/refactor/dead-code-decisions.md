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

The table will be updated at each removal milestone. “No deletion” is the
correct result for any candidate that fails even one required evidence gate.

