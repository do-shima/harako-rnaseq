suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(tximport)
})

quant_files <- snakemake@input[["quant"]]
if (is.null(quant_files)) {
  quant_files <- snakemake@input
}

# ---- normalize snakemake inputs to a plain character vector ----
files <- snakemake@input

# keep only quant.sf (snakemake input may include gtf etc.)
files <- files[grepl("quant\\.sf$", files)]

# coerce to plain character vector
if (is.list(files)) files <- unlist(files, use.names = FALSE)
files <- as.character(files)

stopifnot(length(files) > 0)
stopifnot(all(file.exists(files)))

# name by sample dir (/salmon/<sample>/quant.sf)
names(files) <- basename(dirname(files))

quant_files <- files

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

strip_after_bar <- function(x) {
  x <- as.character(x)
  parts <- strsplit(x, "|", fixed = TRUE)
  vapply(parts, function(p) if (length(p) >= 1) p[[1]] else "", character(1))
}
strip_version <- function(x) sub("\\..*$", "", x)
has_version <- function(x) any(grepl("\\.[0-9]+$", x))

debug_vec <- function(label, v, n = 5) {
  cat(label, " length=", length(v), " empty_count=", sum(v == ""), "\n", sep = "")
  cat(paste(head(v, n), collapse = "\n"), "\n")
  cat(label, " nchar(head) = ", paste(nchar(head(v, n)), collapse = ","), "\n", sep = "")
}

debug_enabled <- function() {
  val <- Sys.getenv("TXIMPORT_DEBUG", "0")
  val %in% c("1", "true", "TRUE", "yes", "YES")
}

q <- readr::read_tsv(quant_files[[1]], show_col_types = FALSE, progress = FALSE)
quant_ids_raw <- q$Name
quant_ids_bar <- strip_after_bar(quant_ids_raw)

if (debug_enabled()) {
  debug_vec("[tximport] quant.sf Name examples", quant_ids_raw)
  debug_vec("[tximport] quant.sf Name (bar-stripped) examples", quant_ids_bar)
}

if (length(quant_ids_bar) == 0 || all(quant_ids_bar == "")) {
  stop("quant_ids_bar is empty after strip_after_bar()")
}

tx_ids_raw <- tx2gene$TXNAME
tx_ids_bar <- strip_after_bar(tx_ids_raw)

if (debug_enabled()) {
  debug_vec("[tximport] tx2gene TXNAME examples", tx_ids_raw)
  debug_vec("[tximport] tx2gene TXNAME (bar-stripped) examples", tx_ids_bar)
}

if (length(tx_ids_bar) == 0 || all(tx_ids_bar == "")) {
  stop("tx_ids_bar is empty after strip_after_bar()")
}

q_has_ver <- has_version(quant_ids_bar)
tx_has_ver <- has_version(tx_ids_bar)
cat(sprintf("[tximport] version_present quant=%s tx2gene=%s\n", q_has_ver, tx_has_ver))
cat(sprintf("[tximport] inputs=%d outputs_dir=%s\n", length(quant_files), dirname(snakemake@output[["counts"]])))

tx2gene_norm <- tx2gene
quant_files_use <- quant_files

if (q_has_ver != tx_has_ver) {
  cat("[tximport] normalizing BOTH sides by stripping version suffixes\n")
  tx2gene_norm$TXNAME <- strip_version(tx_ids_bar)
  quant_files_use <- lapply(quant_files, function(path) {
    tbl <- readr::read_tsv(path, show_col_types = FALSE, progress = FALSE)
    tbl$Name <- strip_version(strip_after_bar(tbl$Name))
    tmp_path <- file.path(tempdir(), paste0(basename(path), ".norm.tsv"))
    readr::write_tsv(tbl, tmp_path)
    tmp_path
  })
} else {
  tx2gene_norm$TXNAME <- tx_ids_bar
}

txi <- tximport(
  files = quant_files_use,
  type = "salmon",
  tx2gene = tx2gene_norm,
  ignoreAfterBar = TRUE,
  ignoreTxVersion = FALSE
)

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
