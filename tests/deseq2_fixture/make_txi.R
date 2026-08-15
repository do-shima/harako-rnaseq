suppressPackageStartupMessages(library(readr))

counts_tbl <- read_tsv(snakemake@input[[1]], show_col_types = FALSE)
counts <- as.matrix(counts_tbl[, setdiff(names(counts_tbl), "gene_id"), drop = FALSE])
storage.mode(counts) <- "numeric"
rownames(counts) <- counts_tbl$gene_id

lengths <- matrix(
  1000,
  nrow = nrow(counts),
  ncol = ncol(counts),
  dimnames = dimnames(counts)
)
if (identical(snakemake@params[["length_pattern"]], "changing") && nrow(lengths) > 0) {
  lengths[1, seq_len(ncol(lengths)) %% 2 == 0] <- 250
}
abundance <- sweep(counts / lengths, 2, colSums(counts / lengths), "/") * 1e6
txi <- list(
  abundance = abundance,
  counts = counts,
  length = lengths,
  countsFromAbundance = "no"
)
dir.create(dirname(snakemake@output[[1]]), recursive = TRUE, showWarnings = FALSE)
saveRDS(txi, snakemake@output[[1]])
