# rnaseq_pipeline

Minimal, Docker-ready RNA-seq pipeline skeleton powered by Snakemake. This repo provides a single entrypoint
(`python -m app run ...`) and a tiny smoke test that runs end-to-end without network downloads.

## Quickstart

Build image:

```
just build
```

Run smoke test (no downloads):

```
just smoke
```

Run on your data:

```
just run INPUT=path/to/input OUTPUT=out CONFIG=path/to/config.yaml ALIGN=none
```

## Config

Example config (see `tests/config.yaml`):

- `samples`: list of sample IDs
- `fastq`: map of sample -> fastq path (relative to `--input` or absolute)
- `ref`: transcripts/genome/gtf paths (relative to `--input` or absolute)
- `ref_preset`: optional `human|mouse|rat` to resolve via `workflow/refs_manifest.tsv`
- `ref_manifest`: optional path to a pinned ref manifest file

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
- Quarto is recommended for richer reports; this repo currently emits a static HTML stub.
