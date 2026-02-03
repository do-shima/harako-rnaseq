suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(DESeq2)
  library(ggplot2)
})

counts_path <- snakemake@input[["counts"]]
sample_table_path <- snakemake@input[["sample_table"]]
contrasts <- snakemake@params[["contrasts"]]

# ---------- read counts ----------
counts_tbl <- read_tsv(counts_path, show_col_types = FALSE)
if (!"gene_id" %in% names(counts_tbl)) {
  stop("tximport counts file must include gene_id column.")
}

count_mat <- as.matrix(counts_tbl[, setdiff(names(counts_tbl), "gene_id"), drop = FALSE])
rownames(count_mat) <- counts_tbl$gene_id

# sanitize column names (samples)
samples <- trimws(colnames(count_mat))
colnames(count_mat) <- samples

# ---------- read sample table ----------
sample_tbl <- read_tsv(sample_table_path, show_col_types = FALSE)
required_cols <- c("sample", "condition")
if (!all(required_cols %in% names(sample_tbl))) {
  stop("Sample table must have columns: sample, condition.")
}

sample_tbl <- sample_tbl %>%
  mutate(
    sample = trimws(as.character(sample)),
    condition = trimws(as.character(condition))
  )

# ---------- strict match sample table vs counts columns ----------
matched <- sample_tbl %>% filter(sample %in% samples)
ord <- match(samples, matched$sample)

if (anyNA(ord) || nrow(matched) != length(samples)) {
  missing_in_sample_table <- setdiff(samples, matched$sample)
  extra_in_sample_table <- setdiff(sample_tbl$sample, samples)
  message("[deseq2] counts columns:")
  message(paste(samples, collapse = ", "))
  message("[deseq2] counts columns head:")
  message(paste(utils::head(samples, 5), collapse = ", "))
  message("[deseq2] sample_table sample column:")
  message(paste(sample_tbl$sample, collapse = ", "))
  message("[deseq2] missing_in_sample_table:")
  message(paste(missing_in_sample_table, collapse = ", "))
  message("[deseq2] extra_in_sample_table:")
  message(paste(extra_in_sample_table, collapse = ", "))
  stop(paste0(
    "Sample mismatch between counts columns and sample table.\n",
    "counts columns n=", length(samples), " matched rows n=", nrow(matched), "\n",
    "missing_in_sample_table: ", paste(missing_in_sample_table, collapse=", "), "\n",
    "extra_in_sample_table: ", paste(extra_in_sample_table, collapse=", ")
  ))
}

sample_tbl <- matched[ord, , drop = FALSE]
sample_tbl <- as.data.frame(sample_tbl)
rownames(sample_tbl) <- sample_tbl$sample

# ---------- condition sanity ----------
if (any(is.na(sample_tbl$condition)) || any(sample_tbl$condition == "")) {
  message("[deseq2] invalid condition values detected:")
  message(paste(sample_tbl$condition, collapse = ", "))
  stop("Sample table condition column contains NA/empty values.")
}
sample_tbl$condition <- factor(sample_tbl$condition, levels = unique(sample_tbl$condition))
sample_tbl$condition <- droplevels(sample_tbl$condition)
conditions <- levels(sample_tbl$condition)
message("[deseq2] conditions unique:")
message(paste(unique(as.character(sample_tbl$condition)), collapse = ", "))

# robust condition diagnostic without capture.output quoting issues
conditions_chr <- as.character(sample_tbl$condition)
cond_tab <- sort(table(conditions_chr, useNA = "ifany"), decreasing = TRUE)
cond_tab_str <- paste(sprintf("%s=%d", names(cond_tab), as.integer(cond_tab)), collapse = ", ")
message(paste0("[deseq2] condition counts: ", cond_tab_str))

single_condition <- length(conditions) < 2

if (single_condition) {
  message("[deseq2] Single condition detected; running QC-only mode (design ~ 1, no DE results).")
} else {
  sample_counts <- table(sample_tbl$condition)
  if (any(sample_counts < 2)) {
    warning("Fewer than 2 samples per condition detected; results may be unstable.")
  }
}

dir.create(dirname(snakemake@output[["results"]]), recursive = TRUE, showWarnings = FALSE)

if (single_condition) {
  design <- ~ 1
  dds <- DESeqDataSetFromMatrix(countData = round(count_mat), colData = sample_tbl, design = design)
  dds <- estimateSizeFactors(dds)
  vsd <- vst(dds, blind = TRUE)

  # PCA / heatmap
  pcaData <- plotPCA(vsd, intgroup = "condition", returnData = TRUE)
  percentVar <- round(100 * attr(pcaData, "percentVar"))
  p <- ggplot(pcaData, aes(x = PC1, y = PC2, color = condition)) +
    geom_point(size = 3) +
    xlab(paste0("PC1: ", percentVar[1], "%")) +
    ylab(paste0("PC2: ", percentVar[2], "%")) +
    theme_bw(base_size = 12)
  ggsave(filename = snakemake@output[["pca"]], plot = p, width = 6, height = 4)

  sample_dists <- dist(t(assay(vsd)))
  png(filename = snakemake@output[["heatmap"]], width = 900, height = 900)
  heatmap(as.matrix(sample_dists), symm = TRUE, margins = c(8, 8))
  dev.off()

  normalized <- counts(dds, normalized = TRUE)
  normalized_tbl <- tibble(gene_id = rownames(normalized)) %>% bind_cols(as_tibble(normalized))
  write_tsv(normalized_tbl, snakemake@output[["normalized"]])

  # placeholder MA plot
  png(filename = snakemake@output[["ma"]], width = 900, height = 700)
  plot.new()
  text(0.5, 0.5, "QC-only (single condition): MA plot not applicable", cex = 1.2)
  dev.off()

  # placeholder results
  stub <- tibble(
    contrast = "qc_only_single_condition",
    gene_id = rownames(normalized),
    baseMean = rowMeans(normalized),
    log2FoldChange = NA_real_,
    lfcSE = NA_real_,
    stat = NA_real_,
    pvalue = NA_real_,
    padj = NA_real_
  )
  write_tsv(stub, snakemake@output[["results"]])

} else {
  # ---------- DESeq2 ----------
  design <- ~ condition
  dds <- DESeqDataSetFromMatrix(countData = round(count_mat), colData = sample_tbl, design = design)
  dds <- DESeq(dds)
  vsd <- vst(dds, blind = TRUE)

  # ---------- PCA: always make ggplot ourselves ----------
  pcaData <- plotPCA(vsd, intgroup = "condition", returnData = TRUE)
  percentVar <- round(100 * attr(pcaData, "percentVar"))

  p <- ggplot(pcaData, aes(x = PC1, y = PC2, color = condition)) +
    geom_point(size = 3) +
    xlab(paste0("PC1: ", percentVar[1], "%")) +
    ylab(paste0("PC2: ", percentVar[2], "%")) +
    theme_bw(base_size = 12)

  ggsave(filename = snakemake@output[["pca"]], plot = p, width = 6, height = 4)

  # ---------- sample distance heatmap ----------
  sample_dists <- dist(t(assay(vsd)))
  png(filename = snakemake@output[["heatmap"]], width = 900, height = 900)
  heatmap(as.matrix(sample_dists), symm = TRUE, margins = c(8, 8))
  dev.off()

  # ---------- normalized counts ----------
  normalized <- counts(dds, normalized = TRUE)
  normalized_tbl <- tibble(gene_id = rownames(normalized)) %>% bind_cols(as_tibble(normalized))
  write_tsv(normalized_tbl, snakemake@output[["normalized"]])

  # ---------- contrasts ----------
  if (is.null(contrasts)) contrasts <- character(0)
  if (length(contrasts) == 0) {
    pairs <- combn(conditions, 2, simplify = FALSE)
    contrasts <- vapply(pairs, function(x) paste0(x[1], "_vs_", x[2]), character(1))
  }

  results_list <- list()
  first_ma <- TRUE

  for (contrast in contrasts) {
    parts <- strsplit(contrast, "_vs_", fixed = TRUE)[[1]]
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
}
