# Output reference

## DESeq2 outputs

- `deseq2/status.json`: analysis mode, policy decision, condition counts, and
  actual artifact availability.
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

Gene-level tximport counts are the DESeq2 input. Gene-level TPM is descriptive
and is never used as DESeq2 input.
