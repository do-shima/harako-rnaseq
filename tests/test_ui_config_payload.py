from app.ui.config_builder import build_config_payload


def _build_payload(**kwargs):
    defaults = {
        "engine": "real",
        "species": "mouse",
        "samples": ["s1"],
        "input_root": "/input",
        "output_root": "/output",
        "sample_table": "/output/metadata/samples.tsv",
        "threads": 1,
        "ref_mode": "preset_cache",
        "ref_block": {},
        "ref_preset": "mouse_gencode",
        "ref_release": "pinned",
        "ref_cache_dir": "/output/refs_cache",
        "use_custom_refs": False,
        "contrast_mode": "",
        "contrast_ref": "",
        "contrast_pairs": [],
        "contrasts": [],
        "enrichment": None,
    }
    defaults.update(kwargs)
    return build_config_payload(**defaults)


def main():
    rat_payload = _build_payload(species="rat", ref_preset="rat_ensembl")
    if rat_payload.get("species") != "rat":
        raise SystemExit(f"species should be rat, got: {rat_payload.get('species')}")
    if rat_payload.get("ref_preset") != "rat_ensembl":
        raise SystemExit(f"ref_preset should be rat_ensembl, got: {rat_payload.get('ref_preset')}")
    if "ref" in rat_payload:
        raise SystemExit("ref should not be present when ref_preset is used")

    manual_payload = _build_payload(
        species="human",
        ref_mode="fasta_gtf",
        ref_preset="",
        ref_release="",
        ref_cache_dir="",
        ref_block={
            "transcripts_fasta": "refs/human/transcripts.fa.gz",
            "genome_fasta": "refs/human/genome.fa.gz",
            "gtf": "refs/human/annotation.gtf.gz",
        },
        use_custom_refs=True,
    )
    ref_block = manual_payload.get("ref", {}).get("human", {})
    if not ref_block:
        raise SystemExit("manual ref block should be nested under species")
    if ref_block.get("transcripts_fasta") != "refs/human/transcripts.fa.gz":
        raise SystemExit("manual ref transcripts_fasta missing or incorrect")


if __name__ == "__main__":
    main()
