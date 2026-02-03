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
- `threads`: integer number of threads for fastp/salmon
- `output`: optional output directory (used if `--output` not provided)
- `ref_preset`: optional preset name (legacy TSV manifest)
- `ref_manifest`: optional TSV manifest path
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
