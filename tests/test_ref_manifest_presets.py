from pathlib import Path

import yaml


EXPECTED = {
    "rat_ensembl": {
        "genome_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/rattus_norvegicus/dna/Rattus_norvegicus.mRatBN7.2.dna.primary_assembly.fa.gz",
        "transcripts_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/rattus_norvegicus/cdna/Rattus_norvegicus.mRatBN7.2.cdna.all.fa.gz",
        "gtf_url": "https://ftp.ensembl.org/pub/release-113/gtf/rattus_norvegicus/Rattus_norvegicus.mRatBN7.2.113.gtf.gz",
    },
    "mouse_gencode": {
        "genome_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/mus_musculus/dna/Mus_musculus.GRCm39.dna.primary_assembly.fa.gz",
        "transcripts_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/mus_musculus/cdna/Mus_musculus.GRCm39.cdna.all.fa.gz",
        "gtf_url": "https://ftp.ensembl.org/pub/release-113/gtf/mus_musculus/Mus_musculus.GRCm39.113.gtf.gz",
    },
    "human_gencode": {
        "genome_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/homo_sapiens/dna/Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz",
        "transcripts_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/homo_sapiens/cdna/Homo_sapiens.GRCh38.cdna.all.fa.gz",
        "gtf_url": "https://ftp.ensembl.org/pub/release-113/gtf/homo_sapiens/Homo_sapiens.GRCh38.113.gtf.gz",
    },
    "mouse_gencode_mm10": {
        "genome_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/mus_musculus/dna/Mus_musculus.GRCm38.dna.primary_assembly.fa.gz",
        "transcripts_fasta_url": "https://ftp.ensembl.org/pub/release-113/fasta/mus_musculus/cdna/Mus_musculus.GRCm38.cdna.all.fa.gz",
        "gtf_url": "https://ftp.ensembl.org/pub/release-113/gtf/mus_musculus/Mus_musculus.GRCm38.113.gtf.gz",
    },
}


def _load_manifest():
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "workflow" / "ref_manifest.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def main():
    manifest = _load_manifest()
    presets = manifest.get("presets") or {}

    for preset, expected_urls in EXPECTED.items():
        if preset not in presets:
            raise SystemExit(f"Missing preset in manifest: {preset}")
        for release in ("pinned", "release-113"):
            if release not in presets[preset]:
                raise SystemExit(f"Missing release in manifest: {preset}/{release}")
            block = presets[preset][release] or {}
            for key, expected in expected_urls.items():
                actual = (block.get(key) or "").strip()
                if actual != expected:
                    raise SystemExit(
                        f"Unexpected URL for {preset}/{release}/{key}\nexpected={expected}\nactual={actual}"
                    )


if __name__ == "__main__":
    main()
