#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import urllib.error
from urllib.parse import urlparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.reference_presets import (  # noqa: E402
    REFERENCE_FILES,
    file_sha256,
    get_release_entry,
    iter_cache_candidates,
    resolve_preset_id,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_SAFETY_MARGIN = 0.20


def validate_reference_file(
    path: Path,
    kind: str,
    *,
    expected_assembly: str = "",
) -> dict:
    if not path.is_file():
        raise ValueError(f"missing file: {path}")
    if path.stat().st_size <= 0:
        raise ValueError(f"empty file: {path}")
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    if path.name.lower().endswith(".gz"):
        try:
            with gzip.open(path, "rb") as handle:
                for _ in iter(lambda: handle.read(1024 * 1024), b""):
                    pass
        except Exception as exc:
            raise ValueError(f"invalid gzip: {path}: {exc}") from exc
    details = {"gzip_valid": True, "format_valid": False}
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            identity_probe = []
            if kind == "gtf_url":
                has_record = False
                has_transcript_attributes = False
                for line in handle:
                    if len(identity_probe) < 100:
                        identity_probe.append(line)
                    if not line.strip() or line.startswith("#"):
                        continue
                    fields = line.rstrip("\r\n").split("\t")
                    if len(fields) != 9:
                        continue
                    has_record = True
                    if (
                        fields[2] in {"transcript", "exon", "CDS"}
                        and 'gene_id "' in fields[8]
                        and 'transcript_id "' in fields[8]
                    ):
                        has_transcript_attributes = True
                        break
                if not has_record:
                    raise ValueError(f"invalid GTF (no 9-column record): {path}")
                if not has_transcript_attributes:
                    raise ValueError(
                        f"invalid GTF (no representative transcript record with "
                        f"gene_id and transcript_id): {path}"
                    )
                details["gtf_9_column_record"] = True
                details["gtf_transcript_attributes"] = True
            else:
                has_header = False
                has_sequence = False
                for line in handle:
                    if len(identity_probe) < 20:
                        identity_probe.append(line)
                    text = line.strip()
                    if not text:
                        continue
                    if text.startswith(">") and len(text) > 1:
                        has_header = True
                    elif has_header and re.fullmatch(r"[A-Za-z*.-]+", text):
                        has_sequence = True
                        break
                if not has_header:
                    raise ValueError(f"invalid FASTA (no header): {path}")
                if not has_sequence:
                    raise ValueError(f"invalid FASTA (no sequence data): {path}")
                details["fasta_header"] = True
                details["fasta_sequence"] = True
            if expected_assembly:
                detected = expected_assembly.lower() in "".join(identity_probe).lower()
                details["expected_assembly"] = expected_assembly
                details["assembly_detected"] = detected
                if not detected:
                    raise ValueError(
                        f"reference content does not identify expected assembly "
                        f"{expected_assembly}: {path}"
                    )
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"invalid reference file: {path}: {exc}") from exc
    digest = file_sha256(path)
    if not SHA256_RE.fullmatch(digest):
        raise ValueError(f"invalid calculated SHA256 for {path}: {digest}")
    details.update(
        {
            "format_valid": True,
            "size_bytes": path.stat().st_size,
            "sha256": digest,
        }
    )
    return details


def _request_preflight(url: str) -> dict:
    headers = {"User-Agent": "harako-reference-checksum-pinner/1.0"}
    response = None
    method = "HEAD"
    try:
        request = urllib.request.Request(url, headers=headers, method="HEAD")
        response = urllib.request.urlopen(request, timeout=60)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        if isinstance(exc, urllib.error.HTTPError) and exc.code not in {400, 403, 405, 501}:
            raise
        method = "GET-range"
        request = urllib.request.Request(
            url, headers={**headers, "Range": "bytes=0-0"}, method="GET"
        )
        response = urllib.request.urlopen(request, timeout=60)
    with response:
        status = int(getattr(response, "status", response.getcode()))
        final_url = response.geturl()
        content_range = response.headers.get("Content-Range", "")
        length = response.headers.get("Content-Length")
        if content_range and "/" in content_range:
            total = content_range.rsplit("/", 1)[1]
            length = total if total.isdigit() else length
        content_length = int(length) if length and str(length).isdigit() else None
        if method == "GET-range":
            response.read(1)
    expected_name = Path(urlparse(url).path).name
    final_name = Path(urlparse(final_url).path).name
    if final_name != expected_name:
        raise ValueError(
            f"unexpected redirect filename: expected {expected_name}, got {final_name}"
        )
    if status not in {200, 206}:
        raise ValueError(f"unexpected HTTP status {status} for {url}")
    return {
        "url": url,
        "final_url": final_url,
        "http_status": status,
        "method": method,
        "content_length": content_length,
        "filename": expected_name,
    }


def preflight_presets(
    manifest: dict,
    cache_dir: Path,
    presets: list[str],
    release: str,
    safety_margin: float = DEFAULT_SAFETY_MARGIN,
) -> dict:
    assets = []
    for preset in presets:
        canonical, canonical_release, release_entry = get_release_entry(
            manifest, preset, release
        )
        metadata = (manifest.get("preset_metadata") or {}).get(canonical, {})
        destination = cache_dir / canonical / canonical_release
        for key, filename in REFERENCE_FILES.items():
            url = str(release_entry[key])
            remote = _request_preflight(url)
            expected_remote_name = Path(urlparse(url).path).name
            identity_tokens = [
                str(metadata.get("assembly", "")),
                str(metadata.get("annotation_release", ""))
                if key == "gtf_url"
                else "",
            ]
            missing_tokens = [
                token
                for token in identity_tokens
                if token and token.lower() not in expected_remote_name.lower()
            ]
            if missing_tokens:
                raise ValueError(
                    f"manifest filename identity mismatch for {canonical}/{key}: "
                    + ", ".join(missing_tokens)
                )
            path = destination / filename
            state = "missing"
            if path.exists():
                try:
                    validation = validate_reference_file(
                        path, "gtf_url" if key == "gtf_url" else "fasta"
                    )
                    expected = (release_entry.get("sha256") or {}).get(key)
                    if expected and validation["sha256"] != str(expected).lower():
                        state = "checksum_mismatch"
                    else:
                        state = "valid" if expected else "valid_but_unpinned"
                except ValueError:
                    state = "invalid"
            assets.append(
                {
                    "canonical_preset": canonical,
                    "manifest_release": canonical_release,
                    "provider": metadata.get("provider", "unknown"),
                    "species": metadata.get("species", "unknown"),
                    "assembly": metadata.get("assembly", "unknown"),
                    "annotation_release": str(
                        metadata.get("annotation_release", "unknown")
                    ),
                    "kind": key,
                    "destination": str(path),
                    "state": state,
                    **remote,
                }
            )
    missing_lengths = [
        asset["content_length"]
        for asset in assets
        if asset["state"] == "missing" and asset["content_length"] is not None
    ]
    unknown_lengths = [
        asset for asset in assets
        if asset["state"] == "missing" and asset["content_length"] is None
    ]
    if unknown_lengths:
        raise ValueError(
            "Content-Length unavailable for missing assets: "
            + ", ".join(asset["url"] for asset in unknown_lengths)
        )
    final_bytes = sum(missing_lengths)
    concurrent_temp_bytes = max(missing_lengths, default=0)
    required_bytes = int(
        (final_bytes + concurrent_temp_bytes) * (1.0 + safety_margin)
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(cache_dir).free
    result = {
        "assets": assets,
        "disk": {
            "final_missing_bytes": final_bytes,
            "largest_temporary_bytes": concurrent_temp_bytes,
            "safety_margin_fraction": safety_margin,
            "required_bytes": required_bytes,
            "free_bytes": free_bytes,
            "sufficient": free_bytes >= required_bytes,
        },
    }
    if free_bytes < required_bytes:
        raise ValueError(
            f"insufficient disk space: required={required_bytes}, free={free_bytes}"
        )
    return result


def _download_atomic(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp.gz")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "harako-reference-checksum-pinner/1.0"}
        )
        with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle, 1024 * 1024)
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _parse_presets(values: list[str] | None, manifest: dict) -> list[str]:
    if not values:
        return sorted((manifest.get("presets") or {}).keys())
    result = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return list(dict.fromkeys(resolve_preset_id(manifest, value) for value in result))


def inspect_bundle(
    manifest: dict,
    cache_dir: Path,
    preset: str,
    release: str,
    *,
    download_missing: bool,
) -> dict:
    canonical, canonical_release, release_entry = get_release_entry(
        manifest, preset, release
    )
    metadata = (manifest.get("preset_metadata") or {}).get(canonical, {})
    selected = None
    staged_paths: dict[Path, Path] = {}
    candidates = list(iter_cache_candidates(manifest, cache_dir, preset, release))
    for candidate in candidates:
        if candidate.get("strict_checksum"):
            expected = release_entry.get("sha256", {})
            if not all(
                isinstance(expected.get(key), str) and SHA256_RE.fullmatch(expected[key])
                for key in REFERENCE_FILES
            ):
                continue
        paths = {
            key: Path(candidate["directory"]) / filename
            for key, filename in REFERENCE_FILES.items()
        }
        if all(path.is_file() for path in paths.values()):
            selected = {**candidate, "paths": paths}
            break
    if selected is None and download_missing:
        directory = cache_dir / canonical / canonical_release
        paths = {
            key: directory / filename for key, filename in REFERENCE_FILES.items()
        }
        for key, path in paths.items():
            if not path.is_file():
                staged_paths[path] = _download_atomic(str(release_entry[key]), path)
        selected = {
            "preset": canonical,
            "release": canonical_release,
            "directory": directory,
            "cache_source": "canonical",
            "paths": {
                key: staged_paths.get(path, path)
                for key, path in paths.items()
            },
            "final_paths": paths,
        }
    if selected is None:
        searched = [
            str(candidate["directory"])
            + (" (checksum required)" if candidate.get("strict_checksum") else "")
            for candidate in candidates
        ]
        return {
            "preset": canonical,
            "release": canonical_release,
            "status": "missing",
            "searched": searched,
        }
    checksums = {}
    files = {}
    try:
        for key, path in selected["paths"].items():
            kind = "gtf_url" if key == "gtf_url" else "fasta"
            validation = validate_reference_file(
                path,
                kind,
                expected_assembly=str(metadata.get("assembly", "")),
            )
            checksums[key] = validation["sha256"]
            files[key] = {
                "path": str(path),
                "cache_source": selected["cache_source"],
                **validation,
            }
        if selected.get("strict_checksum"):
            expected = release_entry.get("sha256", {})
            mismatched = [
                key for key, value in checksums.items()
                if value != str(expected.get(key, "")).lower()
            ]
            if mismatched:
                raise ValueError(
                    "historical cache does not match canonical checksums: "
                    + ", ".join(mismatched)
                )
    except Exception as exc:
        for path in staged_paths.values():
            path.unlink(missing_ok=True)
        return {
            "preset": canonical,
            "release": canonical_release,
            "status": "invalid",
            "cache_source": selected["cache_source"],
            "directory": str(selected["directory"]),
            "error": str(exc),
        }
    for destination, staged in staged_paths.items():
        os.replace(staged, destination)
    if staged_paths:
        files = {
            key: {
                **value,
                "path": str(selected["final_paths"][key]),
            }
            for key, value in files.items()
        }
    return {
        "preset": canonical,
        "release": canonical_release,
        "status": "valid",
        "cache_source": selected["cache_source"],
        "directory": str(selected["directory"]),
        "sha256": checksums,
        "files": files,
    }


def _write_manifest(path: Path, manifest: dict, reports: list[dict]) -> None:
    updates = [report for report in reports if report["status"] == "valid"]
    if len(updates) != len(reports):
        raise ValueError("Refusing to write: every selected preset/release must validate.")
    before = path.read_text(encoding="utf-8")
    changes = []
    for report in updates:
        existing = (
            manifest["presets"][report["preset"]][report["release"]]
            .get("sha256", {})
        )
        for key, value in report["sha256"].items():
            old_value = str(existing.get(key, ""))
            if old_value != value:
                changes.append(
                    {
                        "path": (
                            f"{report['preset']}/{report['release']}/sha256/{key}"
                        ),
                        "before": old_value,
                        "after": value,
                    }
                )
        manifest["presets"][report["preset"]][report["release"]]["sha256"] = dict(
            report["sha256"]
        )
    rendered = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Manifest updated atomically: {path}")
    for change in changes:
        print(f"- {change['path']}: {change['before'] or '<blank>'}")
        print(f"+ {change['path']}: {change['after']}")
    if not changes:
        print("(No checksum value changes.)")
    if before == rendered:
        print("(No textual manifest change.)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate cached references and propose pinned SHA256 values."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--preset", action="append")
    parser.add_argument("--release", default="pinned")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--download-missing", action="store_true")
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--safety-margin",
        type=float,
        default=DEFAULT_SAFETY_MARGIN,
        help="Additional disk-space fraction required during preflight.",
    )
    args = parser.parse_args(argv)

    manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8")) or {}
    presets = _parse_presets(args.preset, manifest)
    preflight = None
    if args.preflight_only or args.download_missing:
        preflight = preflight_presets(
            manifest,
            args.cache_dir,
            presets,
            args.release,
            safety_margin=args.safety_margin,
        )
        if args.preflight_only:
            payload = {"preflight": preflight}
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            if args.output_report:
                args.output_report.parent.mkdir(parents=True, exist_ok=True)
                args.output_report.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            return 0
    reports = [
        inspect_bundle(
            manifest,
            args.cache_dir,
            preset,
            args.release,
            download_missing=args.download_missing,
        )
        for preset in presets
    ]
    for report in reports:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if args.output_report:
        args.output_report.parent.mkdir(parents=True, exist_ok=True)
        args.output_report.write_text(
            json.dumps(
                {"preflight": preflight, "results": reports},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    if args.write:
        _write_manifest(args.manifest, manifest, reports)
    return 0 if all(report["status"] == "valid" for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
