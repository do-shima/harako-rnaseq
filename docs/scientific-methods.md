# Scientific methods

Harako uses fastp for read preprocessing and Salmon for transcript-level
quantification. tximport summarizes transcript estimates to gene-level counts
for DESeq2 and produces gene-level TPM as an abundance measure. DESeq2 uses
counts, never TPM.

## Analysis eligibility

Policy version 1 permits inferential differential-expression analysis only
when the normalized sample table has at least two conditions and every
condition has at least two samples. Harako does not infer biological
independence from filenames or replicate suffixes.

Structurally valid designs below this gate use QC-only mode. Harako estimates
DESeq2 size factors under `~1` when technically possible, writes normalized
counts, and creates applicable PCA and sample-distance outputs. Inferential
contrasts are inactive: Harako does not run `DESeq()` for contrasts, call
`results()`, calculate or report p-values or adjusted p-values, create
differential-expression plots, or run enrichment.

The two-samples-per-condition requirement is a software minimum, not a power
calculation or evidence of biological independence or experimental-design
validity. The current default design is condition-based and does not
automatically model batch, pairing, repeated measures, or other covariates.

## Contrasts and enrichment

Reference, pairwise, selected, and compatible legacy contrast resolution apply
only in differential mode. Enrichment additionally requires available
inferential DE results. File presence alone does not establish eligibility.

Tool versions, reference provenance, and the frozen analysis plan are captured
with each new run.
