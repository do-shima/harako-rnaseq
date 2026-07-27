import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.reference_presets import (  # noqa: E402
    get_release_entry,
    iter_cache_candidates,
    resolve_existing_cache_paths,
    validate_builtin_manifest,
)

USER_AGENT = "rnaseq-pipeline-ref-fetcher/1.0"


class DownloadError(RuntimeError):
    def __init__(self, message, had_http_403=False, had_http_404=False):
        super().__init__(message)
        self.had_http_403 = bool(had_http_403)
        self.had_http_404 = bool(had_http_404)


def _load_simple_yaml(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _emit(progress, payload):
    if not progress:
        return
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _download(url, dest_path, progress=False, label=None):
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
            total = response.headers.get("Content-Length")
            total_val = int(total) if total and total.isdigit() else None
            file_name = label or os.path.basename(dest_path)
            _emit(progress, {"event": "start", "file": file_name, "url": url, "total": total_val})
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                pct = (downloaded / total_val * 100.0) if total_val else None
                _emit(
                    progress,
                    {
                        "event": "chunk",
                        "file": file_name,
                        "bytes": len(chunk),
                        "downloaded": downloaded,
                        "total": total_val,
                        "pct": pct,
                    },
                )
        os.replace(tmp_path, dest_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _cleanup_file(path):
    if os.path.exists(path):
        try:
            os.unlink(path)
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


def _download_with_fallback(primary_url, mirror_urls, dest_path, progress=False, label=None):
    attempted = []
    had_http_403 = False
    had_http_404 = False
    tried_urls = set()
    queue = [primary_url] + list(mirror_urls or [])
    for url in _dedupe(queue):
        tried_urls.add(url)
        try:
            _download(url, dest_path, progress=progress, label=label)
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
                        _download(https_url, dest_path, progress=progress, label=label)
                        return
                    except urllib.error.HTTPError as https_exc:
                        attempted.append(f"{https_url} -> HTTP {https_exc.code}")
                        if int(https_exc.code) == 403:
                            had_http_403 = True
                    except Exception as https_exc:
                        attempted.append(f"{https_url} -> {https_exc.__class__.__name__}: {https_exc}")
        except Exception as exc:
            attempted.append(f"{url} -> {exc.__class__.__name__}: {exc}")

    reason = "Download failed: URL unreachable. Check the URL or proxy settings."
    if had_http_403 or had_http_404:
        reason = "Download failed: URL unreachable (403/404). Check the URL or proxy settings."
    lines = [reason, f"Target: {dest_path}", "Tried URLs:"]
    if attempted:
        lines.extend([f"- {item}" for item in attempted])
    else:
        lines.append("- (none)")
    if had_http_404:
        lines.append("At least one URL returned HTTP 404 (file not found). Check preset/release mapping.")
    lines.append(_manual_hint(dest_path))
    raise DownloadError("\n".join(lines), had_http_403=had_http_403, had_http_404=had_http_404)


def _resolve_manifest(manifest, preset, release):
    _, _, release_data = get_release_entry(manifest, preset, release)
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


def _validate_gzip(path):
    try:
        with gzip.open(path, "rb") as handle:
            for _ in iter(lambda: handle.read(1024 * 1024), b""):
                pass
        return True
    except Exception:
        return False


def _validate_gtf_header(path):
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                return len(stripped.split("\t")) == 9
    except Exception:
        return False
    return False


def _validate_fasta_header(path):
    try:
        opener = gzip.open if path.lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            return any(line.startswith(">") and len(line.strip()) > 1 for line in handle)
    except Exception:
        return False


def _validate_file(dest_path, require_gtf_columns=False, require_fasta_header=False):
    if not os.path.exists(dest_path):
        raise DownloadError("Downloaded file is missing. Retry download.")

    size = os.path.getsize(dest_path)
    if size <= 0:
        raise DownloadError("File saved but size is 0. Disk quota / permission / interrupted download.")

    if dest_path.lower().endswith(".gz") and not _validate_gzip(dest_path):
        raise DownloadError("Downloaded file is corrupted (gzip test failed). Retry download.")

    if require_gtf_columns and not _validate_gtf_header(dest_path):
        raise DownloadError("Downloaded GTF looks invalid (expected tab-delimited 9 columns). Check preset/release.")
    if require_fasta_header and not _validate_fasta_header(dest_path):
        raise DownloadError("Downloaded FASTA looks invalid (expected at least one header). Check preset/release.")


def _ensure_file(
    url,
    mirror_urls,
    checksum,
    dest_path,
    progress=False,
    label=None,
    overwrite=False,
    require_gtf_columns=False,
    require_fasta_header=False,
):
    file_name = label or os.path.basename(dest_path)
    if overwrite:
        _cleanup_file(dest_path)

    if os.path.exists(dest_path):
        try:
            _validate_file(
                dest_path,
                require_gtf_columns=require_gtf_columns,
                require_fasta_header=require_fasta_header,
            )
            existing = _sha256(dest_path)
            if checksum and existing.lower() != checksum.lower():
                raise DownloadError(f"Checksum mismatch for existing file: {dest_path}. Re-download required.")
            if not checksum:
                sys.stderr.write(
                    f"WARNING: checksum is not pinned for {dest_path}. "
                    f"Existing file sha256={existing}. Please pin this in manifest.\n"
                )
            _emit(progress, {"event": "done", "file": file_name, "dest": dest_path, "sha256": existing, "skipped": True})
            return
        except DownloadError as exc:
            sys.stderr.write(f"Existing file invalid; retrying download: {dest_path} ({exc})\n")
            _cleanup_file(dest_path)

    try:
        staged_path = dest_path + ".download.gz"
        _cleanup_file(staged_path)
        _download_with_fallback(url, mirror_urls, staged_path, progress=progress, label=file_name)
        _validate_file(
            staged_path,
            require_gtf_columns=require_gtf_columns,
            require_fasta_header=require_fasta_header,
        )
        actual = _sha256(staged_path)
        if checksum and actual.lower() != checksum.lower():
            raise DownloadError(f"Checksum mismatch for {dest_path}. {_manual_hint(dest_path)}")
        if not checksum:
            sys.stderr.write(
                f"WARNING: checksum is not pinned for {dest_path}. "
                f"Downloaded sha256={actual}. Please pin this in manifest.\n"
            )
        os.replace(staged_path, dest_path)
        _emit(progress, {"event": "done", "file": file_name, "dest": dest_path, "sha256": actual, "skipped": False})
    except Exception as exc:
        _cleanup_file(dest_path)
        _cleanup_file(dest_path + ".download.gz")
        if isinstance(exc, DownloadError):
            raise
        raise DownloadError(str(exc))


def _remove_invalid_cached_files(manifest, cache_dir, preset, release, checksums):
    filenames = {
        "transcripts_fasta_url": ("transcripts.fa.gz", False, True),
        "genome_fasta_url": ("genome.fa.gz", False, True),
        "gtf_url": ("annotation.gtf.gz", True, False),
    }
    for candidate in iter_cache_candidates(
        manifest, Path(cache_dir), preset, release
    ):
        for key, (filename, is_gtf, is_fasta) in filenames.items():
            path = Path(candidate["directory"]) / filename
            if not path.exists():
                continue
            try:
                _validate_file(
                    str(path),
                    require_gtf_columns=is_gtf,
                    require_fasta_header=is_fasta,
                )
                expected = checksums.get(key)
                if expected and _sha256(str(path)).lower() != expected.lower():
                    raise DownloadError(f"Checksum mismatch for cached file: {path}")
            except DownloadError as exc:
                sys.stderr.write(f"Deleting invalid cached file: {path} ({exc})\n")
                _cleanup_file(str(path))


def main():
    parser = argparse.ArgumentParser(description="Fetch reference preset into a local cache.")
    parser.add_argument("--preset", required=True, help="Preset name")
    parser.add_argument("--release", required=True, help="Release name (e.g. pinned or release-113)")
    parser.add_argument("--cache-dir", required=True, help="Cache directory")
    parser.add_argument("--overwrite", action="store_true", help="Re-download even when files already exist")
    parser.add_argument("--out-json", help="Optional output JSON path")
    parser.add_argument("--progress-jsonl", action="store_true", help="Emit JSONL progress events to stdout")
    parser.add_argument(
        "--manifest",
        default=os.path.join(os.path.dirname(__file__), os.pardir, "workflow", "ref_manifest.yaml"),
        help="Path to reference manifest YAML",
    )
    args = parser.parse_args()

    manifest = _load_simple_yaml(args.manifest)
    validate_builtin_manifest(manifest)
    canonical, canonical_release, _ = get_release_entry(
        manifest, args.preset, args.release
    )
    urls, checksums, mirrors = _resolve_manifest(manifest, args.preset, args.release)
    _remove_invalid_cached_files(
        manifest, args.cache_dir, args.preset, args.release, checksums
    )
    existing = resolve_existing_cache_paths(
        manifest, Path(args.cache_dir), args.preset, args.release
    )
    target_dir = (
        str(existing["directory"])
        if existing
        else os.path.join(args.cache_dir, canonical, canonical_release)
    )
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
        label = {
            "transcripts_fasta": "transcripts",
            "genome_fasta": "genome",
            "gtf": "gtf",
        }.get(key, key)
        _ensure_file(
            url,
            mirror_urls,
            checksum,
            dest_path,
            progress=args.progress_jsonl,
            label=label,
            overwrite=args.overwrite,
            require_gtf_columns=(key == "gtf"),
            require_fasta_header=(key != "gtf"),
        )
        resolved[key] = os.path.abspath(dest_path)

    payload = json.dumps(resolved, indent=2)
    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        if args.progress_jsonl:
            _emit(True, {"event": "result", "payload": resolved})
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
