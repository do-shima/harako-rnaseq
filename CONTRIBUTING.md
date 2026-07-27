# Contributing to Harako-RNAseq

Harako-RNAseq welcomes focused bug fixes, tests, documentation, and
scientifically justified improvements consistent with its local single-user
scope.

## Before contributing

- Search existing issues and documentation.
- Do not post FASTQ files, patient information, credentials, confidential
  paths, or identifiable sample data.
- Keep one purpose per branch and pull request.
- Suggested branch prefixes are `fix/`, `feature/`, `docs/`, and `chore/`.
- Describe scientific assumptions and compatibility impact before changing
  analysis behavior.

## Development setup

Install Git, Docker with a Linux engine, and `just`. The supported development
path uses the repository Docker image:

```bash
just build
just smoke
just verify-smoke
```

Launch the UI with `just app` on Ubuntu/Linux or `just app-ps` in Windows
PowerShell. `INPUT` and `OUT` default to repository-local directories.

For host tests, install the hashed runtime and test locks, then run:

```bash
python -m pip install --require-hashes -r requirements.lock.txt
python -m pip install --require-hashes -r requirements-test.lock.txt
python -m pytest -q
```

CI-parity targets are:

```bash
just ci-host
just ci-docker
just ci-all
```

Also run:

```bash
just --list
just doctor-ui
git diff --check
```

Do not add test dependencies to a production container at runtime except in a
documented disposable test container.

To refresh the Python 3.11 test lock after editing `requirements-test.in`:

```bash
python -m pip install pip-tools==7.4.1
python -m piptools compile --generate-hashes \
  --output-file requirements-test.lock.txt requirements-test.in
```

Review dependency changes. The production image does not install the test
lock.

## Tests and fixtures

- Add focused regression tests for every behavior change.
- Keep smoke tests offline and end-to-end.
- Use small synthetic or public fixtures only.
- Do not add production FASTQ, reference bundles, BAM files, patient data, or
  generated run outputs.
- Preserve Windows and Unix path behavior where applicable.
- Confirm public reports remain self-contained and do not expose host paths.

Scientific behavior changes require:

- a documented policy or method;
- pure-unit coverage where practical;
- real or representative integration coverage;
- explicit edge cases and failure behavior; and
- migration notes when frozen configurations or outputs are affected.

## Documentation and output contracts

Update the relevant English and Japanese public claims together. Link focused
details from [docs/index.md](docs/index.md) instead of expanding the landing
page with maintainer commands.

Changes to stable output filenames, schemas, run identity, frozen
configuration, references, or cache behavior require explicit compatibility
documentation and migration notes. Do not silently reinterpret existing runs.

## Pull requests

Include:

- purpose and scope;
- tests executed with exact results;
- output-contract and migration impact;
- documentation changes;
- scientific behavior changes and limitations; and
- any platform-specific validation not performed.

Review generated files and `git status` before submission. Do not include
local inputs, outputs, caches, reports, or secrets.

Release publication is maintainer-controlled. Contributor and Dependabot
branches must never publish images or create releases.

## Originality and licensing

Submitted code, documentation, tests, and assets must be original or legally
reusable under terms compatible with this repository. Identify third-party
material and its license; do not assume acknowledgement alone grants reuse.

Contributions accepted into Harako-RNAseq are distributed under the
[PolyForm Noncommercial License 1.0.0](LICENSE). This repository does not
require or imply a separate Contributor License Agreement.

## AI-assisted contributions

Disclose material AI assistance in the pull request when it affected code,
tests, documentation, or review. The human contributor remains responsible
for requirements, scientific interpretation, acceptance, validation,
licensing, and provenance. AI output must be reviewed before submission and
must not be represented as independently validated.
