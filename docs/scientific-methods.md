# Scientific methods

Harako uses fastp for read preprocessing and Salmon for transcript-level
quantification. tximport summarizes transcript estimates to gene-level counts
for DESeq2 and produces gene-level TPM as a descriptive abundance output.
DESeq2 does not use TPM as input.

## Analysis eligibility

Policy version 1 permits inferential differential-expression analysis only
when the normalized sample table has at least two conditions and every
condition has at least two samples. Harako does not infer biological
independence from filenames or replicate suffixes.

Structurally valid designs below this gate use QC-only mode. Harako estimates
DESeq2 size factors under `~1` when technically possible, writes descriptive
normalized counts, and creates applicable PCA and sample-distance outputs.
It does not run `DESeq()` for contrasts, call `results()`, create inferential
fold changes or p-values, or run enrichment.

The two-sample minimum is a software gate, not a power calculation or evidence
of adequate replication. The current default design is condition-based and
does not automatically model batch, pairing, repeated measures, or other
covariates.

## Contrasts and enrichment

Reference, pairwise, selected, and compatible legacy contrast resolution apply
only in differential mode. Enrichment additionally requires available
inferential DE results. File presence alone does not establish eligibility.

Tool versions, reference provenance, and the frozen analysis plan are captured
with each new run.
