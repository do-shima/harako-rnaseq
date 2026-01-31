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
