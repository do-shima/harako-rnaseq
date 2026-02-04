import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

USER_AGENT = "rnaseq-pipeline-ref-fetcher/1.0"


class DownloadError(RuntimeError):
    def __init__(self, message, had_http_403=False):
        super().__init__(message)
        self.had_http_403 = bool(had_http_403)


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
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(request) as response, open(tmp_path, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        os.replace(tmp_path, dest_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _as_https(url):
    if isinstance(url, str) and url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return ""


def _dedupe(items):
    out = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _parse_mirror_urls(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    # Accept JSON list string when manifest parser preserves quoted values.
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
    return [part.strip() for part in re.split(r"[,|;\s]+", text) if part.strip()]


def _manual_hint(dest_path):
    return (
        f"Manual fallback: download and place the file at {dest_path}. "
        "For UI use, place refs under /input/refs and switch to custom refs mode."
    )


def _download_with_fallback(primary_url, mirror_urls, dest_path):
    attempted = []
    had_http_403 = False
    had_http_404 = False
    tried_urls = set()
    queue = [primary_url] + list(mirror_urls or [])
    for url in _dedupe(queue):
        tried_urls.add(url)
        try:
            _download(url, dest_path)
            return
        except urllib.error.HTTPError as exc:
            attempted.append(f"{url} -> HTTP {exc.code}")
            if int(exc.code) == 403:
                had_http_403 = True
            if int(exc.code) == 404:
                had_http_404 = True
            if int(exc.code) == 403:
                https_url = _as_https(url)
                if https_url and https_url not in tried_urls:
                    tried_urls.add(https_url)
                    try:
                        _download(https_url, dest_path)
                        return
                    except urllib.error.HTTPError as https_exc:
                        attempted.append(f"{https_url} -> HTTP {https_exc.code}")
                        if int(https_exc.code) == 403:
                            had_http_403 = True
                    except Exception as https_exc:
                        attempted.append(f"{https_url} -> {https_exc.__class__.__name__}: {https_exc}")
        except Exception as exc:
            attempted.append(f"{url} -> {exc.__class__.__name__}: {exc}")

    lines = [f"Failed to download reference file: {dest_path}", "Tried URLs:"]
    if attempted:
        lines.extend([f"- {item}" for item in attempted])
    else:
        lines.append("- (none)")
    if had_http_404:
        lines.append("At least one URL returned HTTP 404 (file not found). Check manifest release/file names.")
    lines.append(_manual_hint(dest_path))
    raise DownloadError("\n".join(lines), had_http_403=had_http_403)


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
    mirror_block = release_data.get("mirror_urls", {}) if isinstance(release_data, dict) else {}
    mirrors = {
        "transcripts_fasta_url": _dedupe(
            _parse_mirror_urls(release_data.get("transcripts_fasta_url_mirror_urls"))
            + _parse_mirror_urls(release_data.get("transcripts_fasta_mirror_urls"))
            + _parse_mirror_urls(mirror_block.get("transcripts_fasta_url") if isinstance(mirror_block, dict) else None)
            + _parse_mirror_urls(mirror_block.get("transcripts_fasta") if isinstance(mirror_block, dict) else None)
        ),
        "genome_fasta_url": _dedupe(
            _parse_mirror_urls(release_data.get("genome_fasta_url_mirror_urls"))
            + _parse_mirror_urls(release_data.get("genome_fasta_mirror_urls"))
            + _parse_mirror_urls(mirror_block.get("genome_fasta_url") if isinstance(mirror_block, dict) else None)
            + _parse_mirror_urls(mirror_block.get("genome_fasta") if isinstance(mirror_block, dict) else None)
        ),
        "gtf_url": _dedupe(
            _parse_mirror_urls(release_data.get("gtf_url_mirror_urls"))
            + _parse_mirror_urls(release_data.get("gtf_mirror_urls"))
            + _parse_mirror_urls(mirror_block.get("gtf_url") if isinstance(mirror_block, dict) else None)
            + _parse_mirror_urls(mirror_block.get("gtf") if isinstance(mirror_block, dict) else None)
        ),
    }
    return urls, checksums, mirrors


def _ensure_file(url, mirror_urls, checksum, dest_path):
    if os.path.exists(dest_path):
        if checksum:
            existing = _sha256(dest_path)
            if existing.lower() == checksum.lower():
                return
        else:
            existing = _sha256(dest_path)
            sys.stderr.write(
                f"WARNING: checksum is not pinned for {dest_path}. "
                f"Existing file sha256={existing}. Please pin this in manifest.\n"
            )
            return

    _download_with_fallback(url, mirror_urls, dest_path)

    if checksum:
        actual = _sha256(dest_path)
        if actual.lower() != checksum.lower():
            raise ValueError(f"Checksum mismatch for {dest_path}. {_manual_hint(dest_path)}")
    else:
        actual = _sha256(dest_path)
        sys.stderr.write(
            f"WARNING: checksum is not pinned for {dest_path}. "
            f"Downloaded sha256={actual}. Please pin this in manifest.\n"
        )


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
    urls, checksums, mirrors = _resolve_manifest(manifest, args.preset, args.release)

    target_dir = os.path.join(args.cache_dir, args.preset, args.release)
    os.makedirs(target_dir, exist_ok=True)

    targets = {
        "transcripts_fasta": (
            urls["transcripts_fasta_url"],
            mirrors["transcripts_fasta_url"],
            checksums["transcripts_fasta_url"],
            "transcripts.fa.gz",
        ),
        "genome_fasta": (
            urls["genome_fasta_url"],
            mirrors["genome_fasta_url"],
            checksums["genome_fasta_url"],
            "genome.fa.gz",
        ),
        "gtf": (
            urls["gtf_url"],
            mirrors["gtf_url"],
            checksums["gtf_url"],
            "annotation.gtf.gz",
        ),
    }

    resolved = {}
    for key, (url, mirror_urls, checksum, filename) in targets.items():
        dest_path = os.path.join(target_dir, filename)
        _ensure_file(url, mirror_urls, checksum, dest_path)
        resolved[key] = os.path.abspath(dest_path)

    payload = json.dumps(resolved, indent=2)
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DownloadError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(43 if exc.had_http_403 else 1)
    except Exception as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1)
