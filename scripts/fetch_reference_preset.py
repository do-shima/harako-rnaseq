import argparse
import hashlib
import json
import os
import sys
import urllib.request


def _load_simple_yaml(path):
    root = {}
    stack = [(0, root)]

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.split("#", 1)[0].rstrip("\n")
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            key, sep, value = line.strip().partition(":")
            if not sep:
                continue

            while stack and indent < stack[-1][0]:
                stack.pop()
            if not stack:
                raise ValueError(f"Invalid indentation in {path}")

            current = stack[-1][1]
            value = value.strip()
            if value == "":
                new_node = {}
                current[key] = new_node
                stack.append((indent + 2, new_node))
            else:
                if (value[0] == value[-1]) and value[0] in ("'", "\""):
                    value = value[1:-1]
                current[key] = value

    return root


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url, dest_path):
    tmp_path = dest_path + ".tmp"
    with urllib.request.urlopen(url) as response, open(tmp_path, "wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    os.replace(tmp_path, dest_path)


def _resolve_manifest(manifest, preset, release):
    presets = manifest.get("presets", {})
    if preset not in presets:
        raise ValueError(f"Preset not found: {preset}")

    preset_data = presets[preset]
    if release not in preset_data:
        raise ValueError(f"Release not found for {preset}: {release}")

    release_data = preset_data[release]
    sha_map = release_data.get("sha256", {}) if isinstance(release_data, dict) else {}

    urls = {
        "transcripts_fasta_url": release_data.get("transcripts_fasta_url"),
        "genome_fasta_url": release_data.get("genome_fasta_url"),
        "gtf_url": release_data.get("gtf_url"),
    }
    if not all(urls.values()):
        raise ValueError(f"Missing URL(s) for {preset} {release}")

    checksums = {
        "transcripts_fasta_url": sha_map.get("transcripts_fasta_url") or None,
        "genome_fasta_url": sha_map.get("genome_fasta_url") or None,
        "gtf_url": sha_map.get("gtf_url") or None,
    }
    return urls, checksums


def _ensure_file(url, checksum, dest_path):
    if os.path.exists(dest_path):
        if checksum:
            existing = _sha256(dest_path)
            if existing.lower() == checksum.lower():
                return
        else:
            return

    _download(url, dest_path)

    if checksum:
        actual = _sha256(dest_path)
        if actual.lower() != checksum.lower():
            raise ValueError(f"Checksum mismatch for {dest_path}")


def main():
    parser = argparse.ArgumentParser(description="Fetch reference preset into a local cache.")
    parser.add_argument("--preset", required=True, help="Preset name")
    parser.add_argument("--release", required=True, help="Release name (e.g. pinned or latest)")
    parser.add_argument("--cache-dir", required=True, help="Cache directory")
    parser.add_argument("--out-json", help="Optional output JSON path")
    parser.add_argument(
        "--manifest",
        default=os.path.join(os.path.dirname(__file__), os.pardir, "workflow", "ref_manifest.yaml"),
        help="Path to reference manifest YAML",
    )
    args = parser.parse_args()

    manifest = _load_simple_yaml(args.manifest)
    urls, checksums = _resolve_manifest(manifest, args.preset, args.release)

    target_dir = os.path.join(args.cache_dir, args.preset, args.release)
    os.makedirs(target_dir, exist_ok=True)

    targets = {
        "transcripts_fasta": (urls["transcripts_fasta_url"], checksums["transcripts_fasta_url"], "transcripts.fa.gz"),
        "genome_fasta": (urls["genome_fasta_url"], checksums["genome_fasta_url"], "genome.fa.gz"),
        "gtf": (urls["gtf_url"], checksums["gtf_url"], "annotation.gtf.gz"),
    }

    resolved = {}
    for key, (url, checksum, filename) in targets.items():
        dest_path = os.path.join(target_dir, filename)
        _ensure_file(url, checksum, dest_path)
        resolved[key] = os.path.abspath(dest_path)

    payload = json.dumps(resolved, indent=2)
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()
