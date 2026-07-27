suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(DESeq2)
  library(ggplot2)
  library(jsonlite)
})

counts_path <- snakemake@input[["counts"]]
sample_table_path <- snakemake@input[["sample_table"]]
contrasts <- snakemake@params[["contrasts"]]
plan <- snakemake@params[["analysis_plan"]]
outputs <- snakemake@output

result_columns <- c(
  "contrast", "gene_id", "baseMean", "log2FoldChange",
  "lfcSE", "stat", "pvalue", "padj"
)
warnings_out <- character(0)

placeholder_plot <- function(path, title, detail) {
  png(filename = path, width = 900, height = 650)
  plot.new()
  title(main = title)
  text(0.5, 0.5, detail, cex = 1.1)
  dev.off()
}

write_empty_results <- function(path) {
  empty <- tibble(
    contrast = character(),
    gene_id = character(),
    baseMean = numeric(),
    log2FoldChange = numeric(),
    lfcSE = numeric(),
    stat = numeric(),
    pvalue = numeric(),
    padj = numeric()
  )
  write_tsv(empty, path)
}

plan_scalar <- function(key) {
  value <- plan[[key]]
  if (length(value) == 0) return(NULL)
  value[[1]]
}

dir.create(dirname(outputs[["results"]]), recursive = TRUE, showWarnings = FALSE)

counts_tbl <- read_tsv(counts_path, show_col_types = FALSE)
if (!"gene_id" %in% names(counts_tbl)) {
  stop("tximport counts file must include gene_id column.")
}
count_columns <- setdiff(names(counts_tbl), "gene_id")
if (length(count_columns) == 0) {
  stop("tximport counts file has no sample columns.")
}
count_mat <- as.matrix(counts_tbl[, count_columns, drop = FALSE])
storage.mode(count_mat) <- "numeric"
rownames(count_mat) <- as.character(counts_tbl$gene_id)
colnames(count_mat) <- trimws(colnames(count_mat))
if (any(!is.finite(count_mat))) {
  stop("Count matrix contains non-finite values.")
}
if (any(count_mat < 0)) {
  stop("Count matrix contains negative values.")
}
if (all(count_mat == 0)) {
  stop("DESeq2 normalization is technically impossible: the count matrix is all zero.")
}

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
if (any(is.na(sample_tbl$sample)) || any(sample_tbl$sample == "")) {
  stop("Sample table contains an empty sample identifier.")
}
if (anyDuplicated(sample_tbl$sample)) {
  stop("Sample table contains duplicate sample identifiers.")
}
if (any(is.na(sample_tbl$condition)) || any(sample_tbl$condition == "")) {
  stop("Sample table contains an empty condition.")
}

samples <- colnames(count_mat)
ord <- match(samples, sample_tbl$sample)
if (anyNA(ord) || nrow(sample_tbl) != length(samples)) {
  stop(paste0(
    "Sample mismatch between counts columns and sample table. counts=",
    paste(samples, collapse = ","), " sample_table=",
    paste(sample_tbl$sample, collapse = ",")
  ))
}
sample_tbl <- as.data.frame(sample_tbl[ord, , drop = FALSE])
rownames(sample_tbl) <- sample_tbl$sample
sample_tbl$condition <- factor(
  sample_tbl$condition,
  levels = unique(as.character(sample_tbl$condition))
)
conditions <- levels(sample_tbl$condition)
condition_counts <- sort(table(as.character(sample_tbl$condition)))
actual_counts <- as.list(as.integer(condition_counts))
names(actual_counts) <- names(condition_counts)

plan_counts <- plan[["condition_counts"]]
plan_count_names <- sort(names(plan_counts))
actual_count_names <- sort(names(actual_counts))
counts_match <- identical(plan_count_names, actual_count_names)
if (counts_match) {
  counts_match <- all(vapply(
    actual_count_names,
    function(key) as.integer(plan_counts[[key]][[1]]) == as.integer(actual_counts[[key]]),
    logical(1)
  ))
}
eligible_actual <- length(actual_counts) >= 2 &&
  all(as.integer(unlist(actual_counts)) >= 2)
mode_actual <- if (eligible_actual) "differential" else "qc_only"
reason_actual <- if (eligible_actual) {
  "eligible"
} else if (length(actual_counts) < 2) {
  "single_condition"
} else {
  "insufficient_replicates"
}
if (
  !counts_match ||
  as.integer(plan_scalar("total_samples")) != nrow(sample_tbl) ||
  as.character(plan_scalar("mode")) != mode_actual ||
  as.character(plan_scalar("reason_code")) != reason_actual ||
  isTRUE(plan_scalar("eligible_for_de")) != eligible_actual
) {
  stop(paste0(
    "Frozen analysis_plan does not match the frozen sample table. expected_counts=",
    toJSON(plan_counts, auto_unbox = TRUE), " actual_counts=",
    toJSON(actual_counts, auto_unbox = TRUE), " frozen_mode=",
    plan_scalar("mode"), " actual_mode=", mode_actual
  ))
}

design_formula <- if (mode_actual == "differential") ~ condition else ~ 1
dds <- DESeqDataSetFromMatrix(
  countData = round(count_mat),
  colData = sample_tbl,
  design = design_formula
)
if (mode_actual == "differential") {
  dds <- DESeq(dds)
} else {
  dds <- tryCatch(
    estimateSizeFactors(dds),
    error = function(e) {
      stop(paste0(
        "DESeq2 normalization is technically impossible in QC-only mode: ",
        conditionMessage(e)
      ))
    }
  )
}

normalized <- counts(dds, normalized = TRUE)
if (any(!is.finite(normalized))) {
  stop("DESeq2 normalization produced non-finite values.")
}
normalized_tbl <- tibble(gene_id = rownames(normalized)) %>%
  bind_cols(as_tibble(normalized, .name_repair = "minimal"))
write_tsv(normalized_tbl, outputs[["normalized"]])

transformed <- NULL
transform_name <- "variance stabilizing transformation"
transformed <- tryCatch(
  assay(varianceStabilizingTransformation(dds, blind = TRUE)),
  error = function(e) {
    warnings_out <<- c(
      warnings_out,
      paste0(
        "VST unavailable; descriptive PCA and sample distances use ",
        "log2(normalized counts + 1): ", conditionMessage(e)
      )
    )
    transform_name <<- "log2(normalized counts + 1)"
    log2(normalized + 1)
  }
)

pca_available <- FALSE
distance_available <- FALSE
if (ncol(transformed) < 2) {
  placeholder_plot(
    outputs[["pca"]],
    "PCA unavailable",
    "At least two samples are required."
  )
  placeholder_plot(
    outputs[["heatmap"]],
    "Sample distance unavailable",
    "At least two samples are required."
  )
} else {
  varying <- apply(transformed, 1, function(values) stats::var(values) > 0)
  if (sum(varying) >= 2) {
    pca_fit <- tryCatch(prcomp(t(transformed[varying, , drop = FALSE])), error = function(e) NULL)
    if (!is.null(pca_fit) && ncol(pca_fit$x) >= 2) {
      pca_df <- data.frame(
        PC1 = pca_fit$x[, 1],
        PC2 = pca_fit$x[, 2],
        condition = sample_tbl[rownames(pca_fit$x), "condition", drop = TRUE]
      )
      variance <- round(100 * (pca_fit$sdev^2 / sum(pca_fit$sdev^2)))
      p <- ggplot(pca_df, aes(x = PC1, y = PC2, color = condition)) +
        geom_point(size = 3) +
        xlab(paste0("PC1: ", variance[1], "%")) +
        ylab(paste0("PC2: ", variance[2], "%")) +
        labs(subtitle = transform_name) +
        theme_bw(base_size = 12)
      ggsave(filename = outputs[["pca"]], plot = p, width = 6, height = 4)
      pca_available <- TRUE
    } else {
      placeholder_plot(
        outputs[["pca"]],
        "PCA unavailable",
        "The transformed matrix does not support two principal components."
      )
    }
  } else {
    placeholder_plot(
      outputs[["pca"]],
      "PCA unavailable",
      "At least two varying genes are required."
    )
  }

  distance_ok <- tryCatch({
    sample_dists <- dist(t(transformed))
    png(filename = outputs[["heatmap"]], width = 900, height = 900)
    heatmap(as.matrix(sample_dists), symm = TRUE, margins = c(8, 8))
    dev.off()
    TRUE
  }, error = function(e) {
    if (dev.cur() > 1) dev.off()
    warnings_out <<- c(warnings_out, paste0("Sample distance unavailable: ", conditionMessage(e)))
    FALSE
  })
  if (distance_ok) {
    distance_available <- TRUE
  } else {
    placeholder_plot(
      outputs[["heatmap"]],
      "Sample distance unavailable",
      "The transformed matrix could not be compared."
    )
  }
}

differential_available <- FALSE
ma_available <- FALSE
if (mode_actual == "qc_only") {
  write_empty_results(outputs[["results"]])
  placeholder_plot(
    outputs[["ma"]],
    "MA plot not applicable",
    "Inferential differential-expression analysis was not performed."
  )
} else {
  if (is.null(contrasts)) contrasts <- character(0)
  contrasts <- unlist(contrasts, use.names = FALSE)
  if (length(contrasts) == 0) {
    pairs <- combn(conditions, 2, simplify = FALSE)
    contrasts <- vapply(
      pairs,
      function(pair) paste0(pair[1], "_vs_", pair[2]),
      character(1)
    )
  }
  results_list <- list()
  first_ma <- TRUE
  for (contrast in contrasts) {
    parts <- strsplit(contrast, "_vs_", fixed = TRUE)[[1]]
    if (length(parts) != 2 || !all(parts %in% conditions) || parts[1] == parts[2]) {
      stop(paste("Invalid contrast for frozen differential plan:", contrast))
    }
    res <- results(dds, contrast = c("condition", parts[1], parts[2]))
    res_tbl <- as.data.frame(res)
    res_tbl$gene_id <- rownames(res_tbl)
    res_tbl$contrast <- contrast
    results_list[[contrast]] <- res_tbl

    ma_path <- file.path(dirname(outputs[["ma"]]), paste0("ma_plot_", contrast, ".png"))
    png(filename = ma_path, width = 900, height = 700)
    plotMA(res, main = contrast)
    dev.off()
    if (first_ma) {
      file.copy(ma_path, outputs[["ma"]], overwrite = TRUE)
      first_ma <- FALSE
      ma_available <- TRUE
    }
  }
  results_tbl <- bind_rows(results_list) %>%
    select(all_of(result_columns))
  write_tsv(results_tbl, outputs[["results"]])
  differential_available <- TRUE
}

status <- list(
  schema_version = 1,
  policy_version = as.integer(plan_scalar("policy_version")),
  mode = mode_actual,
  structurally_valid = TRUE,
  eligible_for_de = eligible_actual,
  reason_code = reason_actual,
  condition_counts = actual_counts,
  total_samples = nrow(sample_tbl),
  differential_results_available = differential_available,
  normalized_counts_available = TRUE,
  pca_available = pca_available,
  sample_distance_available = distance_available,
  ma_plot_available = ma_available,
  inferential_qc_plots_available = differential_available,
  enrichment_allowed = differential_available && isTRUE(plan_scalar("enrichment_allowed")),
  warnings = as.list(warnings_out)
)
write_json(
  status,
  outputs[["status"]],
  pretty = TRUE,
  auto_unbox = TRUE,
  null = "null"
)
