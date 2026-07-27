suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(ggplot2)
  library(jsonlite)
})

results_path <- snakemake@input[["results"]]
normalized_path <- snakemake@input[["normalized"]]
sample_table_path <- snakemake@input[["sample_table"]]
status_path <- snakemake@input[["status"]]
outputs <- snakemake@output

output_dir <- dirname(outputs[["summary_tsv"]])
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

status <- fromJSON(status_path, simplifyVector = FALSE)
results_tbl <- read_tsv(results_path, show_col_types = FALSE)
required_cols <- c(
  "contrast", "gene_id", "baseMean", "log2FoldChange",
  "lfcSE", "stat", "pvalue", "padj"
)
missing_cols <- setdiff(required_cols, names(results_tbl))
if (length(missing_cols) > 0) {
  stop(paste("DESeq2 results missing required columns:", paste(missing_cols, collapse = ", ")))
}

normalized_tbl <- read_tsv(normalized_path, show_col_types = FALSE)
if (!"gene_id" %in% names(normalized_tbl)) {
  stop("normalized_counts.tsv must include gene_id column.")
}
sample_tbl <- read_tsv(sample_table_path, show_col_types = FALSE)
if (!all(c("sample", "condition") %in% names(sample_tbl))) {
  stop("Sample table must include sample and condition columns.")
}
normalized_samples <- trimws(setdiff(names(normalized_tbl), "gene_id"))
if (!setequal(trimws(as.character(sample_tbl$sample)), normalized_samples)) {
  stop("normalized_counts columns do not match sample table.")
}

condition_counts <- status$condition_counts
summary_values <- list(
  analysis_mode = status$mode,
  reason_code = status$reason_code,
  condition_counts = toJSON(condition_counts, auto_unbox = TRUE),
  total_samples = status$total_samples,
  differential_results_available = status$differential_results_available,
  normalized_counts_available = status$normalized_counts_available,
  pca_available = status$pca_available,
  sample_distance_available = status$sample_distance_available,
  inferential_qc_plots_available = status$inferential_qc_plots_available
)
summary_tbl <- tibble(
  metric = names(summary_values),
  value = vapply(summary_values, function(value) as.character(value), character(1))
)
write_tsv(summary_tbl, outputs[["summary_tsv"]])
write_json(summary_values, outputs[["summary_json"]], pretty = TRUE, auto_unbox = TRUE)

placeholder <- function(path) {
  plot <- ggplot() +
    annotate("text", x = 0, y = 0, label = "Not applicable: QC-only analysis", size = 5) +
    xlim(-1, 1) +
    ylim(-1, 1) +
    theme_void()
  ggsave(filename = path, plot = plot, width = 7, height = 4.5)
}

if (!isTRUE(status$differential_results_available)) {
  for (path in c(outputs[["padj_hist"]], outputs[["lfc_hist"]], outputs[["mean_vs_lfc"]], outputs[["volcano"]])) {
    placeholder(path)
  }
} else {
  results_clean <- results_tbl %>%
    filter(!is.na(padj), !is.na(log2FoldChange), !is.na(baseMean))

  padj_plot <- ggplot(results_clean, aes(x = padj)) +
    geom_histogram(bins = 50, fill = "#4C78A8", color = "white") +
    facet_wrap(~contrast, scales = "free_y") +
    theme_minimal() +
    labs(title = "Adjusted p-value distribution", x = "padj", y = "Genes")
  lfc_plot <- ggplot(results_clean, aes(x = log2FoldChange)) +
    geom_histogram(bins = 60, fill = "#F58518", color = "white") +
    facet_wrap(~contrast, scales = "free_y") +
    theme_minimal() +
    labs(title = "log2 fold-change distribution", x = "log2FoldChange", y = "Genes")
  mean_vs_lfc_plot <- ggplot(results_clean, aes(x = baseMean + 1, y = log2FoldChange)) +
    geom_point(alpha = 0.35, size = 0.8, color = "#54A24B") +
    facet_wrap(~contrast) +
    scale_x_log10() +
    theme_minimal() +
    labs(title = "Mean expression vs log2 fold-change", x = "baseMean (log10)", y = "log2FoldChange")
  volcano_plot <- results_clean %>%
    mutate(sig = ifelse(padj <= 0.05, "padj <= 0.05", "ns")) %>%
    ggplot(aes(x = log2FoldChange, y = -log10(padj), color = sig)) +
    geom_point(alpha = 0.5, size = 0.9) +
    facet_wrap(~contrast) +
    theme_minimal() +
    scale_color_manual(values = c("padj <= 0.05" = "#E45756", "ns" = "#7F7F7F")) +
    labs(title = "Volcano plot", x = "log2FoldChange", y = "-log10(padj)")

  ggsave(outputs[["padj_hist"]], padj_plot, width = 7, height = 4.5)
  ggsave(outputs[["lfc_hist"]], lfc_plot, width = 7, height = 4.5)
  ggsave(outputs[["mean_vs_lfc"]], mean_vs_lfc_plot, width = 7, height = 4.5)
  ggsave(outputs[["volcano"]], volcano_plot, width = 7, height = 4.5)
}
