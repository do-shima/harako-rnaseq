# Configuration schema

This schema describes the supported configuration keys for `python -m app run`.

Required keys:
- `engine`: `real` or `stub` (smoke uses `stub`; real uses external tools)
- `samples`: list of sample IDs
- `fastq`: map of sample -> FASTQ path (SE) OR
- `fastq1` and `fastq2`: maps of sample -> FASTQ path (PE)
- `ref`: reference paths (relative to `--input` or absolute)
  - `transcripts_fasta` (required for Salmon)
  - `genome_fasta` (optional, enables decoy-aware index)
  - `gtf` (optional, used by tximport if `tx2gene_tsv` is not provided)

Optional keys:
- `conditions`: map of sample -> condition (used when `sample_table` not provided)
- `sample_table`: TSV path with columns `sample`, `condition`, `fastq1`, `fastq2` (optional)
- `tx2gene_tsv`: TSV path with columns `TXNAME` and `GENEID`
- `contrasts`: list of `A_vs_B` strings (defaults to all pairwise contrasts)
- `contrast_mode`: `ref|pairwise|select|legacy` (default: legacy if contrasts set, else ref)
- `contrast_ref`: reference condition for mode=ref
- `contrast_pairs`: list of `[A, B]` for mode=select
- `threads`: integer number of threads for fastp/salmon
- `output`: optional output directory (used if `--output` not provided)
- `ref_preset`: optional canonical preset ID from `workflow/ref_manifest.yaml`;
  legacy aliases remain readable and are migrated explicitly
- `ref_release`: `pinned` or a compatible manifest release
- `ref_manifest`: optional YAML manifest path
- `ref_cache_dir`: cache root; canonical directories are preferred and compatible
  legacy alias directories are reused in place
- `reference_provenance`: resolved provider/species/assembly/releases, paths,
  exact checksums, verification status, and cache source written to new
  saved/frozen configs. Built-in schema-v2 presets require complete manifest
  SHA256 values; custom references do not.
- `enrichment`: optional enrichment settings
  - `enable`: bool (default false)
  - `methods`: list of `ORA`/`GSEA` (default both)
  - `alpha`: float (default 0.05)
  - `lfc`: float (default 0)
  - `top_terms`: int (default 15)
  - `rank_metric`: string (default `stat`)

Notes:
- Paths can be absolute or relative to `--input`.
- For `engine: real`, real tools are used; for `engine: stub`, repo-local stubs keep smoke fast/offline.
