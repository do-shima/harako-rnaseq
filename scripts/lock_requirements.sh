#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python -m pip install --upgrade --no-cache-dir pip-tools==7.4.1
pip-compile \
  --generate-hashes \
  --resolver=backtracking \
  --output-file requirements.lock.txt \
  requirements.in
