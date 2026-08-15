# Full architecture refactor baseline

This maintainer record captures the behavior and environment before production
code was changed. It is not a release qualification record.

## Repository state

- Repository root: `D:/git/harako-rnaseq-final-release-verify`
- Branch: `refactor/full-architecture-cleanup`
- Start commit: `332abc4f4a3e6d1bf61cec87b48d4a995c9657f7`
- `origin/main`: `332abc4f4a3e6d1bf61cec87b48d4a995c9657f7`
- Harako version: `0.3.0-beta.2`
- Working tree before the branch was created: clean
- Merge, rebase, and cherry-pick state: none

## Environment

| Component | Baseline |
|---|---|
| Host Python | 3.9.13 (`C:/Users/do/anaconda3/python.exe`) |
| Docker client/server | 29.7.2 / 29.7.2 |
| Host Java | unavailable on `PATH` |
| Host Snakemake | unavailable in the host Python environment |
| Container Python | 3.11.15 |
| Container R | 4.5.0 |
| Container Snakemake | 9.13.4 |
| Container fastp | 0.23.4 |
| Container Salmon | 1.10.0 |
| Container DESeq2 | 1.48.2 |
| Container tximport | 1.36.1 |
| Pytest collection | 412 tests |

Host Java and Snakemake absence are environment limitations, not repository
failures. The supported all-in-one container supplied both paths.

## Qualification before refactoring

| Command | Result |
|---|---|
| Python compile check | PASS, 102 Python files |
| `python -m pytest -q` | PASS, 400 passed, 12 skipped, 2 dependency deprecation warnings |
| `just agent-smoke` | PASS |
| `just verify-agent-smoke` | PASS |
| `just smoke` | PASS |
| `just verify-smoke` | PASS, including self-contained report verification |
| strict release-readiness, version `0.3.0-beta.2` | PASS, including 12 reference hashes |
| `just ci-host` | PASS, 400 passed, 12 skipped |
| `just ci-docker` | PASS, 410 passed, 2 skipped; real R stack and GUI doctor included |
| `git diff --check` | PASS |

The two host warnings came from Streamlit using Pillow's deprecated
`BILINEAR` symbol and were pre-existing third-party warnings.

## Canonical contract values

The host deterministic agent smoke produced:

- differential plan ID:
  `77829db9aeae6ea6fdcbd70ba21ea2bd30be1979ee4f05853bd229d023292135`
- differential approval hash:
  `1e4ce84bbed4f1f5fbfe114fa41255b57df7471143066de4188136e07abf07e0`
- QC-only plan ID:
  `4b320a22efcc3fe0bd69717106441aa21fffedfb10327f1485f1c6829eeb0c43`
- QC-only approval hash:
  `7c0dbe09f9f21d5f4201a69d7a15da1255e6eb700930885b44f34a9ad46b490c`

Container smoke hashes differ because execution-relevant absolute roots are
different. This is expected; hashes must remain stable for the same canonical
payload and environment.

## Baseline size

Line counts use tracked text files and include comments and blank lines:

- production Python (application, scripts, workflow helpers): 55 files / 16,730 lines
- workflow and R sources: 7 files / 2,375 lines
- tests and test workflow sources: 58 files / 8,970 lines before the new
  characterization module
- Markdown documentation: 53 files / 4,534 lines
