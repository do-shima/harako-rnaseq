suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(tximport)
})

debug_enabled <- function() {
  val <- Sys.getenv("TXIMPORT_DEBUG", "0")
  val %in% c("1", "true", "TRUE", "yes", "YES")
}

quant_files <- snakemake@input[["quant"]]
if (is.null(quant_files) || length(quant_files) == 0) {
  quant_files <- snakemake@input
}

# ---- normalize snakemake inputs to a plain character vector ----
files <- quant_files

# keep only quant.sf (snakemake input may include gtf etc.)
files <- files[grepl("quant\\.sf$", files)]

# coerce to plain character vector
if (is.list(files)) files <- unlist(files, use.names = FALSE)
files <- as.character(files)

sample_names <- names(files)
if (is.null(sample_names) || length(sample_names) != length(files)) {
  sample_names <- rep("", length(files))
}
sample_names <- vapply(seq_along(files), function(i) {
  val <- sample_names[[i]]
  if (is.null(val) || is.na(val) || val == "") {
    basename(dirname(files[[i]]))
  } else {
    val
  }
}, character(1))

files <- setNames(as.character(files), sample_names)
N <- length(sample_names)
stopifnot(is.character(files), length(files) == N, !is.null(names(files)))

if (debug_enabled()) {
  cat("[tximport] files class=", paste(class(files), collapse = ","), "\n", sep = "")
  cat("[tximport] files length=", length(files), "\n", sep = "")
  cat("[tximport] files head:\n")
  cat(paste(head(files, 5), collapse = "\n"), "\n")
}

stopifnot(length(files) > 0)
stopifnot(all(file.exists(files)))

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

tx2gene <- tx2gene %>%
  filter(!is.na(TXNAME), !is.na(GENEID), TXNAME != "", GENEID != "") %>%
  distinct()

strip_after_space <- function(x) {
  sub(" .*", "", as.character(x))
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

q <- readr::read_tsv(quant_files[[1]], show_col_types = FALSE, progress = FALSE)
quant_ids_raw <- q$Name
quant_ids_bar <- strip_after_bar(strip_after_space(quant_ids_raw))

if (debug_enabled()) {
  debug_vec("[tximport] quant.sf Name examples", quant_ids_raw)
  debug_vec("[tximport] quant.sf Name (bar-stripped) examples", quant_ids_bar)
}

if (length(quant_ids_bar) == 0 || all(quant_ids_bar == "")) {
  stop("quant_ids_bar is empty after strip_after_bar()")
}

tx_ids_raw <- tx2gene$TXNAME
tx_ids_bar <- strip_after_bar(strip_after_space(tx_ids_raw))

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
ignore_tx_version <- FALSE

overlap_rate <- function(x, y) {
  if (length(x) == 0 || length(y) == 0) return(0)
  length(intersect(unique(x), unique(y))) / length(unique(y))
}

strip_versions <- function() {
  cat("[tximport] normalizing BOTH sides by stripping version suffixes\n")
  tx2gene_norm$TXNAME <<- strip_version(tx_ids_bar)
  quant_files_use <<- vapply(seq_along(quant_files), function(i) {
    path <- quant_files[[i]]
    sample_id <- names(quant_files)[[i]]
    if (is.null(sample_id) || is.na(sample_id) || sample_id == "") {
      sample_id <- basename(dirname(path))
    }
    tbl <- readr::read_tsv(path, show_col_types = FALSE, progress = FALSE)
    tbl$Name <- strip_version(strip_after_bar(strip_after_space(tbl$Name)))
    tmp_path <- file.path(tempdir(), sprintf("%s.quant.norm.%d.tsv", sample_id, i))
    readr::write_tsv(tbl, tmp_path)
    stopifnot(file.exists(tmp_path))
    tmp_path
  }, character(1))
  names(quant_files_use) <<- names(quant_files)
  ignore_tx_version <<- TRUE
}

overlap_raw <- overlap_rate(quant_ids_bar, tx_ids_bar)
if (debug_enabled()) {
  cat(sprintf("[tximport] overlap_rate raw=%.4f\n", overlap_raw))
}

if (q_has_ver != tx_has_ver) {
  strip_versions()
} else {
  tx2gene_norm$TXNAME <- tx_ids_bar
}

overlap_norm <- overlap_rate(quant_ids_bar, tx2gene_norm$TXNAME)
if (debug_enabled()) {
  cat(sprintf("[tximport] overlap_rate norm=%.4f\n", overlap_norm))
}

if (overlap_norm < 0.01) {
  strip_versions()
  overlap_norm2 <- overlap_rate(strip_version(quant_ids_bar), tx2gene_norm$TXNAME)
  cat(sprintf("[tximport] overlap_rate fallback=%.4f\n", overlap_norm2))
  if (overlap_norm2 < 0.01) {
    stop("tximport ID overlap is too low; check GTF/FASTA release consistency (Ensembl rat often fails when releases differ).")
  }
}

names(quant_files_use) <- names(quant_files)
quant_files_use <- setNames(as.character(quant_files_use), names(quant_files_use))
stopifnot(all(file.exists(quant_files_use)))

txi <- tximport(
  files = quant_files_use,
  type = "salmon",
  tx2gene = tx2gene_norm,
  ignoreAfterBar = TRUE,
  ignoreTxVersion = ignore_tx_version
)

if (is.null(colnames(txi$counts)) || any(colnames(txi$counts) == "")) {
  colnames(txi$counts) <- names(quant_files_use)
}
if (is.null(colnames(txi$abundance)) || any(colnames(txi$abundance) == "")) {
  colnames(txi$abundance) <- names(quant_files_use)
}

counts <- as.data.frame(txi$counts)
tpm <- as.data.frame(txi$abundance)

required_cols <- c("gene_id", names(quant_files_use))
missing_counts <- setdiff(required_cols, c("gene_id", colnames(counts)))
missing_tpm <- setdiff(required_cols, c("gene_id", colnames(tpm)))
if (length(missing_counts) > 0 || length(missing_tpm) > 0) {
  cat("[tximport] files names:\n")
  cat(paste(names(quant_files_use), collapse = "\n"), "\n")
  cat("[tximport] counts colnames:\n")
  cat(paste(colnames(counts), collapse = "\n"), "\n")
  cat("[tximport] tpm colnames:\n")
  cat(paste(colnames(tpm), collapse = "\n"), "\n")
  cat("[tximport] counts head:\n")
  print(utils::head(counts, 2))
  cat("[tximport] tpm head:\n")
  print(utils::head(tpm, 2))
  stopifnot(length(missing_counts) == 0, length(missing_tpm) == 0)
}

counts <- tibble(gene_id = rownames(counts)) %>% bind_cols(as_tibble(counts))
tpm <- tibble(gene_id = rownames(tpm)) %>% bind_cols(as_tibble(tpm))

qc <- tibble(
  sample = colnames(txi$counts),
  library_size = colSums(txi$counts)
)

final_required <- c("gene_id", names(quant_files_use))
final_missing_counts <- setdiff(final_required, names(counts))
final_missing_tpm <- setdiff(final_required, names(tpm))
if (length(final_missing_counts) > 0 || length(final_missing_tpm) > 0) {
  cat("[tximport] final columns missing\n")
  cat("[tximport] counts names:\n")
  cat(paste(names(counts), collapse = "\n"), "\n")
  cat("[tximport] tpm names:\n")
  cat(paste(names(tpm), collapse = "\n"), "\n")
  stopifnot(length(final_missing_counts) == 0, length(final_missing_tpm) == 0)
}

dir.create(dirname(snakemake@output[["counts"]]), recursive = TRUE, showWarnings = FALSE)

write_tsv(counts, snakemake@output[["counts"]])
write_tsv(tpm, snakemake@output[["tpm"]])
write_tsv(qc, snakemake@output[["qc"]])
