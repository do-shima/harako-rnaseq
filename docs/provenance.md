# ikra Provenance Audit

## Status

This engineering provenance audit classifies Harako-RNAseq as an independently
implemented project inspired by ikra's high-level concept. No copied or adapted
ikra source code, copyrightable documentation, test data, or assets were
detected in Harako-RNAseq.

The audit is not a legal opinion. Automated similarity analysis cannot prove a
negative, and the conclusions are limited to the repositories and revisions
described below.

## Name origin and adopted interpretation

The project name predates its English expansion. *Harako* is the Japanese term
associated with salmon roe, and the name also acknowledges ikra, the
Salmon-centered RNA-seq pipeline that provided conceptual inspiration.

HARAKO is now also interpreted as the backronym **Human-Auditable, Reproducible
Analysis Kit and Orchestrator**. This is an adopted explanation of the current
design philosophy, not the original chronological naming process:

- Human-Auditable refers to explicit sample and condition review, reviewable
  plans, exact execution approval, and inspectable provenance and artifacts.
- Reproducible refers to the Docker environment, frozen Run configuration,
  captured versions and provenance, and checksum-pinned references.
- Analysis Kit refers to the integrated GUI, CLI, Snakemake workflow, reports,
  and supporting tools for bulk RNA-seq.
- Orchestrator refers to validation, dry-run, controlled workflow execution,
  status and artifact inspection, and optional agent orchestration without
  transferring scientific authority.

“Human-Auditable” describes what a person can inspect; it does not mean that
Harako-RNAseq automatically audits or certifies scientific validity. The ikra
relationship remains one of inspiration and acknowledgement. Harako-RNAseq is
independently implemented and is not an official successor to, affiliated
with, or endorsed by the ikra project.

## Compared Source

- Repository: https://github.com/yyoshiaki/ikra
- Current default branch at audit time: `master`
- Current default-branch revision:
  `c242855e88bfc4fc781c82ee4c6c20249cd18bf1`
- Compared release: `v2.0.1`
- Release commit: `557f0bfd2c699ebe886525d4a394e04e5f106248`
- License file: repository-root `LICENSE`, Creative Commons
  Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)
- License SHA256 at both compared revisions:
  `43a372304b1da21ff143b9dd10424d93dc193073aecd5984a6b3872416dc7acd`
- Release citation: Hiraoka Yu et al. *yyoshiaki/ikra: ikra v2.0.1*.
  Zenodo. https://doi.org/10.5281/zenodo.5541399

The comparison checkout and detached release worktree were created under the
system temporary directory, outside the Harako-RNAseq working tree. No ikra
file was copied into Harako-RNAseq and ikra was not modified.

The default branch differs from `v2.0.1` only in `README.md`, `README_ja.md`,
and `ikra.sh`. The `ikra.sh` changes are small option and COWSAY fixes. Both
revisions were covered by the repository-history comparison.

## Scope

The audit covered:

- shell, Python, R, Snakemake, and CWL workflow source;
- Docker and tool-installation logic;
- reference acquisition and validation;
- SRA/ENA acquisition;
- Salmon indexing and quantification;
- tximport and gene-level summarization;
- sample-table parsing and alignment options;
- differential expression, enrichment, and report generation;
- README and usage text, tables, examples, and configuration;
- diagrams, screenshots, logos, images, adapters, and test fixtures; and
- current Harako content plus all reachable Harako Git commits.

Generated local inputs, outputs, caches, and Snakemake state were excluded
because they are not repository source material.

## AI-assisted development provenance

OpenAI Codex was used as a development-assistance tool for:

- code generation and modification proposals;
- refactoring;
- unit-test and regression-test generation;
- documentation drafting; and
- debugging and code-review suggestions.

The human maintainer retained responsibility for:

- requirements and scientific scope;
- architecture selection;
- acceptance or rejection of generated changes;
- manual and automated validation;
- licensing; and
- release and publication decisions.

AI-generated output was not accepted automatically. Its use does not establish
authorship, copyright ownership, scientific validation, or endorsement by
OpenAI.

This section is a transparency statement about the development process. It
does not alter the PolyForm Noncommercial License 1.0.0 applied to
Harako-RNAseq source code or the licenses of third-party software.

## Methods

1. Inventoried relevant files in both ikra revisions and the Harako tree.
2. Compared SHA256 file hashes across the current trees.
3. Compared normalized files after removing whitespace and comment-only lines.
4. Searched for exact multiline blocks of at least two lines and 80 characters.
5. Searched for exact normalized sequences of 12 lexical tokens.
6. Used Python `difflib.SequenceMatcher` for whole-file and block-level
   similarity screening.
7. Manually reviewed corresponding implementation areas and all automated
   flags.
8. Compared image hashes, dimensions, and the visible logo designs.
9. Searched Harako commit messages and patches for ikra names, copied
   filenames, distinctive variables, and import/copy/port/rewrite language.
10. Compared blob identities across all 125 reachable Harako commits and all
    382 reachable commits in the retrieved ikra repository.
11. Repeated normalized-file and 12-token checks across historical text blobs
    up to 2 MB.

## Automated Results

- Non-empty exact current-tree file matches: 0.
- Normalized exact current-tree matches of at least 80 characters: 0.
- Exact multiline current-tree blocks meeting the threshold: 0.
- Exact current-tree 12-token sequence matches: 0.
- Substantial `difflib` blocks: 0.
- Exact historical Git blob matches: 0 non-empty blobs. The only shared blob
  was Git's universal empty-file object.
- Historical normalized exact matches of at least 80 characters: 0.
- Historical 12-token sequence matches: 0.
- Distinctive ikra strings or original ikra function/variable names found in
  Harako history: 0.

The only overlapping historical basenames were `.gitignore`, `README.md`, and
`quant.sf`. These names are generic repository, documentation, and Salmon
output names and are not evidence of copying.

## File-by-File Findings

| Harako-RNAseq files | Compared ikra files | Finding | Classification |
| --- | --- | --- | --- |
| `workflow/Snakefile` | `ikra.sh`, `basicrnaseq_se.cwl`, `cwl_tools/*.cwl` | Harako defines a resumable Snakemake DAG with stable run outputs. ikra uses a monolithic shell script plus experimental CWL tools. Shared tool names and standard command options are functional necessities; no matching block was found. | Independently reimplemented equivalent functionality; common implementation pattern |
| `workflow/scripts/build_gentrome.py`, `workflow/scripts/salmon_index_stub.py`, `workflow/scripts/salmon_quant_stub.py` | Salmon sections of `ikra.sh`, `cwl_tools/salmon-index.cwl`, `cwl_tools/salmon-quant.cwl` | Harako implements decoy-aware gentrome construction, test stubs, and a transcripts-only fallback. ikra builds a transcripts-only index and has no corresponding Python implementation or stubs. | Independently reimplemented equivalent functionality |
| `scripts/tximport_real.R`, `scripts/tximport_stub.py` | `tximport_R.R`, embedded tximport block in `ikra.sh`, `quantmerge_gene.R` | Both necessarily call the public tximport API. ikra derives paths from a CSV and writes `countsFromAbundance="scaledTPM"` output. Harako consumes Snakemake inputs, builds transcript-to-gene mappings from GTF or TSV, normalizes identifiers, and emits counts, TPM, and QC separately. No matching token sequence or block was found. | Common/non-distinctive API use; independently implemented |
| `scripts/srr_fetch.py` | SRA sections of `ikra.sh`, `ikra_Ion_SRR.sh` | ikra invokes local `fasterq-dump`/`fastq-dump`. Harako parses several input-table forms and downloads from ENA over HTTP with retry, resume, size, and MD5 checks. No shared implementation was found. | Independently reimplemented equivalent functionality |
| `scripts/fetch_reference_preset.py`, `scripts/fetch_refs_ensembl.sh`, `workflow/ref_manifest.yaml`, `workflow/refs_manifest.tsv` | GENCODE and genome download sections of `ikra.sh` | ikra constructs GENCODE URLs and invokes `wget` in shell. Harako resolves a pinned manifest, supports Ensembl presets and user files, validates downloads, and manages a cache. URLs, data model, and code structure are distinct. | Independently reimplemented equivalent functionality |
| `scripts/install_tools.sh`, `Dockerfile`, `compose.yaml` | Docker command construction and image variables in `ikra.sh` | ikra pulls and runs separate third-party tool images and has no Dockerfile. Harako builds one image and installs pinned tools. Generic Docker and package names are non-distinctive. | Common/non-distinctive implementation pattern |
| `app/*.py`, `app/ui/*.py`, `app/ui/locales/*.json` | `ikra.sh` usage/options and README usage text | ikra has no Python application or GUI. Harako's CLI, Streamlit UI, localization, session isolation, frozen configuration, validation, and recovery code have no ikra counterpart. The shared concepts of species, threads, and optional alignment are generic pipeline controls. | Independently implemented; conceptual inspiration only |
| `scripts/deseq2_real.R`, `scripts/deseq2_qc_real.R`, `scripts/enrichment_run.R` and stubs | No corresponding ikra files | ikra produces a gene expression table but does not implement Harako's DESeq2, QC, contrast, or enrichment workflows. | Harako-original scope; no counterpart |
| `scripts/report_real.Rmd`, `scripts/report_stub.py`, `scripts/check_report_selfcontained.py` | MultiQC invocations in `ikra.sh`, README screenshots | ikra invokes MultiQC and documents its output. Harako renders a branded self-contained report from its own workflow artifacts. No copied report markup, prose, or image was found. | Independently implemented; common reporting concept |
| `README.md`, `README.ja.md`, `config/schema.md`, `docs/*.md`, CLI/UI help text | `README.md`, `README_ja.md`, `ikra.sh` usage text | No exact multiline or 12-token match was found before adding the acknowledgement. Instructions, tables, examples, output contracts, and troubleshooting content are distinct. | Independently authored documentation |
| `icon/Harako-logo.png`, `icon/Harako-logo.jpg`, `icon/Harako-logo-report.jpg` | `img/*` | File hashes and dimensions differ. Manual visual review shows a distinct Harako salmon/DNA workflow mark rather than ikra's embryo/roe character, pipeline diagram, or screenshots. | Independently created assets |
| `tests/**`, example configs, and small fixtures | `test/**`, `adapters/**`, example CSV files | No non-empty exact file, normalized match, or 12-token match was found. Both use generic RNA-seq fields and Salmon `quant.sf` conventions, but values and fixture structures differ. Harako does not include ikra adapter files. | Independently created test material; common data conventions |
| Harako shell and PowerShell launch scripts | `ikra.sh`, `test/*.sh` | No matching block or distinctive ikra variable/function name was found. Harako's launchers implement its single-image, cross-platform mount and run-directory model. | Independently implemented |

## Manual Review of Similarities

No automated block met the manual-review threshold. The following conceptual
similarities were nevertheless reviewed because they are central to both
projects:

- Salmon index and quantification commands use standard Salmon executable names
  and documented flags.
- Both accept single-end and paired-end data and expose thread counts.
- Both can obtain public accession data and use a sample/experiment table.
- Both summarize Salmon transcript estimates at gene level with tximport.
- Both discuss human/mouse references and an optional alignment mode.
- Both use Docker to reduce local dependency setup.

These similarities describe the problem domain and public tool interfaces.
Their expression, control flow, data models, output contracts, and surrounding
implementation are different.

## Git History Findings

Harako history contains no commit mentioning `ikra` or `ikra.sh`. Broader
commit-message searches for imports, copies, ports, translations, rewrites, and
adaptations produced only unrelated uses of those words.

Patch-history searches found none of these distinctive ikra identifiers:
`EX_MATRIX_FILE`, `IF_REMOVE_INTERMEDIATES`, `TX2SYMBOL`, `M_GEN_VER`,
`H_GEN_VER`, `salmon_output_`, `designtable.csv`, or the phrase
`RNAseq pipeline centered on Salmon`.

Historical exact-object comparison covered every reachable tree entry,
including large blobs, without reading their contents. Historical fuzzy
analysis was limited to relevant text-like files no larger than 2 MB. The
Harako object database contains tens of gigabytes of loose historical data, so
fuzzy comparison of every large historical blob was not practical. Large
binary scientific outputs are also poor candidates for source-code similarity
analysis.

## Classification and Decision

Relevant findings fall into these categories:

1. conceptual inspiration only;
2. common or non-distinctive implementation patterns; and
3. independently reimplemented equivalent functionality.

No finding was classified as copied/adapted copyrightable material or as
ambiguous. Under the decision criteria supplied for this audit, the provenance
result is **Case A: independent implementation confirmed**.

The audit supports acknowledging ikra as conceptual inspiration. It does not
assert that acknowledgement would cure incorporation of CC BY-NC 4.0 material;
the conclusion instead rests on finding no such incorporated material.

## Conclusion

- Independent implementation was confirmed by this engineering audit.
- No ikra code, documentation, test data, or assets were found incorporated in
  Harako-RNAseq.
- Harako-RNAseq's PolyForm Noncommercial License 1.0.0 was selected
  independently from ikra's CC BY-NC 4.0 license.
- This audit is not a legal opinion.
- Automated fuzzy historical analysis was limited by repository size, while
  exact reachable-tree comparison was complete.

## Harako-RNAseq License

Harako-RNAseq source code is source-available under the PolyForm Noncommercial
License 1.0.0, SPDX identifier `PolyForm-Noncommercial-1.0.0`. The selected
license does not apply to ikra or relicense third-party components used by or
distributed with Harako-RNAseq.
