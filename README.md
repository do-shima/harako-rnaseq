# rnaseq_pipeline

Minimal, Docker-ready RNA-seq pipeline skeleton powered by Snakemake. This repo provides a single entrypoint
(`python -m app run ...`) and a tiny smoke test that runs end-to-end without network downloads.

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

## Advanced usage

Windows-friendly one-liners are in [PowerShell snippets](#powershell-safe-command-snippets).

GUI (optional, preview):

```
docker run --rm -p 127.0.0.1:8501:8501 -v "${PWD}:/app" -v /path/to/input:/input:ro -v /path/to/output:/output rnaseq_pipeline bash -lc 'cd /app && streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501'
```

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
```

Common run flags (pass via `ARGS`):

```
ARGS="--dry-run --printshellcmds --reason" just run INPUT=... OUTPUT=... CONFIG=...
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

- **PowerShell:** `ENABLE_ENRICHMENT=1 just smoke` does nothing → use `$env:ENABLE_ENRICHMENT="1"; just smoke`.
- **PowerShell:** host python missing / `exit 9009` → self-contained check runs in Docker; use `just check-report-selfcontained ...`.
- **REPORT= mixing:** `REPORT=out_smoke/report/report.html` is treated as a positional arg → prefer `just check-report-selfcontained out_smoke/report/report.html` (REPORT= also accepted).
- **Validate vs init mismatch:** `just validate CONFIG=...` can't see Windows paths → use `INPUT=... OUT=... just validate-out`.
- **PowerShell just args:** `just init INPUT=...` / `just run INPUT=...` are parsed as recipes → set `$env:INPUT`/`$env:OUT`/`$env:CONFIG` and run `just init`/`just run`.
- **Snakemake targets:** put targets after `--` → `python -m snakemake ... -- report`.
- **PowerShell Git:** `@{u}` needs quotes → `git rev-parse '@{u}'`.
- **Stale metadata / logs:** output exists but Snakemake complains → `rm -rf out/.snakemake` and check `/output/.snakemake/log`, `/output/logs/*`.
- **CRLF/LF noise:** set `git config --global core.autocrlf true` (repo enforces LF).
- **Bad FASTQ paths:** `/app/...` in samples.tsv → use `/input`-relative paths.
- **Docker Desktop:** drive not shared → enable sharing for the drive (e.g., D:).

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
- `out/run/command.txt`, `config_resolved.yaml`, `versions.tsv`, `git_rev.txt`
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
- `ref_preset`: optional `human|mouse|rat` to resolve via `workflow/refs_manifest.tsv`
- `ref_manifest`: optional path to a pinned ref manifest file
- `tx2gene_tsv`: optional transcript-to-gene table for tximport
- `contrasts`: optional list of `A_vs_B` strings
- `threads`: optional integer
- `enrichment`: optional settings (enable/methods/alpha/lfc/top_terms/rank_metric)

See `config/schema.md` for the canonical config reference.

Species-specific refs (rat example):

```
species: rat
ref:
  rat:
    transcripts_fasta: refs/rat/Rattus_norvegicus.GRCr8.cdna.all.fa.gz
    genome_fasta: refs/rat/Rattus_norvegicus.GRCr8.dna.toplevel.fa.gz
    gtf: refs/rat/Rattus_norvegicus.GRCr8.115.gtf.gz
```

Flat refs (no species nesting) still work and keep current mouse/human behavior.

Rat quickstart (PowerShell, copy/paste safe):
```
$env:INPUT="D:\data\input"; $env:OUT="D:\data\output"; $env:THREADS="4"
just init
just fetch-refs-rat
just check-refs-rat
just rat-config
just dry-run-rat
just all-rat-nobuild
```

Note: the DNA toplevel file is large and may time out on the first try; re-running `just fetch-refs-rat` will resume.

If refs are missing, you'll see an error like:
`[refs] species=rat missing_ref_key=transcripts_fasta tried=ref.transcripts_fasta,ref.rat.transcripts_fasta configfiles=[/output/config.yaml]`

Where to put refs (recommended):
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

Annotation note:
- GENCODE は主に human/mouse 向け。rat は Ensembl を使う前提。

## Reference presets (scaffolding)

Presets are an optional convenience to fetch pinned or "latest" reference bundles into a local cache. All URLs
and checksums live in `workflow/ref_manifest.yaml` (single source of truth). This does not run during smoke.

Example: fetch a preset and point config at cached files:

```
python scripts/fetch_reference_preset.py --preset human_gencode --release pinned --cache-dir refs_cache --out-json refs.json
```

Then use the resolved paths in your config:

```
ref:
  transcripts_fasta: refs_cache/human_gencode/pinned/transcripts.fa.gz
  genome_fasta: refs_cache/human_gencode/pinned/genome.fa.gz
  gtf: refs_cache/human_gencode/pinned/annotation.gtf.gz
```

Pinned vs latest:
- `pinned` is a fixed, reproducible release with optional checksums.
- `latest` is intended for moving targets (still captured in the manifest).

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

- `out/fastp/{sample}.fastq`
- `out/fastp/{sample}.json`
- `out/fastp/{sample}.html`
- `out/salmon/{sample}/quant.sf`
- `out/tximport/txi.tsv`
- `out/deseq2/results.tsv`
- `out/report/report.html`
- `out/results/enrichment/contrast=<A>_vs_<B>/status.json` (when enrichment is enabled)

## Notes

- Current tools are stubbed to keep smoke tests tiny and offline.
- Real runs use fastp, Salmon, tximport, and DESeq2 with a static HTML report.
- When enrichment is enabled, the report includes a Gene set enrichment section driven by `results/enrichment/**/status.json`.
- Quarto is recommended for richer reports; this repo currently emits a static HTML report (R Markdown).
