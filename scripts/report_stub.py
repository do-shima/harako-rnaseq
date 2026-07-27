import os
from html import escape
from datetime import datetime

input_file = snakemake.input["results"]
output_file = snakemake.output[0]

os.makedirs(os.path.dirname(output_file), exist_ok=True)

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
    "  </style>",
    "</head>",
    "<body>",
    "  <h1>RNA-seq Report</h1>",
    f"  <div class=\"meta\">Generated: {datetime.utcnow().isoformat()}Z</div>",
    "  <p>Static HTML report (Quarto-ready placeholder).</p>",
    "  <h2>Reference provenance</h2>",
    f"  <div class=\"ref-status {verification_status}\">Reference verification: {verification_status}</div>",
    f"  <table>{reference_html}</table>",
    "  <details><summary>Full reference checksums</summary>",
    f"  <pre>{escape(full_hash_text)}</pre></details>",
    f"  <pre>Input: {input_file}</pre>",
    "</body>",
    "</html>",
])

with open(output_file, "w", encoding="utf-8") as handle:
    handle.write(html)
