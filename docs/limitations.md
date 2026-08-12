# Limitations

- Two conditions with two valid samples each is only the software minimum for
  differential-expression analysis. Small designs can still produce unstable
  estimates.
- Users must establish biological independence and assess statistical power.
- The current model does not automatically account for batch, pairing,
  repeated measures, or other covariates.
- QC-only normalized counts and gene-level TPM abundance measures are not
  substitutes for inferential differential-expression results.
- Degenerate count matrices can make DESeq2 median-ratio normalization
  technically impossible; Harako fails explicitly in that case.
- Reference checksums identify content but do not guarantee that an assembly
  or annotation is biologically appropriate for a study.
