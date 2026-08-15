# Limitations

- Having at least two conditions with two valid samples each is only the
  minimum enforced by the software for differential expression analysis.
  Small designs can still produce unstable estimates.
- Users must establish biological independence and assess statistical power.
- The built-in model does not support batch, pairing, repeated measures,
  covariates, or interactions.
- Users must explicitly identify full-length versus 3′-tag RNA-seq. Harako
  does not infer the protocol, and selecting the wrong protocol can apply or
  omit an inappropriate effective-length correction.
- Runs created before explicit protocol selection retain their historical
  uncorrected matrix handoff and should be recreated for protocol-aware
  reanalysis when appropriate.
- QC-only normalized counts and gene-level TPM abundance measures are not
  substitutes for inferential differential expression results.
- Degenerate count matrices can make DESeq2 median-ratio normalization
  technically impossible; Harako fails explicitly in that case.
- Reference checksums identify content but do not guarantee that an assembly
  or annotation is biologically appropriate for a study.
