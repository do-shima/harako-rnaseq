suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(DESeq2)
  library(ggplot2)
})

counts_path <- snakemake@input[["counts"]]
sample_table_path <- snakemake@input[["sample_table"]]
contrasts <- snakemake@params[["contrasts"]]

counts_tbl <- read_tsv(counts_path, show_col_types = FALSE)
if (!"gene_id" %in% names(counts_tbl)) {
  stop("tximport counts file must include gene_id column.")
}

count_mat <- as.matrix(counts_tbl[, setdiff(names(counts_tbl), "gene_id")])
rownames(count_mat) <- counts_tbl$gene_id

sample_tbl <- read_tsv(sample_table_path, show_col_types = FALSE)
required_cols <- c("sample", "condition")
if (!all(required_cols %in% names(sample_tbl))) {
  stop("Sample table must have columns: sample, condition.")
}

samples <- colnames(count_mat)
sample_tbl <- sample_tbl %>% filter(sample %in% samples)
sample_tbl <- sample_tbl %>% mutate(condition = as.character(condition))
sample_tbl <- sample_tbl %>% arrange(match(sample, samples))
rownames(sample_tbl) <- sample_tbl$sample

conditions <- unique(sample_tbl$condition)
if (length(conditions) < 2) {
  stop("At least two conditions are required for DESeq2.")
}

sample_counts <- table(sample_tbl$condition)
if (any(sample_counts < 2)) {
  warning("Fewer than 2 samples per condition detected; results may be unstable.")
}

sample_tbl$condition <- factor(sample_tbl$condition, levels = conditions)

dds <- DESeqDataSetFromMatrix(countData = round(count_mat), colData = sample_tbl, design = ~condition)
dds <- DESeq(dds)

vsd <- vst(dds, blind = TRUE)

dir.create(dirname(snakemake@output[["results"]]), recursive = TRUE, showWarnings = FALSE)

pca_plot <- plotPCA(vsd, intgroup = "condition")
ggsave(filename = snakemake@output[["pca"]], plot = pca_plot, width = 6, height = 4)

sample_dists <- dist(t(assay(vsd)))
png(filename = snakemake@output[["heatmap"]], width = 900, height = 900)
heatmap(as.matrix(sample_dists), symm = TRUE, margins = c(8, 8))
dev.off()

normalized <- counts(dds, normalized = TRUE)
normalized_tbl <- tibble(gene_id = rownames(normalized)) %>% bind_cols(as_tibble(normalized))
write_tsv(normalized_tbl, snakemake@output[["normalized"]])

if (length(contrasts) == 0) {
  if (length(conditions) >= 2) {
    pairs <- combn(conditions, 2, simplify = FALSE)
    contrasts <- vapply(pairs, function(x) paste0(x[1], "_vs_", x[2]), character(1))
  }
}

results_list <- list()
first_ma <- TRUE
for (contrast in contrasts) {
  parts <- strsplit(contrast, "_vs_")[[1]]
  if (length(parts) != 2) {
    stop(paste("Invalid contrast format:", contrast))
  }
  res <- results(dds, contrast = c("condition", parts[1], parts[2]))
  res_tbl <- as.data.frame(res)
  res_tbl$gene_id <- rownames(res_tbl)
  res_tbl$contrast <- contrast
  results_list[[contrast]] <- res_tbl

  ma_path <- file.path(dirname(snakemake@output[["ma"]]), paste0("ma_plot_", contrast, ".png"))
  png(filename = ma_path, width = 900, height = 700)
  plotMA(res, main = contrast)
  dev.off()

  if (first_ma) {
    file.copy(ma_path, snakemake@output[["ma"]], overwrite = TRUE)
    first_ma <- FALSE
  }
}

results_tbl <- bind_rows(results_list) %>%
  select(contrast, gene_id, everything())

write_tsv(results_tbl, snakemake@output[["results"]])
