suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(ggplot2)
  library(jsonlite)
})

status_payload <- function(ok, skipped, reason, inputs, config, versions) {
  list(
    ok = ok,
    skipped = skipped,
    reason = reason,
    inputs = inputs,
    config = config,
    versions = versions
  )
}

write_status <- function(path, payload) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  writeLines(jsonlite::toJSON(payload, auto_unbox = TRUE, pretty = TRUE), path)
}

safe_version <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) return(NA_character_)
  as.character(utils::packageVersion(pkg))
}

ratio_to_num <- function(x) {
  parts <- strsplit(x, "/", fixed = TRUE)
  vapply(parts, function(p) {
    if (length(p) != 2) return(NA_real_)
    a <- suppressWarnings(as.numeric(p[[1]]))
    b <- suppressWarnings(as.numeric(p[[2]]))
    if (is.na(a) || is.na(b) || b == 0) return(NA_real_)
    a / b
  }, numeric(1))
}

write_ora <- function(tbl, out_tsv, out_png, top_n) {
  if (nrow(tbl) == 0) return(FALSE)
  out_tbl <- tbl %>%
    transmute(
      term_id = ID,
      description = Description,
      pvalue = pvalue,
      padj = p.adjust,
      gene_count = Count,
      gene_ratio = GeneRatio,
      bg_ratio = BgRatio,
      genes = gsub("/", ";", geneID)
    )
  readr::write_tsv(out_tbl, out_tsv)
  plot_tbl <- out_tbl %>%
    mutate(gene_ratio_num = ratio_to_num(gene_ratio)) %>%
    arrange(padj) %>%
    head(top_n)
  if (nrow(plot_tbl) == 0) return(TRUE)
  p <- ggplot(plot_tbl, aes(x = gene_ratio_num, y = reorder(description, gene_ratio_num))) +
    geom_point(aes(size = gene_count, color = -log10(padj))) +
    scale_color_viridis_c(option = "C") +
    labs(x = "Gene ratio", y = NULL, color = "-log10(padj)", size = "Gene count") +
    theme_bw(base_size = 12)
  ggsave(out_png, plot = p, width = 8, height = 5)
  TRUE
}

write_gsea <- function(tbl, out_tsv, out_png, top_n) {
  if (nrow(tbl) == 0) return(FALSE)
  out_tbl <- tbl %>%
    transmute(
      term_id = pathway,
      description = name,
      pvalue = pval,
      padj = padj,
      NES = NES,
      size = size,
      leading_edge = vapply(leadingEdge, function(x) paste(x, collapse = ";"), character(1))
    )
  readr::write_tsv(out_tbl, out_tsv)
  plot_tbl <- out_tbl %>%
    arrange(padj) %>%
    head(top_n)
  if (nrow(plot_tbl) == 0) return(TRUE)
  p <- ggplot(plot_tbl, aes(x = NES, y = reorder(description, NES))) +
    geom_point(aes(size = size, color = -log10(padj))) +
    scale_color_viridis_c(option = "C") +
    labs(x = "NES", y = NULL, color = "-log10(padj)", size = "Size") +
    theme_bw(base_size = 12)
  ggsave(out_png, plot = p, width = 8, height = 5)
  TRUE
}

select_orgdb <- function(species) {
  species <- tolower(species %||% "")
  if (species == "human") return("org.Hs.eg.db")
  if (species == "mouse") return("org.Mm.eg.db")
  if (species == "rat") return("org.Rn.eg.db")
  NA_character_
}

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x

results_path <- snakemake@input[["results"]]
deseq_status_path <- snakemake@input[["status"]]
outdir <- snakemake@params[["outdir"]]
species <- snakemake@params[["species"]]
alpha <- snakemake@params[["alpha"]] %||% 0.05
lfc <- snakemake@params[["lfc"]] %||% 0
top_terms <- snakemake@params[["top_terms"]] %||% 15
methods <- snakemake@params[["methods"]] %||% c("ORA", "GSEA")
rank_metric <- snakemake@params[["rank_metric"]] %||% "stat"

dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

if (!file.exists(results_path)) {
  stop("DESeq2 results.tsv not found.")
}
if (!file.exists(deseq_status_path)) {
  stop("DESeq2 status.json not found.")
}
deseq_status <- jsonlite::fromJSON(deseq_status_path, simplifyVector = FALSE)
if (
  !identical(deseq_status$mode, "differential") ||
  !isTRUE(deseq_status$differential_results_available) ||
  !isTRUE(deseq_status$enrichment_allowed)
) {
  stop("Enrichment requires available inferential differential-expression results.")
}

results_tbl <- readr::read_tsv(results_path, show_col_types = FALSE)
if (!"contrast" %in% names(results_tbl)) {
  stop("DESeq2 results.tsv must include contrast column.")
}

if (!requireNamespace("AnnotationDbi", quietly = TRUE)) {
  for (contrast in unique(results_tbl$contrast)) {
    out_contrast <- file.path(outdir, paste0("contrast=", contrast))
    status_path <- file.path(out_contrast, "status.json")
    payload <- status_payload(
      ok = FALSE,
      skipped = TRUE,
      reason = "AnnotationDbi not available",
      inputs = list(deseq_tsv = results_path, contrast = contrast, species = species),
      config = list(alpha = alpha, lfc = lfc, top_terms = top_terms, methods = methods,
                    gene_set = "GO:BP", rank_metric = rank_metric),
      versions = list(
        R = as.character(getRversion()),
        AnnotationDbi = safe_version("AnnotationDbi")
      )
    )
    write_status(status_path, payload)
  }
  file.create(snakemake@output[["done"]])
  quit(save = "no", status = 0)
}

orgdb_pkg <- select_orgdb(species)
versions <- list(
  R = as.character(getRversion()),
  clusterProfiler = safe_version("clusterProfiler"),
  fgsea = safe_version("fgsea"),
  AnnotationDbi = safe_version("AnnotationDbi"),
  orgdb = safe_version(orgdb_pkg)
)

if (is.na(orgdb_pkg) || !requireNamespace(orgdb_pkg, quietly = TRUE)) {
  for (contrast in unique(results_tbl$contrast)) {
    out_contrast <- file.path(outdir, paste0("contrast=", contrast))
    status_path <- file.path(out_contrast, "status.json")
    payload <- status_payload(
      ok = FALSE,
      skipped = TRUE,
      reason = paste0("orgdb unavailable for species=", species),
      inputs = list(deseq_tsv = results_path, contrast = contrast, species = species),
      config = list(alpha = alpha, lfc = lfc, top_terms = top_terms, methods = methods,
                    gene_set = "GO:BP", rank_metric = rank_metric),
      versions = versions
    )
    write_status(status_path, payload)
  }
  file.create(snakemake@output[["done"]])
  quit(save = "no", status = 0)
}

orgdb <- get(orgdb_pkg, envir = asNamespace(orgdb_pkg))

for (contrast in unique(results_tbl$contrast)) {
  out_contrast <- file.path(outdir, paste0("contrast=", contrast))
  dir.create(out_contrast, recursive = TRUE, showWarnings = FALSE)
  status_path <- file.path(out_contrast, "status.json")
  payload_base <- list(
    inputs = list(deseq_tsv = results_path, contrast = contrast, species = species),
    config = list(alpha = alpha, lfc = lfc, top_terms = top_terms, methods = methods,
                  gene_set = "GO:BP", rank_metric = rank_metric),
    versions = versions
  )

  contrast_tbl <- results_tbl %>%
    filter(.data$contrast == contrast)

  if (!all(c("gene_id", "log2FoldChange", "padj", rank_metric) %in% names(contrast_tbl))) {
    payload <- status_payload(
      ok = FALSE,
      skipped = TRUE,
      reason = "missing required columns in results.tsv",
      inputs = payload_base$inputs,
      config = payload_base$config,
      versions = payload_base$versions
    )
    write_status(status_path, payload)
    next
  }

  contrast_tbl <- contrast_tbl %>%
    mutate(
      gene_id = gsub("\\\\..*$", "", as.character(gene_id)),
      padj = as.numeric(padj),
      log2FoldChange = as.numeric(log2FoldChange)
    )

  entrez_ids <- AnnotationDbi::mapIds(
    orgdb,
    keys = contrast_tbl$gene_id,
    keytype = "ENSEMBL",
    column = "ENTREZID",
    multiVals = "first"
  )

  contrast_tbl$entrez_id <- unname(entrez_ids)
  mapping_rate <- mean(!is.na(contrast_tbl$entrez_id))

  if (is.na(mapping_rate) || mapping_rate < 0.05) {
    payload <- status_payload(
      ok = FALSE,
      skipped = TRUE,
      reason = "low mapping rate for ENSEMBL -> ENTREZ",
      inputs = payload_base$inputs,
      config = payload_base$config,
      versions = payload_base$versions
    )
    write_status(status_path, payload)
    next
  }

  ok_any <- FALSE
  method_errors <- c()
  had_error <- FALSE

  if ("ORA" %in% methods) {
    tryCatch({
      if (!requireNamespace("clusterProfiler", quietly = TRUE)) {
        stop("clusterProfiler not available")
      }
      sig_tbl <- contrast_tbl %>%
        filter(!is.na(padj), padj <= alpha, abs(log2FoldChange) >= lfc, !is.na(entrez_id))
      genes <- unique(sig_tbl$entrez_id)
      if (length(genes) == 0) {
        method_errors <- c(method_errors, "ORA: no significant genes")
      } else {
        ora <- clusterProfiler::enrichGO(
          gene = genes,
          OrgDb = orgdb,
          keyType = "ENTREZID",
          ont = "BP",
          pvalueCutoff = alpha,
          qvalueCutoff = alpha,
          pAdjustMethod = "BH",
          readable = FALSE
        )
        ora_tbl <- as.data.frame(ora)
        ora_ok <- write_ora(
          ora_tbl,
          file.path(out_contrast, "ora_go_bp.tsv"),
          file.path(out_contrast, "ora_go_bp_dotplot.png"),
          top_terms
        )
        ok_any <- ok_any || ora_ok
      }
    }, error = function(e) {
      had_error <<- TRUE
      method_errors <<- c(method_errors, paste0("ORA: ", conditionMessage(e)))
    })
  }

  if ("GSEA" %in% methods) {
    tryCatch({
      if (!requireNamespace("fgsea", quietly = TRUE)) {
        stop("fgsea not available")
      }
      if (!requireNamespace("GO.db", quietly = TRUE)) {
        stop("GO.db not available")
      }
      go_db <- get("GO.db", envir = asNamespace("GO.db"))
      ranked <- contrast_tbl %>%
        filter(!is.na(entrez_id), !is.na(.data[[rank_metric]])) %>%
        mutate(rank = as.numeric(.data[[rank_metric]]))
      if (nrow(ranked) == 0) {
        method_errors <- c(method_errors, "GSEA: no ranked genes")
      } else {
        stats <- ranked$rank
        names(stats) <- ranked$entrez_id
        stats <- sort(stats, decreasing = TRUE)

        go_map <- AnnotationDbi::select(
          orgdb,
          keys = unique(ranked$entrez_id),
          keytype = "ENTREZID",
          columns = c("GO", "ONTOLOGY")
        )
        go_map <- go_map %>% filter(!is.na(GO), ONTOLOGY == "BP")
        pathways <- split(go_map$ENTREZID, go_map$GO)
        pathways <- lapply(pathways, unique)
        if (length(pathways) == 0) {
          method_errors <- c(method_errors, "GSEA: no GO:BP gene sets")
        } else {
          fg <- fgsea::fgsea(
            pathways = pathways,
            stats = stats,
            minSize = 10,
            maxSize = 500,
            eps = 1e-6
          )
          if (nrow(fg) > 0) {
            go_names <- AnnotationDbi::select(go_db, keys = fg$pathway, columns = "TERM", keytype = "GOID")
            fg$name <- go_names$TERM[match(fg$pathway, go_names$GOID)]
            fg_ok <- write_gsea(
              fg,
              file.path(out_contrast, "gsea_go_bp.tsv"),
              file.path(out_contrast, "gsea_go_bp_dotplot.png"),
              top_terms
            )
            ok_any <- ok_any || fg_ok
          } else {
            method_errors <- c(method_errors, "GSEA: no enriched terms")
          }
        }
      }
    }, error = function(e) {
      had_error <<- TRUE
      method_errors <<- c(method_errors, paste0("GSEA: ", conditionMessage(e)))
    })
  }

  if (ok_any) {
    payload <- status_payload(
      ok = TRUE,
      skipped = FALSE,
      reason = "ok",
      inputs = payload_base$inputs,
      config = payload_base$config,
      versions = payload_base$versions
    )
    write_status(status_path, payload)
  } else {
    reason <- if (length(method_errors) > 0) paste(method_errors, collapse = "; ") else "no results"
    payload <- status_payload(
      ok = FALSE,
      skipped = !had_error,
      reason = reason,
      inputs = payload_base$inputs,
      config = payload_base$config,
      versions = payload_base$versions
    )
    write_status(status_path, payload)
  }
}

file.create(snakemake@output[["done"]])
