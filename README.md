# rnaseq_pipeline

Minimal, Docker-ready RNA-seq pipeline skeleton powered by Snakemake. This repo provides a single entrypoint
(`python -m app run ...`) and a tiny smoke test that runs end-to-end without network downloads.

## Quickstart

Build image:

```
just build
```

Interactive setup (no downloads):

```
just init
```

Docker note: when using `input=/input` in Snakemake, you can store relative FASTQ paths in `samples.tsv`
and they will resolve under `/input`. Avoid `/app`-prefixed paths.

Validate a config:

```
just validate CONFIG=path/to/config.yaml
```

Run smoke test (no downloads):

```
just smoke
```

Run on your data (real pipeline):

```
just run INPUT=path/to/input OUTPUT=out CONFIG=path/to/config.yaml ALIGN=none
```

Override engine/threads (optional):

```
ENGINE=real THREADS=4 just run INPUT=path/to/input OUTPUT=out CONFIG=path/to/config.yaml ALIGN=none
```

Common run flags (pass via `ARGS`):

```
ARGS="--dry-run --printshellcmds --reason" just run INPUT=... OUTPUT=... CONFIG=...
```

Portable dry-run (avoid version-sensitive flags):

```
ARGS="--dry-run --printshellcmds" just run INPUT=... OUTPUT=... CONFIG=...
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

Direct Snakemake dry-run (regression check):

```

Run artifacts (real runs):
- `out/run/command.txt`, `config_resolved.yaml`, `versions.tsv`, `git_rev.txt`
- The HTML report links to these files.

Docker Desktop resources (real runs):
- CPU: 4+ cores recommended
- RAM: 8–16 GB recommended for medium datasets

Init regression check (relative FASTQ paths):

```
python -m app init --out config.yaml
# enter FASTQ as Con_1_1.fq.gz (relative)
# samples.tsv should contain Con_1_1.fq.gz (no /app prefix)
```
docker run --rm -v "$PWD:/app" -v /path/to/input:/input -v /path/to/output:/output rnaseq_pipeline \
  bash -lc "cd /app && python -m snakemake -s workflow/Snakefile --configfile /app/config.yaml --config input=/input output=/output -n"
```

## Config

Example config (see `tests/config.yaml` for stub, `examples/config_real.yaml` for real):

- `engine`: `stub` or `real` (default real for user runs)
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

See `config/schema.md` for the canonical config reference.

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

## Output layout (stable)

- `out/fastp/{sample}.fastq`
- `out/fastp/{sample}.json`
- `out/fastp/{sample}.html`
- `out/salmon/{sample}/quant.sf`
- `out/tximport/txi.tsv`
- `out/deseq2/results.tsv`
- `out/report/report.html`

## Notes

- Current tools are stubbed to keep smoke tests tiny and offline.
- Real runs use fastp, Salmon, tximport, and DESeq2 with a static HTML report.
- Quarto is recommended for richer reports; this repo currently emits a static HTML report (R Markdown).
