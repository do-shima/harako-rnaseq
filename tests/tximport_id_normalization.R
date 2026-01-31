suppressPackageStartupMessages({
  library(testthat)
})

strip_after_bar <- function(x) {
  x <- as.character(x)
  parts <- strsplit(x, "|", fixed = TRUE)
  vapply(parts, function(p) if (length(p) >= 1) p[[1]] else "", character(1))
}
strip_version <- function(x) sub("\\..*$", "", x)
has_version <- function(x) any(grepl("\\.[0-9]+$", x))

test_that("bar stripping keeps transcript IDs", {
  ids <- c("ENSMUST000001.2|ENSMUSG000001|foo", "ENSMUST000002.1|bar")
  expect_equal(strip_after_bar(ids), c("ENSMUST000001.2", "ENSMUST000002.1"))
})

test_that("version presence detection", {
  expect_true(has_version(c("ENSMUST000001.2", "ENSMUST000002.1")))
  expect_false(has_version(c("ENSMUST000001", "ENSMUST000002")))
})

test_that("strip version applies to both sides on mismatch", {
  quant_ids <- c("ENSMUST000001", "ENSMUST000002")
  tx_ids <- c("ENSMUST000001.2", "ENSMUST000002.1")
  q_has <- has_version(quant_ids)
  t_has <- has_version(tx_ids)
  expect_true(q_has != t_has)
  expect_equal(strip_version(quant_ids), c("ENSMUST000001", "ENSMUST000002"))
  expect_equal(strip_version(tx_ids), c("ENSMUST000001", "ENSMUST000002"))
})
