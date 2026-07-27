import base64
import json
import os


RESULT_COLUMNS = [
    "contrast",
    "gene_id",
    "baseMean",
    "log2FoldChange",
    "lfcSE",
    "stat",
    "pvalue",
    "padj",
]
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFElEQVQoU2NkYGD4z0AE"
    "YBxVSF8AAFwAAy/6F2wAAAAASUVORK5CYII="
)

plan = dict(snakemake.params["analysis_plan"])
outputs = snakemake.output
os.makedirs(os.path.dirname(outputs["results"]), exist_ok=True)

with open(outputs["results"], "w", encoding="utf-8") as handle:
    handle.write("\t".join(RESULT_COLUMNS) + "\n")
    if plan["mode"] == "differential":
        handle.write("B_vs_A\tgeneA\t10\t1.0\t0.2\t5.0\t0.001\t0.01\n")
        handle.write("B_vs_A\tgeneB\t8\t-0.5\t0.3\t-1.67\t0.1\t0.2\n")

samples = list(snakemake.config.get("samples") or [])
with open(outputs["normalized"], "w", encoding="utf-8") as handle:
    handle.write("\t".join(["gene_id", *samples]) + "\n")
    handle.write("\t".join(["geneA", *(["10"] * len(samples))]) + "\n")
    handle.write("\t".join(["geneB", *(["8"] * len(samples))]) + "\n")

for key in ("pca", "heatmap", "ma"):
    with open(outputs[key], "wb") as handle:
        handle.write(PNG_BYTES)

multiple_samples = plan["total_samples"] >= 2
differential = plan["mode"] == "differential"
status = {
    "schema_version": 1,
    "policy_version": plan["policy_version"],
    "mode": plan["mode"],
    "structurally_valid": True,
    "eligible_for_de": plan["eligible_for_de"],
    "reason_code": plan["reason_code"],
    "condition_counts": plan["condition_counts"],
    "total_samples": plan["total_samples"],
    "differential_results_available": differential,
    "normalized_counts_available": True,
    "pca_available": multiple_samples,
    "sample_distance_available": multiple_samples,
    "ma_plot_available": differential,
    "inferential_qc_plots_available": differential,
    "enrichment_allowed": plan["enrichment_allowed"] and differential,
    "warnings": ["Stub outputs are placeholders and are not scientific results."],
}
with open(outputs["status"], "w", encoding="utf-8") as handle:
    json.dump(status, handle, indent=2, sort_keys=True)
    handle.write("\n")
