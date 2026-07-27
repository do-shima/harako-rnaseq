# rnaseq_pipeline

Language:
- English: `README.md`
- Japanese: `README.ja.md`

Minimal, Docker-ready RNA-seq pipeline skeleton powered by Snakemake. This repo provides a single entrypoint
(`python -m app run ...`) and a tiny smoke test that runs end-to-end without network downloads.

Harako-RNAseq is a public-beta, source-available application for local,
single-user academic and non-commercial RNA-seq analysis. It is not a hosted
multi-user service.

Harako selects an explicit analysis mode from the normalized sample table.
Inferential differential-expression analysis requires at least two conditions
and at least two samples in every condition. Other structurally valid designs
run in **QC-only mode**: preprocessing, Salmon quantification, gene-level
tximport counts and TPM, descriptive normalization, applicable QC, and the
self-contained report remain available, but DE contrasts and enrichment are
not run. This minimum gate is not a power calculation and does not establish
biological independence or an adequate experimental design.

## Origins and acknowledgements

Harako-RNAseq was inspired by the
[ikra](https://github.com/yyoshiaki/ikra) RNA-seq pipeline centered on Salmon.
Harako-RNAseq is an independently implemented project that extends this concept
with a graphical user interface, cross-platform Docker operation, reproducible
run management, differential-expression and quality-control workflows, and
self-contained reporting. Harako-RNAseq is not an official successor to, or
endorsed by, the ikra project.

### AI-assisted development

Development of Harako-RNAseq was assisted by OpenAI Codex for implementation,
refactoring, test generation, documentation, debugging, and code review.
All scientific interpretations, architectural decisions, validation,
licensing decisions, and release decisions were made and approved by the
project maintainer. AI-generated suggestions were reviewed before inclusion
in the repository.

This acknowledgement does not imply endorsement, sponsorship, or certification
of Harako-RNAseq by OpenAI.

## License and permitted use

Harako-RNAseq is source-available under the
[PolyForm Noncommercial License 1.0.0](LICENSE).

It may be used, modified, and redistributed for permitted noncommercial
purposes, including academic, educational, and public research use, subject to
the license terms.

Commercial use, commercial services, resale, and use for an anticipated
commercial application are not granted by this license and require a separate
written license or permission.

Third-party tools and libraries used by or distributed with Harako-RNAseq
remain subject to their respective licenses.

Commercial licensing inquiries may be submitted through the repository's
[GitHub Issues](https://github.com/do-shima/harako-rnaseq/issues).

Branch naming (standardized, 1 PR = 1 purpose):
- main: always green
- feature/*: human work
- codex/*: Codex work
- topic suffix is short, kebab-case
- do not mix multiple goals in one PR

## Quickstart

Build image:

```
just build
```

## Windows: pytest (PowerShell)

Use `py -m pytest` as the standard command on Windows.

PowerShell (venv):
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.lock.txt
py -m pytest
```

Windows (B方式2: Docker一時pytest, host Python不要):
```powershell
just test-docker
```

PowerShell:
```
just build-ps
```

SRA/ENA to single-UI (recommended beginner flow):

1. Build image (or only when missing):
```
just build-if-needed
```
PowerShell:
```
just build-if-needed-ps
```
2. Fetch FASTQ + `samples.tsv` into repo-local input roots:
```
RUN_TABLE=path/to/SraRunTable.txt just srr
# or
SRR_LIST=path/to/srr_list.txt just srr
# or
SRR="SRR123 ERR456 DRR789" just srr
```
PowerShell:
```
$env:RUN_TABLE="path\\to\\SraRunTable.txt"; just srr-ps
# or
$env:SRR_LIST="path\\to\\srr_list.txt"; just srr-ps
# or
$env:SRR="SRR123 ERR456 DRR789"; just srr-ps
```
3. Use printed `run_id` and launch UI:
```
$env:INPUT="<repo>/data_in/srr/<run_id>"
$env:OUT="<repo>/data_out/<run_id>"
just app-ps
```

Notes:
- Input auto-detection supports RunSelector table (`.txt/.tsv/.csv`) and accession list files.
- Input source priority in `just srr` (`srr-ps` on PowerShell): `RUN_TABLE` > `SRR_LIST` > `SRR`.
- `condition` is empty by default. Auto-fill only when explicitly requested:
  - `CONDITION_FROM=<column_name> just srr`
  - `CONDITION_MAP=path/to/map.tsv just srr` (2 columns: `sample_or_run<TAB>condition`)
- Re-download existing files when needed: `SRR_FORCE=1 just srr`
- Fetch logs/manifests:
  - `data_in/srr/<run_id>/run/manifest.json`
  - `data_in/srr/<run_id>/run/srr_fetch.log`

Reproducibility scope:
- Docker base image is digest-pinned.
- apt uses a fixed Debian snapshot timestamp.
- Python dependencies are hash-locked in `requirements.lock.txt`.
- Salmon/Fastp binaries are downloaded from fixed URLs with SHA256 verification.
- R/CRAN uses a pinned snapshot and Bioconductor release.
- Required report/runtime R packages are installed in-image: `data.table`, `readr`, `dplyr`, `ggplot2`, `rmarkdown`, `jsonlite`, `yaml`, `tximport`, `DESeq2`, `apeglm`, `EnhancedVolcano`, `clusterProfiler`, `fgsea`, `AnnotationDbi`, `GO.db`, `org.Hs.eg.db`, `org.Mm.eg.db`, `org.Rn.eg.db`.

Scientific output notes:
- DESeq2 uses gene-level tximport counts, not TPM.
- Gene-level TPM is a descriptive abundance output.
- `deseq2/status.json` is the machine-readable source of truth for analysis
  mode and artifact availability.
- In QC-only mode, `deseq2/results.tsv` retains its columns but has zero data
  rows; no p-values, adjusted p-values, or pseudo-contrasts are fabricated.

Interactive setup (no downloads, just-only flow):

```
just init INPUT=path/to/input OUT=out
```

This writes `OUT/config.yaml` and `OUT/metadata/samples.tsv` and sets `input: /input`, `output: /output`.

Docker note: when using `input=/input` in Snakemake, you can store relative FASTQ paths in `samples.tsv`
and they will resolve under `/input`. Avoid `/app`-prefixed paths.

PowerShell (env vars required for just arguments):

```
$env:INPUT="D:\path\to\input"; $env:OUT="out"; just init
```

cmd.exe:

```
set INPUT=D:\path\to\input & set OUT=out & just init
```

Validate a config (recommended):

```
INPUT=path/to/input OUT=out just validate-out
```

Validation errors now include row numbers for missing `sample`/`condition`/`fastq1` in `samples.tsv`.

PowerShell:
```
$env:INPUT="D:\path\to\input"; $env:OUT="D:\path\to\out"; just validate-out
```

cmd.exe:
```
set INPUT=D:\path\to\input & set OUT=D:\path\to\out & just validate-out
```

Advanced (validate a repo-local config path):
```
CONFIG=out/config.yaml just validate
```

Run on your data (real pipeline, recommended):

```
OUT=out INPUT=path/to/input just run-real
```

PowerShell:
```
$env:INPUT="D:\path\to\input"; $env:OUT="D:\path\to\out"; $env:THREADS="4"; just run-real
```

cmd.exe:
```
set INPUT=D:\path\to\input & set OUT=D:\path\to\out & set THREADS=4 & just run-real
```

Contrast selection (recommended):
- Use `contrast_mode: ref` with `contrast_ref: control` (generates `stz_vs_control`).
- `contrast_pairs` can specify explicit A,B pairs.
- Legacy `contrasts: ["A_vs_B"]` is deprecated; use `contrast_mode` + `contrast_ref`/`contrast_pairs`.

Run smoke test (no downloads):

```
just smoke
```

Optional: include enrichment fixture check during smoke:

bash/zsh:
```
ENABLE_ENRICHMENT=1 just smoke
```

PowerShell:
```
$env:ENABLE_ENRICHMENT="1"; just smoke
```

cmd.exe:
```
set ENABLE_ENRICHMENT=1 & just smoke
```

One-shot verification (smoke + self-contained + key outputs):

```
just verify-smoke
```

Windowsでの手動テスト（Docker一時pytest）:
```powershell
just test-docker
```
- `build-if-needed-ps` 実行後、コンテナ内で `python -m py_compile`（`app/ui`, `tests`）を実行します。
- その後 `python -m pip install -q pytest` を一時実行し、`python -m pytest -q` を走らせます。

GUI (recommended):

Step A: set host mounts (PowerShell example):
```
$env:INPUT="D:\path\to\input"
$env:OUT="D:\path\to\out"
```

Step B: build only if image is missing:
```
just build-if-needed
```
PowerShell:
```
just build-if-needed-ps
```

Step C: launch the single UI (one command):
```
just app
```

Linux/Mac note:
- `INPUT`/`OUT` を未指定で `just app` を実行した場合、`./input` と `./output`（repo 直下）を自動利用します。
- 必要ディレクトリは起動前に自動作成されます。
- そのまま `just app` 1回で起動できます。

PowerShell policy:
- `just app-ps` も `INPUT`/`OUT` 未指定時は repo 直下 `input` / `output` を自動利用します。
- 明示したい場合は次のコマンドを使用します。

PowerShell (copy/paste, explicit `INPUT`/`OUT`):
```
$env:INPUT="D:\path\to\input"; $env:OUT="D:\path\to\out"; just app-ps
```

PowerShell (persist example 1: user profile):
```powershell
Add-Content -Path $PROFILE -Value '$env:INPUT="D:\path\to\input"'
Add-Content -Path $PROFILE -Value '$env:OUT="D:\path\to\out"'
```

PowerShell (persist example 2: manual `.env.ps1`):
```powershell
Set-Content .env.ps1 '$env:INPUT="D:\path\to\input"`n$env:OUT="D:\path\to\out"'
. .\.env.ps1
just app-ps
```

PowerShell (direct docker run, `${env:...}` form):
```
$env:REPO="D:\path\to\rnaseq_pipeline"; $env:INPUT="D:\path\to\input"; $env:OUT="D:\path\to\out"
docker run --rm -p 127.0.0.1:8501:8501 -v "${env:REPO}:/app" -v "${env:INPUT}:/input:ro" -v "${env:OUT}:/output" rnaseq_pipeline bash -lc 'cd /app && streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false --logger.level=warning'
```

bash/zsh:
```
INPUT="/path/to/input" OUT="/path/to/out" just app
```

UI is intended for local use. Open `http://127.0.0.1:8501` (or `http://localhost:8501`) in your browser.
Use the sidebar `Language` selector to switch between English (default) and Japanese.
`just app` / `just app-ps` filter Streamlit startup URL banner lines; direct `streamlit run` may still print them as normal runtime output.
PowerShell import check (UI troubleshooting): `just ui-import-check-ps`.

Production run (real data, cross-platform):

bash/zsh:
```
export INPUT=/path/to/data
export OUT=/path/to/out
just build-if-needed
just app           # Save session-scoped config.yaml + samples.tsv
just validate-out
ENGINE=real THREADS=8 just run-out
just check
```

PowerShell:
```
$env:INPUT="D:\path\to\data"
$env:OUT="D:\path\to\out"
just build-if-needed-ps
just app-ps           # Save session-scoped config.yaml + samples.tsv
just validate-out
$env:ENGINE="real"; $env:THREADS="8"; just run-out-ps
just check
```

If a run fails, start with `just logs`. To re-generate the report only, use `just report-out`. To locate the report path, use `just open-out`.
After a successful run, verify outputs with `just verify-real`.
Default is strict self-contained checking (fails with exit 49 if external URLs exist).
To allow external URLs and warn only: `SELFCONTAINED=warn just verify-real`.
To inspect remaining external references: `just debug-report-externals`.

Recommended /input layout:
- `/input/*.fastq.gz` (or nested subdirectories)
- `/input/refs/...` (keep references under the same mount for simplicity)
PowerShell refs download: set `INPUT` to your input-base folder; `fetch-refs-ps` writes under `INPUT\refs` (mounted as `/input/refs` in the container).

Contrast selection (condition-based):
- `contrast_mode: ref` with `contrast_ref: control` generates `stz_vs_control`.
- `contrast_mode: select` uses explicit pairs like `[control, stz]`.
- Legacy `contrasts: ["A_vs_B"]` is deprecated; use `contrast_mode` + `contrast_ref`/`contrast_pairs`.

Note: Save/Dry-run are disabled until required references are selected (transcripts/genome/gtf or preset).

Web UI updates:
- Project name is editable and run output directories are named as `{project_slug}_{run_id}`.
- Project name persists across reruns and is written into the saved UI config payload.
- UI draft state is isolated per browser session under `/output/ui_sessions/<ui_session_id>/...` instead of shared `/output/config.yaml` and `/output/run/...` files.
- Starting a run freezes immutable run inputs under `/output/data_out/<run_id>/run/`; resume/recover/unlock always read `config_resolved.yaml` from that run-local folder.
- `Validate` and `Dry-run` are exposed separately in Summary with numbered actions (`1. Save`, `2. Validate`, `3. Dry-run`, `4. Run`).
- `Auto-fill condition from sample` normalizes replicate suffixes (e.g. `STZ_1`/`STZ_2` -> `STZ`, `Con-1` -> `Con`; accessions like `SRR14340927` are kept unchanged).
- Enrichment is auto-disabled in the GUI unless at least 2 conditions are present and each condition has at least 2 samples.
- Run behavior options are collapsed under an expander and recommended defaults are used by default.

UI storage layout:
- `/output/ui_sessions/<ui_session_id>/config.yaml`
- `/output/ui_sessions/<ui_session_id>/metadata/samples.tsv`
- `/output/ui_sessions/<ui_session_id>/ui_state.json`
- `/output/ui_sessions/<ui_session_id>/ui_effective_config.json`
- `/output/ui_sessions/<ui_session_id>/logs/ui_events.log` (and other UI session logs)
- `/output/data_out/<run_id>/run/config_resolved.yaml`
- `/output/data_out/<run_id>/run/metadata/samples.tsv`
- `/output/data_out/<run_id>/run/manifest.json`
- `/output/data_out/<run_id>/run/metadata.json`

Condition auto-fill normalization rules:
- Applied only when `condition` is empty and auto-fill is enabled.
- Input sample string is trimmed before normalization.
- If sample is a run accession (`SRR\d+`, `ERR\d+`, `DRR\d+`), keep as-is.
- Remove only trailing replicate suffixes:
  - separator + digits: `_1`, `-2`, `.3`, `_02`, etc.
  - optional `rep` form at the end: `rep1`, `_rep2`, `-rep3`, `.rep4`.
- Only the tail is normalized; internal tokens are not rewritten.
  - Example: `Sample_A_1` -> `Sample_A`.
- If normalization would produce an empty/invalid label, fallback to original sample.

Note: open `http://127.0.0.1:8501` (or `http://localhost:8501`) in your browser. If Streamlit logs show `0.0.0.0:8501`, that is a bind address, not a browser URL.

Quick diagnostics:
- `docker ps` should show port `8501` published
- open `http://127.0.0.1:8501`

Self-contained report check (PowerShell ok):

bash/zsh:
```
just check-report-selfcontained out_smoke/report/report.html
```

PowerShell:
```
just check-report-selfcontained out_smoke/report/report.html
```

cmd.exe:
```
just check-report-selfcontained out_smoke/report/report.html
```

Note: this check runs inside Docker so it does not require Python on the host (PowerShell-friendly).
Compatibility: `just check-report-selfcontained REPORT=out/report/report.html` is also accepted.

Exit codes:
- 0: OK (self-contained)
- 2: usage / missing report
- 49: external references detected (http/https, cdn, fonts)

For advanced Snakemake/docker commands, see [Advanced usage](#advanced-usage) and [PowerShell snippets](#powershell-safe-command-snippets).
If you hit errors, start with [Troubleshooting](#troubleshooting-10-quick-fixes).

Dependency lock refresh (maintainers):
```
bash scripts/lock_requirements.sh
```

## Advanced usage

Windows-friendly one-liners are in [PowerShell snippets](#powershell-safe-command-snippets).

GUI (optional, preview):
- Preferred: `just app` after setting `INPUT` and `OUT` (PowerShell: `just app-ps`).
- Legacy launcher recipes are deprecated.

Run report with Snakemake using a bind mount (expects `/output/config.yaml` from `just init`):

```
OUT=path/to/output INPUT=path/to/input just run-real
```

Run report for rat (bind mount + species override):

```
OUT=path/to/output INPUT=path/to/input just run-real-rat
```

Override engine/threads (optional):

```
ENGINE=real THREADS=4 just run INPUT=path/to/input OUTPUT=out CONFIG=path/to/config.yaml ALIGN=none

PowerShell:
```
$env:INPUT="D:\path\to\input"; $env:OUT="D:\path\to\out"; $env:CONFIG="D:\path\to\config.yaml"; $env:ENGINE="real"; $env:THREADS="4"; just run-ps
```

PowerShell run_id mode (recommended for resumeable runs):
```
$env:INPUT="D:\path\to\input"
$env:OUT="D:\path\to\out_base"
$env:CONFIG="D:\path\to\config.yaml"
just run-ps            # creates OUT\data_out\<run_id>
# To reuse an existing run:
$env:RUN_ID="..."
just run-ps
# Snakemake helpers:
just unlock-ps
just resume-ps
```

PowerShell (Windows) stable Snakemake helpers for a specific run_id output:
```
# OUT should be the run_id output dir (example: D:\path\to\out_base\data_out\<run_id>)
$env:INPUT="D:\path\to\input"
$env:OUT="D:\path\to\out_base\data_out\<run_id>"
just windows-unlock-ps
just windows-dry-run-ps
just windows-run-ps
```

Common run flags (pass via `ARGS`):

```
ARGS="--dry-run --printshellcmds --quiet-reason" just run INPUT=... OUTPUT=... CONFIG=...
```

Recommended Snakemake flags (pass via `ARGS` to `just run-real`):

```
ARGS="--rerun-incomplete --printshellcmds --show-failed-logs" OUT=... INPUT=... just run-real
```

Portable dry-run (avoid version-sensitive flags):

```
ARGS="--dry-run --printshellcmds" just run INPUT=... OUTPUT=... CONFIG=...
```

Snakemake metadata/provenance warnings (when outputs exist but metadata is missing):

- Remove metadata cache and retry:

```
rm -rf out/.snakemake
```

- Or ask Snakemake to clean metadata for the current DAG:

```
python -m snakemake -s workflow/Snakefile --configfile config.yaml --cleanup-metadata
```

- If you intentionally want timestamps to drive re-runs:

```
python -m snakemake -s workflow/Snakefile --configfile config.yaml --rerun-triggers mtime
```

Targets should be placed last in Snakemake commands (to avoid `--configfile` being parsed as a target):

```
python -m snakemake -s workflow/Snakefile --configfile config.yaml --cores 4 -- report
```

Config override sanity check (single `--config`):

```
python -m app run --input /input --output /output --config config.yaml --dry-run
# The printed command should contain exactly one --config with all key=value pairs.
```

Just regression checks (PowerShell, copy/paste safe):

```
$env:INPUT="D:\data\input"; $env:OUT="D:\data\output"; $env:THREADS="4"
just init
just gentrome
just all-nobuild
just check-outputs
just check-salmon-meta
just logs
```

PowerShell note: avoid double-quote + backtick line continuations; prefer single-quoted bash -lc scripts.
LF/CRLF note: this repo uses `.gitattributes` to keep `*.R`, `*.py`, `Snakefile`, `justfile`, and `*.md` in LF on all platforms.
Windows Git setting (recommended):

```
git config --global core.autocrlf true
```

Optional enrichment outputs (disabled by default, contract additions only):
- `results/enrichment/contrast=<A>_vs_<B>/status.json` (always present when enabled)
- `results/enrichment/contrast=<A>_vs_<B>/ora_go_bp.tsv` and `gsea_go_bp.tsv` (when available)

PowerShell-safe command snippets (copy/paste friendly):

- Docker run (one line):

```
docker run --rm -v "${PWD}:/app" -v "D:\data\input:/input" -v "D:\data\output:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -- report'
```

- Docker run (PowerShell backtick line continuation):

```
docker run --rm `
  -v "${PWD}:/app" `
  -v "D:\data\input:/input" `
  -v "D:\data\output:/output" `
  rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -- report'
```

- Snakemake target placement reminder (targets must come after `--`):

```
python -m snakemake -s workflow/Snakefile --configfile config.yaml --cores 4 -- report
```

- Git upstream shorthand must be quoted in PowerShell:

```
git rev-parse '@{u}'
```

Git refname ambiguity cleanup (avoid `origin/` as a local branch prefix):

- Check for problematic refs:

```
git show-ref | Select-String -Pattern 'refs/heads/origin/'
```

- Delete accidental branches (example):

```
git branch -D origin/codex/whatever
```

- Helper (cross-platform):

```
just git-sanity
```

If workflow outputs were accidentally committed in the past, remove them once and commit the cleanup:

```
git rm -r --cached out .snakemake logs log tmp temp report output
git commit -m "Stop tracking workflow outputs"
```

## Troubleshooting (10 quick fixes)

Windows recommended shell: PowerShell (use `*-ps` recipes like `build-if-needed-ps`, `srr-ps`, `app-ps`). Git Bash/MSYS is supported but see the next section for path-conversion caveats.

- **PowerShell:** `ENABLE_ENRICHMENT=1 just smoke` does nothing → use `$env:ENABLE_ENRICHMENT="1"; just smoke`.
- **PowerShell:** host python missing / `exit 9009` → self-contained check runs in Docker; use `just check-report-selfcontained ...`.
- **Docker context mismatch (Windows):** if `docker ps` works but `docker exec` / mounts fail, run `docker context use default`.
- **MSYS/Git Bash path conversion (Windows):** errors like `can't open file '/app/C:/Program Files/Git/app/...'` → use PowerShell or prefix Docker with `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"`. This repo auto-guards via `just _docker -- ...` (MSYS/MINGW/CYGWIN only).
- **UI startup:** use `just app` (PowerShell: `just app-ps`). Launcher recipes are legacy.
- **REPORT= mixing:** `REPORT=out_smoke/report/report.html` is treated as a positional arg → prefer `just check-report-selfcontained out_smoke/report/report.html` (REPORT= also accepted).
- **Validate vs init mismatch:** `just validate CONFIG=...` can't see Windows paths → use `INPUT=... OUT=... just validate-out`.
- **PowerShell just args:** `just init INPUT=...` / `just run-ps INPUT=...` are parsed as recipes → set `$env:INPUT`/`$env:OUT`/`$env:CONFIG` and run `just init`/`just run-ps`.
- **Snakemake targets:** put targets after `--` → `python -m snakemake ... -- report`.
- **PowerShell Git:** `@{u}` needs quotes → `git rev-parse '@{u}'`.
- **Windows bind-mount metadata I/O errors:** `Error recording metadata for finished job ([Errno 5] Input/output error)` on `/output/.../.snakemake` means Snakemake metadata was being written onto the Windows bind mount. Current `python -m app run` and UI flows keep Snakemake work files in container temp storage instead; retry the run, and inspect `out/run/snakemake_*.txt` plus `out/logs/*` rather than `/output/.snakemake/log`.
- **CRLF/LF noise:** set `git config --global core.autocrlf true` (repo enforces LF).
- **Bad FASTQ paths:** `/app/...` in samples.tsv → use `/input`-relative paths.
- **Docker Desktop:** drive not shared → enable sharing for the drive (e.g., D:).

## Troubleshooting (Windows / Git Bash, MSYS)

Symptom: When running Docker from Git Bash/MSYS, container paths like `/app/...` can be rewritten into Windows paths, causing errors like missing scripts inside the container.

Workarounds:
- Recommended: use PowerShell on Windows.
- Alternative: disable MSYS path conversion with `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"`.
- This repo automatically applies the guard for `just _docker -- ...` invocations (MSYS/MINGW/CYGWIN only).

tximport version-mismatch regression test (tiny fixtures):

```
just test-tximport
```

tximport rat header regression test (tiny fixtures):

```
just test-tximport-rat-header
```

enrichment regression test (tiny fixtures):

```
just test-enrichment
```

Remote server usage (SSH + Docker):

```
ssh user@server
git clone <repo>
cd rnaseq_pipeline
just build
just init
just validate CONFIG=config.yaml
ENGINE=real THREADS=8 just run INPUT=/data OUTPUT=/results CONFIG=config.yaml ALIGN=none
```

Direct Snakemake dry-run (PowerShell-safe, single line):

```
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -n -p --latency-wait 60 --'
```

List available rules (make sure you mount the repo; `-v "/app"` will not work on Windows):

```
docker run --rm -v "$PWD:/app" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake -s workflow/Snakefile --configfile tests/config.yaml --config input=tests/data output=out --list-rules'
```

Or run the helper target:

```
just list-rules
```

PowerShell-safe alternatives:

```
docker run --rm -v "${PWD}:/app" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake -s workflow/Snakefile --configfile tests/config.yaml --config input=tests/data output=out --list-rules'
```

```
docker run --rm -v "$(Get-Location).Path:/app" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake -s workflow/Snakefile --configfile tests/config.yaml --config input=tests/data output=out --list-rules'
```

PowerShell-safe backtick version (copy/paste safe):

```
docker run --rm `
  -v "$(Get-Location).Path:/app" `
  rnaseq_pipeline bash -lc 'cd /app && python -m snakemake -s workflow/Snakefile --configfile tests/config.yaml --config input=tests/data output=out --list-rules'
```

Gentrome regression checks (PowerShell-safe, single line):

```
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- gentrome'
docker run --rm -v /path/to/output:/output rnaseq_pipeline bash -lc 'gzip -t /output/salmon/gentrome.fa.gz'
```

Run artifacts (real runs):
- `out/run/command.txt`, `config_resolved.yaml`, `versions.tsv`, `pip_freeze.txt`, `sessionInfo.txt`, `git_rev.txt`
- `out/run/snakemake_version.txt`, `snakemake_cmd.txt`, `snakemake_stdout.txt`, `snakemake_stderr.txt` (UI/Run execution logs)
- The HTML report links to these files.

QC outputs (real runs, under `out/deseq2`):
- `qc_summary.tsv`, `qc_summary.json`
- `padj_hist.png`, `lfc_hist.png`, `mean_vs_lfc.png`, `volcano.png`

Docker Desktop resources (real runs):
- CPU: 4+ cores recommended
- RAM: 8–16 GB recommended for medium datasets

Init regression check (relative FASTQ paths):

```
python -m app init --input-base /input --out /output
# enter FASTQ as Con_1_1.fq.gz (relative)
# /output/metadata/samples.tsv should contain Con_1_1.fq.gz (no /app prefix)
```

Stage targets (PowerShell-safe, single line):

```
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- salmon_index'
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- salmon_quant'
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- tximport'
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- deseq2'
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- deseq2_qc'
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- report'
```

Salmon meta_info.json check:

```
ls -lh /output/salmon/<sample>/meta_info.json /output/salmon/<sample>/aux_info/meta_info.json /output/salmon/<sample>/cmd_info.json || true
```

Windows PowerShell example (Docker Desktop):

```
docker run --rm -it -v "${PWD}:/app" -v "D:\data\input:/input" -v "D:\data\output:/output" rnaseq_pipeline bash -lc 'cd /app && python -m app init --input-base /input --out /output'
```
```

## Config

Example config (see `tests/config.yaml` for stub, `examples/config_real.yaml` for real):

- `engine`: `stub` or `real` (default real for user runs)
- `species`: `mouse|human|rat` (default: mouse)
- `samples`: list of sample IDs
- `fastq`: map of sample -> fastq path (relative to `--input` or absolute)
- `fastq1`/`fastq2`: optional maps for paired-end inputs
- `conditions` or `sample_table`: sample -> condition mapping or TSV
- `ref`: transcripts/genome/gtf paths (relative to `--input` or absolute)
- `ref_preset`: canonical preset ID (legacy aliases remain readable)
- `ref_manifest`: optional path to a pinned ref manifest file
- `tx2gene_tsv`: optional transcript-to-gene table for tximport
- `contrast_mode`: optional `ref|pairwise|select|legacy`
- `contrast_ref`: optional reference condition for `ref`
- `contrast_pairs`: optional list of `[A, B]` for `select`
- `contrasts`: optional legacy list of `A_vs_B` strings
- `threads`: optional integer
- `enrichment`: optional settings (enable/methods/alpha/lfc/top_terms/rank_metric)

See `config/schema.md` for the canonical config reference.

Species-specific custom refs (experimental GRCr8 example, not the default rat preset):

```
species: rat
ref:
  rat:
    transcripts_fasta: refs/rat/Rattus_norvegicus.GRCr8.cdna.all.fa.gz
    genome_fasta: refs/rat/Rattus_norvegicus.GRCr8.dna.toplevel.fa.gz
    gtf: refs/rat/Rattus_norvegicus.GRCr8.115.gtf.gz
```

Flat refs (no species nesting) still work and keep current mouse/human behavior.

The supported beta rat preset is `rat_ensembl_mratbn7_2` (Ensembl 113,
mRatBN7.2). The GRCr8/release-115 paths above are custom-reference examples and
must not share its cache directory.

Rat preset quickstart (PowerShell):
```
$env:INPUT="D:\data\input"; $env:OUT="D:\data\output"; $env:THREADS="4"
just init
just fetch-refs-rat
just rat-config
just dry-run-rat
just all-rat-nobuild
```

`just fetch-refs-rat` uses the checksum-pinned manifest-based mRatBN7.2 preset.

If refs are missing, you'll see an error like:
`[refs] species=rat missing_ref_key=transcripts_fasta tried=ref.transcripts_fasta,ref.rat.transcripts_fasta configfiles=[/output/config.yaml]`

Experimental GRCr8 custom-reference location:
- `/input/refs/<species>/Rattus_norvegicus.GRCr8.cdna.all.fa.gz`
- `/input/refs/<species>/Rattus_norvegicus.GRCr8.dna.toplevel.fa.gz`
- `/input/refs/<species>/Rattus_norvegicus.GRCr8.115.gtf.gz`

Quick ref existence check (PowerShell-safe, single line):
```
docker run --rm -v "<INPUT>:/input" rnaseq_pipeline bash -lc 'ls -lh /input/refs/<species>/*.fa* /input/refs/<species>/*.gtf*'
```

Common mistakes:
- species のスペルミス（mouse/mice など）
- ref の配置先が `/input/refs/<species>/` 以外になっている
- transcripts と gtf を取り違える

## Reference presets

Presets fetch fixed reference bundles into a local cache. All URLs and checksums live in
`workflow/ref_manifest.yaml` (single source of truth). The public beta presets
are Ensembl bundles: human GRCh38/release 113, mouse GRCm39/release 113, mouse
GRCm38/release 102, and rat mRatBN7.2/release 113 (`dna.toplevel`).

Legacy IDs (`human_gencode`, `mouse_gencode`, `mouse_gencode_mm10`, and
`rat_ensembl`) remain readable and resolve to factual canonical Ensembl IDs.
Existing compatible legacy caches are reused in place without copying large
files. All four public-beta bundles have complete SHA256 sets. Built-in
acquisition and cache reuse require the manifest hashes to match.
See [Reference presets](docs/reference-presets.md) for the exact mapping and
migration policy.

Example: fetch a preset and point config at cached files:

```
python scripts/fetch_reference_preset.py --preset human_ensembl_grch38 --release pinned --cache-dir refs_cache --out-json refs.json
```

Then use the resolved paths in your config:

```
ref:
  transcripts_fasta: refs_cache/human_ensembl_grch38/release-113/transcripts.fa.gz
  genome_fasta: refs_cache/human_ensembl_grch38/release-113/genome.fa.gz
  gtf: refs_cache/human_ensembl_grch38/release-113/annotation.gtf.gz
```

Release notes:
- `pinned` resolves to `release-113` except for GRCm38/mm10, which resolves to
  `release-102`.
- Download target filenames are fixed: `genome.fa.gz`, `transcripts.fa.gz`, `annotation.gtf.gz`.

Decoy-aware Salmon (future step):
- When both genome and transcripts are available, the pipeline can build a gentrome
  (transcripts + genome) and a decoy list (genome contigs). These are required for
  decoy-aware Salmon indexing and improve quantification accuracy.
- Reference consistency: if you use vM38, make sure the genome is GRCm38 to match the
  transcriptome/GTF. Avoid mixing vM38 transcripts with vM39 (GRCm39) genome.

Salmon meta_info.json compatibility:
- Some Salmon versions write `meta_info.json` under `aux_info/` instead of the sample root.
- This pipeline copies `aux_info/meta_info.json` to `{sample}/meta_info.json` after quant
  when needed so downstream steps stay stable across versions.
  Observed on Windows + Docker bind mount: `/output/salmon/Con_1/aux_info/meta_info.json` exists
  while `/output/salmon/Con_1/meta_info.json` does not.

Tximport + Gencode bar headers:
- Gencode transcript FASTA headers can include `|` separators (e.g., `ENSMUST...|ENSMUSG...|...`).
- We use `ignoreAfterBar=TRUE` and keep transcript versions by default.
- If quant IDs lack version suffixes but `tx2gene` includes them (or vice versa), we strip versions on BOTH
  sides to keep them consistent.
- Tximport sets `ignoreTxVersion=FALSE` and relies on explicit normalization when needed.
- Quick check:
  `head -n 5 /output/salmon/<sample>/quant.sf | cut -f1`
 - Debugging:
   `TXIMPORT_DEBUG=1 python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores 4 -p --latency-wait 60 -- tximport`

Dry-run (DAG only) per species (refs must exist on disk):
```
python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=mouse -n
python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=human -n
python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat -n
```

## Output layout (stable)

- `out/fastp/{sample}.fastq` (single-end)
- `out/fastp/{sample}_R1.fastq` (paired)
- `out/fastp/{sample}_R2.fastq` (paired)
- `out/fastp/{sample}.json`
- `out/fastp/{sample}.html`
- `out/salmon/{sample}/quant.sf`
- `out/tximport/txi.tsv`
- `out/deseq2/results.tsv`
- `out/report/report.html`
- `out/report/report.html` includes Harako-RNAseq branding and an embedded logo so the HTML remains shareable as a standalone file.
- `out/results/enrichment/contrast=<A>_vs_<B>/status.json` (when enrichment is enabled)

## Notes

- Current tools are stubbed to keep smoke tests tiny and offline.
- Real runs use fastp, Salmon, tximport, and DESeq2 with a static HTML report.
- When enrichment is enabled, the report includes a Gene set enrichment section driven by `results/enrichment/**/status.json`.
- Quarto is recommended for richer reports; this repo currently emits a static HTML report (R Markdown).
