suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(tximport)
})

quant_files <- snakemake@input[["quant"]]
if (is.null(quant_files)) {
  quant_files <- snakemake@input
}
samples <- snakemake@params[["samples"]]
names(quant_files) <- samples

gtf_path <- snakemake@input[["gtf"]]
tx2gene_path <- snakemake@input[["tx2gene"]]

if (length(gtf_path) == 0) {
  gtf_path <- NULL
}
if (length(tx2gene_path) == 0) {
  tx2gene_path <- NULL
}

extract_attr <- function(x, key) {
  pattern <- paste0(key, " \"([^\"]+)\"")
  has_key <- grepl(pattern, x)
  value <- ifelse(has_key, sub(paste0(".*", pattern, ".*"), "\\1", x), NA_character_)
  value
}

tx2gene <- NULL
if (!is.null(tx2gene_path) && nzchar(tx2gene_path) && file.exists(tx2gene_path)) {
  tx2gene <- read_tsv(tx2gene_path, col_names = c("TXNAME", "GENEID"), show_col_types = FALSE)
} else if (!is.null(gtf_path) && nzchar(gtf_path) && file.exists(gtf_path)) {
  gtf <- read_tsv(
    gtf_path,
    comment = "#",
    col_names = FALSE,
    col_types = cols(.default = col_character()),
    show_col_types = FALSE
  )
  attrs <- gtf$X9
  tx2gene <- tibble(
    TXNAME = extract_attr(attrs, "transcript_id"),
    GENEID = extract_attr(attrs, "gene_id")
  ) %>%
    filter(!is.na(TXNAME), !is.na(GENEID)) %>%
    distinct()
} else {
  stop("Provide either tx2gene_tsv or gtf in config for tximport.")
}

txi <- tximport(quant_files, type = "salmon", tx2gene = tx2gene)

counts <- as.data.frame(txi$counts)
tpm <- as.data.frame(txi$abundance)

counts <- tibble(gene_id = rownames(counts)) %>% bind_cols(as_tibble(counts))
tpm <- tibble(gene_id = rownames(tpm)) %>% bind_cols(as_tibble(tpm))

qc <- tibble(
  sample = colnames(txi$counts),
  library_size = colSums(txi$counts)
)

dir.create(dirname(snakemake@output[["counts"]]), recursive = TRUE, showWarnings = FALSE)

write_tsv(counts, snakemake@output[["counts"]])
write_tsv(tpm, snakemake@output[["tpm"]])
write_tsv(qc, snakemake@output[["qc"]])
