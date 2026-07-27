import base64
import json
import os


with open(snakemake.input["status"], "r", encoding="utf-8") as handle:
    status = json.load(handle)

outputs = snakemake.output
os.makedirs(os.path.dirname(outputs["summary_tsv"]), exist_ok=True)

summary = {
    "analysis_mode": status["mode"],
    "reason_code": status["reason_code"],
    "condition_counts": json.dumps(status["condition_counts"], sort_keys=True),
    "total_samples": status["total_samples"],
    "differential_results_available": status["differential_results_available"],
    "normalized_counts_available": status["normalized_counts_available"],
    "pca_available": status["pca_available"],
    "sample_distance_available": status["sample_distance_available"],
    "inferential_qc_plots_available": status["inferential_qc_plots_available"],
}
with open(outputs["summary_tsv"], "w", encoding="utf-8") as handle:
    handle.write("metric\tvalue\n")
    for key, value in summary.items():
        handle.write(f"{key}\t{str(value).lower() if isinstance(value, bool) else value}\n")

with open(outputs["summary_json"], "w", encoding="utf-8") as handle:
    json.dump(summary, handle, indent=2, sort_keys=True)
    handle.write("\n")

png_bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFElEQVQoU2NkYGD4z0AE"
    "YBxVSF8AAFwAAy/6F2wAAAAASUVORK5CYII="
)
for key in ("padj_hist", "lfc_hist", "mean_vs_lfc", "volcano"):
    with open(outputs[key], "wb") as handle:
        handle.write(png_bytes)
