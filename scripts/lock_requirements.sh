#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python -m pip install --no-cache-dir pip==24.3.1 pip-tools==7.4.1
python -m piptools compile \
  --generate-hashes \
  --resolver=backtracking \
  --no-upgrade \
  --allow-unsafe \
  --output-file requirements.lock.txt \
  requirements.in
python -m piptools compile \
  --generate-hashes \
  --resolver=backtracking \
  --no-upgrade \
  --output-file requirements-test.lock.txt \
  requirements-test.in
