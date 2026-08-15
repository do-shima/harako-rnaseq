import os
import json
from html import escape
from datetime import datetime

status_file = snakemake.input["status"]
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

with open(status_file, "r", encoding="utf-8") as handle:
    status = json.load(handle)

counts_text = ", ".join(
    f"{key}={value}" for key, value in status.get("condition_counts", {}).items()
) or "none"
is_qc_only = status.get("mode") == "qc_only"
reason_code = str(status.get("reason_code", "unknown"))
reason_text = {
    "eligible": "Minimum sample-count requirements were met",
    "single_condition": "Only one condition was provided",
    "insufficient_replicates": "At least one condition did not meet the minimum sample-count requirements",
    "unknown": "The reason is unavailable",
}.get(reason_code, "An unrecognized reason was reported")
reason_display = f"{reason_text} ({reason_code})"
analysis_banner = (
    "<div class=\"qc-only\"><strong>QC-only analysis:</strong> "
    "differential expression analysis was not performed.</div>"
    if is_qc_only
    else "<div class=\"differential\">Differential expression analysis</div>"
)

provenance = snakemake.config.get("reference_provenance") or {}
verified_value = provenance.get("checksum_verified")
verification_status = (
    "unknown" if verified_value is None
    else ("verified" if verified_value is True else "unverified")
)
reference_hashes = provenance.get("checksums") or {}
reference_fields = [
    ("Provider", provenance.get("provider", "unknown")),
    ("Species", provenance.get("species", snakemake.config.get("species", "unknown"))),
    ("Assembly", provenance.get("assembly", "unknown")),
    ("Annotation release", provenance.get("annotation_release", "unknown")),
    ("Manifest release", provenance.get("manifest_release", snakemake.config.get("ref_release", "unknown"))),
    ("Canonical preset", provenance.get("canonical_preset", snakemake.config.get("ref_preset", "unknown"))),
    ("Verification status", verification_status),
    (
        "Checksums",
        "; ".join(
            f"{key}={str(reference_hashes.get(key, 'unknown'))[:12]}..."
            if reference_hashes.get(key)
            else f"{key}=unknown"
            for key in ("transcripts_fasta", "genome_fasta", "gtf")
        ),
    ),
]
reference_html = "".join(
    f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
    for label, value in reference_fields
)
protocol_warning = status.get("scientific_warning")
full_hash_text = "\n".join(
    f"{key}: {reference_hashes.get(key, 'unknown')}"
    for key in ("transcripts_fasta", "genome_fasta", "gtf")
)

html = "\n".join([
    "<!doctype html>",
    "<html lang=\"en\">",
    "<head>",
    "  <meta charset=\"utf-8\">",
    "  <title>RNA-seq Report</title>",
    "  <style>",
    "    body { font-family: Arial, sans-serif; margin: 24px; }",
    "    h1 { margin-bottom: 4px; }",
    "    .meta { color: #555; margin-bottom: 16px; }",
    "    pre { background: #f5f5f5; padding: 12px; }",
    "    th { text-align: left; padding-right: 16px; }",
    "    .ref-status { padding: 8px 12px; border-left: 4px solid; margin: 12px 0; }",
    "    .verified { background: #e7f5ec; color: #1f6b3a; }",
    "    .unverified { background: #fff4d6; color: #7a5200; }",
    "    .unknown { background: #eeeeee; color: #444444; }",
    "    .qc-only { background: #eef6fb; border-left: 4px solid #2878a5; padding: 12px; margin: 16px 0; }",
    "    .differential { background: #e7f5ec; border-left: 4px solid #2f7d4d; padding: 12px; margin: 16px 0; }",
    "  </style>",
    "</head>",
    "<body>",
    "  <h1>RNA-seq Report</h1>",
    f"  <div class=\"meta\">Generated: {datetime.utcnow().isoformat()}Z</div>",
    "  <p>Static HTML report (Quarto-ready placeholder).</p>",
    "  <h2>Analysis plan</h2>",
    f"  {analysis_banner}",
    "  <table>",
    f"    <tr><th>Analysis mode</th><td>{escape(str(status.get('mode', 'unknown')))}</td></tr>",
    f"    <tr><th>Reason</th><td>{escape(reason_display)}</td></tr>",
    f"    <tr><th>Condition counts</th><td>{escape(counts_text)}</td></tr>",
    f"    <tr><th>Total samples</th><td>{escape(str(status.get('total_samples', 'unknown')))}</td></tr>",
    f"    <tr><th>Library protocol</th><td>{escape(str(status.get('library_protocol', 'legacy_unspecified')))}</td></tr>",
    f"    <tr><th>tximport handoff</th><td>{escape(str(status.get('tximport_handoff_method', 'historical_counts_matrix_without_length_offset')))}</td></tr>",
    f"    <tr><th>Effective-length correction used</th><td>{'yes' if status.get('length_offset_used') else 'no'}</td></tr>",
    f"    <tr><th>Differential results available</th><td>{'yes' if status.get('differential_results_available') else 'no'}</td></tr>",
    "  </table>",
    f"  <p><strong>Scientific warning:</strong> {escape(str(protocol_warning))}</p>" if protocol_warning else "",
    "  <h2>Differential expression</h2>",
    (
        "  <p>Not applicable: differential expression analysis was not performed.</p>"
        if is_qc_only
        else "  <p>Stub differential outputs are placeholders and are not scientific results.</p>"
    ),
    "  <h2>Enrichment</h2>",
    (
        "  <p>Not applicable: differential expression results are unavailable, so enrichment was not run.</p>"
        if is_qc_only
        else "  <p>Enrichment was disabled, or its status file was not found.</p>"
    ),
    "  <h2>Reference provenance</h2>",
    f"  <div class=\"ref-status {verification_status}\">Reference verification: {verification_status}</div>",
    f"  <table>{reference_html}</table>",
    "  <details><summary>Full reference checksums</summary>",
    f"  <pre>{escape(full_hash_text)}</pre></details>",
    "</body>",
    "</html>",
])

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write(html)
