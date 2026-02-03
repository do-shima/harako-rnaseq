suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(ggplot2)
  library(jsonlite)
})

results_path <- snakemake@input[["results"]]
normalized_path <- snakemake@input[["normalized"]]
sample_table_path <- snakemake@input[["sample_table"]]

output_dir <- dirname(snakemake@output[["summary_tsv"]])
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

results_tbl <- read_tsv(results_path, show_col_types = FALSE)
required_cols <- c("contrast", "gene_id", "baseMean", "log2FoldChange", "pvalue", "padj")
missing_cols <- setdiff(required_cols, names(results_tbl))
if (length(missing_cols) > 0) {
  stop(paste("DESeq2 results missing required columns:", paste(missing_cols, collapse = ", ")))
}

normalized_tbl <- read_tsv(normalized_path, show_col_types = FALSE)
if (!"gene_id" %in% names(normalized_tbl)) {
  stop("normalized_counts.tsv must include gene_id column.")
}

sample_tbl <- read_tsv(sample_table_path, show_col_types = FALSE)
required_sample_cols <- c("sample", "condition")
missing_sample_cols <- setdiff(required_sample_cols, names(sample_tbl))
if (length(missing_sample_cols) > 0) {
  stop(paste("Sample table missing required columns:", paste(missing_sample_cols, collapse = ", ")))
}

sample_tbl <- sample_tbl %>% mutate(sample = trimws(as.character(sample)))
normalized_samples <- setdiff(names(normalized_tbl), "gene_id")
normalized_samples <- trimws(normalized_samples)
missing_samples <- setdiff(sample_tbl$sample, normalized_samples)
extra_samples <- setdiff(normalized_samples, sample_tbl$sample)
if (length(missing_samples) > 0 || length(extra_samples) > 0) {
  message("Sample mismatch detected in normalized_counts vs sample table.")
  message("Missing samples: ", paste(missing_samples, collapse = ", "))
  message("Extra samples: ", paste(extra_samples, collapse = ", "))
  stop("normalized_counts columns do not match sample table.")
}

summary_tbl <- results_tbl %>%
  group_by(contrast) %>%
  summarise(
    genes = n(),
    padj_lt_0_05 = sum(!is.na(padj) & padj <= 0.05),
    lfc_gt_1 = sum(!is.na(log2FoldChange) & log2FoldChange >= 1),
    lfc_lt_minus_1 = sum(!is.na(log2FoldChange) & log2FoldChange <= -1),
    median_baseMean = median(baseMean, na.rm = TRUE),
    .groups = "drop"
  )

write_tsv(summary_tbl, snakemake@output[["summary_tsv"]])

qc_payload <- list(
  generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  summary = summary_tbl
)
write_json(qc_payload, snakemake@output[["summary_json"]], pretty = TRUE, auto_unbox = TRUE)

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

plot_outputs <- list(
  padj_plot = snakemake@output[["padj_hist"]],
  lfc_plot = snakemake@output[["lfc_hist"]],
  mean_vs_lfc_plot = snakemake@output[["mean_vs_lfc"]],
  volcano_plot = snakemake@output[["volcano"]]
)

ggsave(filename = plot_outputs$padj_plot, plot = padj_plot, width = 7, height = 4.5)

ggsave(filename = plot_outputs$lfc_plot, plot = lfc_plot, width = 7, height = 4.5)

ggsave(filename = plot_outputs$mean_vs_lfc_plot, plot = mean_vs_lfc_plot, width = 7, height = 4.5)

ggsave(filename = plot_outputs$volcano_plot, plot = volcano_plot, width = 7, height = 4.5)
