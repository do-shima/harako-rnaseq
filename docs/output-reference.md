# Output reference

## tximport outputs

- `tximport/txi.tsv`: stable gene-level original estimated-count matrix.
- `tximport/tpm.tsv`: stable gene-level TPM abundance matrix; never DESeq2
  input.
- `tximport/qc_library_sizes.tsv`: stable library-size QC table.
- `tximport/txi.rds`: internal complete tximport handoff containing `counts`,
  `abundance`, sample-specific effective `length`, and
  `countsFromAbundance`.

## DESeq2 outputs

- `deseq2/status.json`: analysis mode, policy decision, condition counts,
  library protocol, tximport handoff method, `counts_from_abundance`, whether
  a length offset was used, legacy state and warning when applicable, and
  actual artifact availability. Older status files without these additive
  fields remain readable.
- `deseq2/results.tsv`: standard DE result columns. In QC-only mode it contains
  the header and zero data rows.
- `deseq2/normalized_counts.tsv`: descriptive DESeq2-normalized gene counts
  when normalization is technically possible.
- `deseq2/pca.png`: descriptive PCA or an informative placeholder.
- `deseq2/sample_distance_heatmap.png`: sample distances or an informative
  placeholder.
- `deseq2/ma_plot.png`: inferential MA plot in differential mode; a clearly
  labeled not-applicable placeholder in QC-only mode.
- `deseq2/qc_summary.tsv` and `deseq2/qc_summary.json`: mode and availability
  summary.
- `deseq2/padj_hist.png`, `lfc_hist.png`, `mean_vs_lfc.png`, and `volcano.png`:
  inferential plots in differential mode and not-applicable placeholders in
  QC-only mode.

For full-length RNA-seq, original tximport counts and effective length reach
DESeq2 through `DESeqDataSetFromTximport`. For 3′-tag RNA-seq, rounded original
counts reach `DESeqDataSetFromMatrix` without length correction. Gene-level
TPM is descriptive and is never used as DESeq2 input.
