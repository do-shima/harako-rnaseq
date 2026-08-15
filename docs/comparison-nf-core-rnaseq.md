# Harako-RNAseq and nf-core/rnaseq

Harako-RNAseq is not intended to replace nf-core/rnaseq.

**Comparison date:** 2026-08-15

**nf-core/rnaseq version reviewed:** 3.26.0

This comparison is about scope and operating model, not performance or
scientific ranking. It uses Harako's current source and the official
[nf-core/rnaseq introduction](https://nf-co.re/rnaseq/3.26.0/),
[parameters](https://nf-co.re/rnaseq/3.26.0/parameters), and
[output reference](https://nf-co.re/rnaseq/3.26.0/docs/output/). Public-data
acquisition is compared with the official
[nf-core/fetchngs documentation](https://nf-co.re/fetchngs/1.12.0/). Pipeline
licensing and project history are linked from the official
[nf-core/rnaseq repository](https://github.com/nf-core/rnaseq).

## Compact comparison

| Area | Harako-RNAseq | nf-core/rnaseq 3.26.0 |
|---|---|---|
| Intended user | Researchers and analysts who want a guarded, bilingual, local GUI for a constrained bulk RNA-seq workflow | Bioinformatics users and facilities that need a broad, configurable community pipeline |
| Interface | English/Japanese Streamlit GUI plus CLI and approval-gated agent plan | Nextflow CLI, parameter files, launch tooling, and institutional profiles; no equivalent Harako analysis GUI |
| Compute setting | Single local workstation through one Docker image; Windows Docker Desktop and Ubuntu/Linux are the qualified targets | Laptop/local execution plus HPC schedulers and cloud executors through Nextflow and nf-core configuration profiles |
| Quantification routes | Salmon-only transcript quantification followed by tximport | STAR–Salmon, STAR–RSEM, HISAT2, Bowtie2–Salmon, and optional pseudoalignment routes including Salmon |
| BAM and bigWig | Not produced | Alignment routes can produce BAM and bigWig outputs, with options to retain intermediates |
| QC breadth | fastp, Salmon summaries, normalized-count PCA/sample distance, guarded mode reporting | Broad read-, alignment-, biotype-, duplication-, complexity-, strandedness-, and contamination-oriented QC collected in MultiQC |
| SRA/ENA acquisition | A small explicit Harako acquisition path followed by user review of sample and condition assignments | SRA/ENA/DDBJ/GEO acquisition and rnaseq samplesheet generation are handled by the separate nf-core/fetchngs pipeline |
| Built-in statistical group comparison | Integrated simple `~ condition` DESeq2 comparison when the minimum gate passes; otherwise descriptive QC-only | Produces expression matrices and QC but explicitly does not assign statistical significance with FDR or p-values |
| Complex designs | Batch, pairing, repeated measures, covariates, and interactions are unsupported by the built-in model | Not part of nf-core/rnaseq itself; downstream statistical work can use R or nf-core/differentialabundance |
| Run provenance | Frozen run-local configuration, sample table, analysis plan, reference provenance, versions, manifest, logs, status, and self-contained report | Nextflow execution records, pipeline information, reports, software versions, parameters, and community-standard provenance outputs |
| Community maturity | Small public-beta project with deliberately narrow qualification | Long-running, widely used nf-core community pipeline with many contributors, modules, releases, and institutional profiles |
| License | Source-available PolyForm Noncommercial 1.0.0; academic and permitted noncommercial use | MIT-licensed pipeline code; users must still review licenses of tools and reference resources |

## Where nf-core/rnaseq is broader

The official nf-core/rnaseq workflow includes multiple alignment and
quantification paths, and Salmon is one of them. Salmon itself is therefore
not a differentiator for Harako. nf-core/rnaseq can perform genomic alignment,
retain or re-use BAM files, create bigWig coverage, extract and deduplicate
UMIs, remove ribosomal RNA, screen contamination, assemble transcripts, and
collect extensive results in MultiQC. Its official workflow lists STAR,
RSEM, HISAT2, Salmon, alignment post-processing, RSeQC, Qualimap, dupRadar,
Preseq, Kraken2/Bracken or Sylph, and other components.

Nextflow also makes nf-core/rnaseq a better fit for shared compute. Official
[nf-core system configuration guidance](https://nf-co.re/docs/running/configuration/nextflow-for-your-system)
covers local machines, schedulers such as Slurm, SGE, LSF, and PBS, and cloud
executors such as AWS Batch. Harako's one-container, single-workstation model
is intentionally much smaller. It does not offer a cluster scheduler layer,
cloud execution abstraction, alignment-centric diagnostics, BAM/bigWig, UMI
handling, or contamination workflows.

For those needs, nf-core/rnaseq is normally the preferable starting point. Its
community, release history, module ecosystem, test profiles, institutional
configurations, and support channels are also substantially more mature than
Harako's public beta.

## Statistical analysis is a different boundary

nf-core/rnaseq uses DESeq2-derived information for aspects of QC, but its
official introduction states that the pipeline does not statistically compare
samples to assign FDR or p-values. It produces quantification and QC outputs
for downstream analysis. Users can work in R or another statistical
environment, or use the separate
[nf-core/differentialabundance pipeline](https://nf-co.re/differentialabundance/latest/).
Accordingly, saying that nf-core/rnaseq lacks Harako's integrated inferential
DESeq2 step is not a claim that the nf-core ecosystem lacks differential
analysis.

Harako integrates only a narrow group comparison. It validates an explicit
sample-to-condition table and runs `~ condition` when there are at least two
conditions and at least two samples per condition. Otherwise it enters
QC-only mode and does not produce inferential contrasts, p-values, adjusted
p-values, differential plots, or enrichment. The threshold is a software gate,
not evidence of biological independence, design validity, or adequate power.
Harako does not support batch terms, pairing, repeated measures, covariates, or
interactions in its built-in model.

Harako also requires an explicit full-length or 3′-tag protocol choice. For
full-length data it uses original tximport estimated counts with the
sample-specific effective-length correction through
`DESeqDataSetFromTximport`; for 3′-tag data it uses original counts without
that correction. TPM is not DESeq2 input. This is a precise boundary for the
small supported model, not a claim that Harako is scientifically stricter than
nf-core workflows.

## Public accessions and sample meaning

Current nf-core/rnaseq documentation says its former SRA download function was
moved to nf-core/fetchngs. fetchngs resolves supported public accessions,
retrieves metadata and FASTQ files, verifies downloads where supported, and
can prepare an rnaseq-compatible samplesheet. This is the broader nf-core
route for SRA, ENA, DDBJ, and GEO acquisition.

Harako offers a smaller acquisition workflow, but it deliberately separates
file acquisition from biological interpretation. It does not infer conditions,
controls, or biological independence from accession metadata. Users must
review FASTQ pairing and explicitly assign conditions before execution. The
same caution remains necessary with any automatically generated samplesheet:
technical runs are not automatically biological replicates.

## Harako's intended value

Harako's value is the constrained end-to-end interaction: a bilingual GUI,
visible FASTQ and pairing review, explicit condition and library-protocol
selection, pinned reference choices, a guarded DESeq2-or-QC-only decision,
fixed run records, a self-contained report, and exact approval-hash execution
for controlled local automation. It aims to help a user operate one supported
path on a workstation and understand why inferential outputs are or are not
applicable.

That narrower experience can be useful when it matches the study and local
operating environment. It should not be generalized into claims that Harako
is faster, more accurate, more reproducible, or a replacement for
nf-core/rnaseq. When a project needs broader QC, multiple quantifiers,
alignment artifacts, complex infrastructure, or a mature community workflow,
nf-core/rnaseq is the more appropriate tool; statistical design and downstream
inference must then be planned with the corresponding downstream workflow or
analysis environment.
