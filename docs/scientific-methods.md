# Scientific methods

Harako uses fastp for read preprocessing and Salmon for transcript-level
quantification. tximport summarizes transcript estimates to gene-level counts
for DESeq2 and produces gene-level TPM as an abundance measure. DESeq2 uses
counts, never TPM.

## Library protocol and tximport handoff

Every new run explicitly records `library_protocol` as `full_length` or
`three_prime_tag`. Harako does not infer this choice from filenames,
accessions, read length, library names, sequencing platform, or sample
metadata.

For full-length RNA-seq, tximport uses `countsFromAbundance="no"` and Harako
passes the complete tximport object to `DESeqDataSetFromTximport`. DESeq2 thus
models the original estimated counts with the tximport-derived,
sample-specific effective-length correction. Harako does not combine this
offset with `lengthScaledTPM`.

For 3′-tag RNA-seq, transcript length is not expected to drive fragment yield
in the same way. Harako therefore rounds the original `txi$counts` only when
constructing `DESeqDataSetFromMatrix` and does not add a length offset. TPM is
reported for abundance review but is not DESeq2 input in either protocol.

Frozen runs created before explicit protocol selection remain readable as
`legacy_unspecified`. If resumed, they preserve the historical rounded-count
matrix handoff without a length offset and show a scientific warning. A new
run with an explicit protocol is recommended for reanalysis.

This handoff follows the official Bioconductor
[tximport vignette](https://bioconductor.org/packages/release/bioc/vignettes/tximport/inst/doc/tximport.html#downstream-dge-in-bioconductor),
including its separate guidance for
[3′-tag RNA-seq](https://bioconductor.org/packages/release/bioc/vignettes/tximport/inst/doc/tximport.html#3%E2%80%99_tagged_RNA-seq),
and the
[DESeq2 vignette](https://bioconductor.org/packages/release/bioc/vignettes/DESeq2/inst/doc/DESeq2.html#transcript-abundance-files-and-tximport-tximeta).

## Analysis eligibility

Policy version 1 permits differential expression analysis only
when the normalized sample table has at least two conditions and every
condition has at least two samples. Harako does not infer biological
independence from filenames or replicate suffixes.

Inputs that pass structural validation but do not meet the minimum sample-count
requirements use QC-only mode. Harako estimates
DESeq2 size factors under `~1` when technically possible, writes normalized
counts, and creates applicable PCA and sample-distance outputs. Inferential
contrasts are inactive: Harako does not run `DESeq()` for contrasts, call
`results()`, calculate or report p-values or adjusted p-values, create
differential expression plots, or run enrichment.

The two-samples-per-condition requirement is the minimum threshold enforced by
the software, not a power calculation or evidence of biological independence
or experimental-design validity. The current default design is condition-based
and does not model batch, pairing, repeated measures, covariates, or
interactions.

## Contrasts and enrichment

Reference, pairwise, selected, and compatible legacy contrast resolution apply
only in differential mode. Enrichment additionally requires available
inferential DE results. File presence alone does not establish eligibility.

Tool versions, reference provenance, and the frozen analysis plan are captured
with each new run.
