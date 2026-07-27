#!/usr/bin/env python3
"""Fetch FASTQ files for SRR/ERR/DRR accessions via ENA."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Dict, Iterable, List, Optional, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, url2pathname, urlopen


ACCESSION_RE = re.compile(r"^(SRR|ERR|DRR)\d+$", re.IGNORECASE)
RUN_COL_NORMALIZED = {
    "run",
    "runacc",
    "run_accession",
    "runaccession",
}
SAMPLE_COL_PRIORITY = [
    "SampleName",
    "sample_name",
    "submitted_sample_name",
    "SampleAlias",
    "sample_alias",
    "sample_title",
    "SampleTitle",
    "experiment_title",
    "Experiment",
]
DEFAULT_ENA_API_URL = "https://www.ebi.ac.uk/ena/portal/api/filereport"
DEFAULT_ENA_FIELDS = [
    "run_accession",
    "fastq_ftp",
    "fastq_md5",
    "library_layout",
    "sample_alias",
    "sample_title",
    "experiment_title",
    "study_accession",
    "scientific_name",
]
JST = timezone(timedelta(hours=9), name="JST")


class SrrFetchError(RuntimeError):
    pass


def resolve_local_file_uri(
    value: str,
    *,
    platform: Optional[str] = None,
) -> Union[Path, PurePath]:
    """Resolve a local path or file URI without losing drive or UNC components."""
    raw = str(value or "").strip()
    if not raw:
        raise SrrFetchError("Local file path or URI is empty.")
    if "\x00" in raw:
        raise SrrFetchError("Local file path or URI contains a null byte.")

    requested_platform = (platform or ("windows" if os.name == "nt" else "posix")).lower()
    if requested_platform in {"windows", "win32", "nt"}:
        target_platform = "windows"
    elif requested_platform in {"posix", "linux", "darwin", "macos"}:
        target_platform = "posix"
    else:
        raise SrrFetchError(f"Unsupported local path platform: {platform}")

    host_platform = "windows" if os.name == "nt" else "posix"

    def make_path(path_text: str, *, encoded: bool = False) -> Union[Path, PurePath]:
        if encoded:
            if re.search(r"%(?![0-9A-Fa-f]{2})", path_text):
                raise SrrFetchError(f"Malformed percent escape in local file URI: {raw}")
            decoded = url2pathname(path_text) if target_platform == host_platform else unquote(path_text)
        else:
            decoded = path_text
        if not decoded:
            raise SrrFetchError(f"Local file URI has no path: {raw}")
        if target_platform == host_platform:
            return Path(decoded)
        if target_platform == "windows":
            return PureWindowsPath(decoded)
        return PurePosixPath(decoded)

    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return make_path(raw)
    if target_platform == "windows" and raw.startswith("\\\\"):
        return make_path(raw)

    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme and scheme != "file":
        raise SrrFetchError(f"Unsupported local file URI scheme '{parsed.scheme}': {raw}")
    if not scheme:
        return make_path(raw)
    if parsed.query or parsed.fragment:
        raise SrrFetchError(f"Local file URI must not contain a query or fragment: {raw}")

    authority = parsed.netloc
    path_part = parsed.path
    if target_platform == "windows":
        if re.fullmatch(r"[A-Za-z]:", authority):
            return make_path(f"{authority}{path_part}", encoded=True)
        if authority and authority.lower() != "localhost":
            if not path_part or path_part == "/":
                raise SrrFetchError(f"UNC file URI is missing a share path: {raw}")
            return make_path(f"//{authority}{path_part}", encoded=True)
        if re.match(r"^/[A-Za-z]:/", path_part):
            path_part = path_part[1:]
        return make_path(path_part, encoded=True)

    if authority and authority.lower() != "localhost":
        if not path_part or path_part == "/":
            raise SrrFetchError(f"File URI authority is missing a path: {raw}")
        path_part = f"//{authority}{path_part}"
    return make_path(path_part, encoded=True)


@dataclass
class InputRun:
    run_accession: str
    sample_name: str
    condition: str
    source_row: Dict[str, str]


def setup_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("srr_fetch")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch FASTQ files from ENA for SRR/ERR/DRR runs.")
    parser.add_argument("--repo-root", default="", help="Repository root (default: inferred from script path).")
    parser.add_argument("--run-table", default="", help="RunSelector table path (.txt/.tsv/.csv).")
    parser.add_argument("--srr-list", default="", help="Accession list file path.")
    parser.add_argument("--input-file", default="", help="Auto-detect file mode (RunSelector table or accession list).")
    parser.add_argument("--runs", nargs="+", default=[], help="Accession arguments, e.g. --runs SRR1 SRR2.")
    parser.add_argument("--condition-from", default="", help="Column name in RunSelector table for condition values.")
    parser.add_argument("--condition-map", default="", help="TSV/CSV map: sample_or_run <tab> condition.")
    parser.add_argument("--force", action="store_true", help="Force re-download even if local file exists.")
    parser.add_argument("--retries", type=int, default=3, help="Download retries per file.")
    parser.add_argument("--retry-wait-sec", type=float, default=2.0, help="Base wait before retry.")
    parser.add_argument("--timeout-sec", type=int, default=60, help="HTTP timeout in seconds.")
    parser.add_argument("--ena-api-url", default=DEFAULT_ENA_API_URL, help="ENA filereport API endpoint.")
    parser.add_argument("--ena-fixture", default="", help="Optional local JSON fixture for ENA responses.")
    parser.add_argument("--emit-run-id", action="store_true", help="Print run_id only to stdout on success.")
    return parser.parse_args(argv)


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def choose_run_column(fieldnames: Iterable[str]) -> Optional[str]:
    for name in fieldnames:
        if normalized_key(name) in RUN_COL_NORMALIZED:
            return name
    for name in fieldnames:
        key = normalized_key(name)
        if "run" in key and ("acc" in key or "accession" in key):
            return name
    return None


def choose_condition_column(fieldnames: Iterable[str], requested: str) -> Optional[str]:
    if not requested:
        return None
    exact = {name: name for name in fieldnames}
    if requested in exact:
        return exact[requested]
    normalized_lookup = {normalized_key(name): name for name in fieldnames}
    return normalized_lookup.get(normalized_key(requested))


def choose_sample_value(row: Dict[str, str], fallback: str) -> str:
    row_lookup = {normalized_key(k): (k, (v or "").strip()) for k, v in row.items()}
    for candidate in SAMPLE_COL_PRIORITY:
        hit = row_lookup.get(normalized_key(candidate))
        if hit and hit[1]:
            return hit[1]
    return fallback


def sanitize_sample_name(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned or "sample"


def split_tokens_from_lines(path: Path) -> List[str]:
    runs: List[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [token.strip() for token in re.split(r"[\s,;]+", line) if token.strip()]
            runs.extend(parts)
    return runs


def detect_input_mode(path: Path) -> str:
    if not path.exists():
        raise SrrFetchError(f"Input file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    snippet = text[:8192]
    delimiter = "\t"
    if "\t" in snippet:
        delimiter = "\t"
    elif "," in snippet:
        delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(snippet, delimiters=",\t")
        delimiter = dialect.delimiter
    except csv.Error:
        pass

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames:
        run_col = choose_run_column(reader.fieldnames)
        if run_col:
            return "run_table"

    tokens = split_tokens_from_lines(path)
    if not tokens:
        raise SrrFetchError(f"No non-empty lines found in input file: {path}")
    matched = sum(1 for token in tokens if ACCESSION_RE.match(token))
    if matched / max(len(tokens), 1) >= 0.7:
        return "accession_list"
    raise SrrFetchError(
        f"Could not auto-detect input mode for {path}. "
        "Expected RunSelector table with a Run column, or an SRR/ERR/DRR list."
    )


def parse_runs_arg(tokens: Iterable[str]) -> List[str]:
    runs: List[str] = []
    for token in tokens:
        for part in re.split(r"[\s,;]+", token.strip()):
            if part:
                runs.append(part.upper())
    return runs


def validate_runs(runs: Iterable[str]) -> List[str]:
    out: List[str] = []
    for run in runs:
        run_norm = run.strip().upper()
        if not run_norm:
            continue
        if not ACCESSION_RE.match(run_norm):
            raise SrrFetchError(f"Invalid accession: {run}")
        out.append(run_norm)
    if not out:
        raise SrrFetchError("No accessions provided.")
    return out


def parse_run_table(path: Path, condition_from: str) -> List[InputRun]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    snippet = text[:8192]
    delimiter = "\t" if "\t" in snippet else ","
    try:
        dialect = csv.Sniffer().sniff(snippet, delimiters=",\t")
        delimiter = dialect.delimiter
    except csv.Error:
        pass

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise SrrFetchError(f"Run table has no header row: {path}")

    run_col = choose_run_column(reader.fieldnames)
    if not run_col:
        raise SrrFetchError(f"Run table is missing a Run/Run acc column: {path}")

    cond_col = choose_condition_column(reader.fieldnames, condition_from)
    if condition_from and not cond_col:
        raise SrrFetchError(f"--condition-from column not found: {condition_from}")

    parsed: List[InputRun] = []
    for row in reader:
        run_raw = (row.get(run_col) or "").strip().upper()
        if not run_raw:
            continue
        if not ACCESSION_RE.match(run_raw):
            continue
        sample_raw = choose_sample_value(row, run_raw)
        condition = (row.get(cond_col) or "").strip() if cond_col else ""
        parsed.append(
            InputRun(
                run_accession=run_raw,
                sample_name=sanitize_sample_name(sample_raw),
                condition=condition,
                source_row={k: (v or "") for k, v in row.items()},
            )
        )

    if not parsed:
        raise SrrFetchError(f"No SRR/ERR/DRR runs found in run table: {path}")
    return parsed


def parse_accession_list(path: Path) -> List[InputRun]:
    runs = validate_runs(split_tokens_from_lines(path))
    return [InputRun(run_accession=run, sample_name=run, condition="", source_row={}) for run in runs]


def ensure_unique_sample_names(entries: List[InputRun]) -> None:
    counts: Dict[str, int] = {}
    for entry in entries:
        counts[entry.sample_name] = counts.get(entry.sample_name, 0) + 1
    for entry in entries:
        if counts.get(entry.sample_name, 0) > 1:
            entry.sample_name = sanitize_sample_name(f"{entry.sample_name}_{entry.run_accession}")


def load_condition_map(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    snippet = text[:4096]
    delimiter = "\t" if "\t" in snippet else ","
    try:
        dialect = csv.Sniffer().sniff(snippet, delimiters=",\t")
        delimiter = dialect.delimiter
    except csv.Error:
        pass

    mapping: Dict[str, str] = {}
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not rows:
        return mapping

    start_index = 0
    first = [cell.strip() for cell in rows[0]]
    if len(first) >= 2 and (
        normalized_key(first[0]) in {"sampleorrun", "sample", "run", "accession"}
        or normalized_key(first[1]) == "condition"
    ):
        start_index = 1

    for row in rows[start_index:]:
        if len(row) < 2:
            continue
        key = row[0].strip()
        value = row[1].strip()
        if key:
            mapping[key] = value
    return mapping


def apply_condition_map(entries: List[InputRun], mapping: Dict[str, str]) -> None:
    for entry in entries:
        mapped = mapping.get(entry.sample_name)
        if mapped is None:
            mapped = mapping.get(entry.run_accession)
        if mapped is not None:
            entry.condition = mapped


def load_ena_fixture(path: Path) -> Dict[str, Dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixture: Dict[str, Dict[str, str]] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                run = (value.get("run_accession") or key or "").upper()
                if run:
                    row = {k: str(v) if v is not None else "" for k, v in value.items()}
                    row.setdefault("run_accession", run)
                    fixture[run] = row
    elif isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                run = str(row.get("run_accession", "")).upper()
                if run:
                    fixture[run] = {k: str(v) if v is not None else "" for k, v in row.items()}
    else:
        raise SrrFetchError("ENA fixture must be a JSON object or array.")
    return fixture


def build_filreport_url(base_url: str, run_accession: str) -> str:
    parsed = urlparse(base_url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update(
        {
            "accession": run_accession,
            "result": "read_run",
            "fields": ",".join(DEFAULT_ENA_FIELDS),
            "format": "json",
        }
    )
    return urlunparse(parsed._replace(query=urlencode(existing)))


def fetch_ena_row(
    run_accession: str,
    ena_api_url: str,
    timeout_sec: int,
    fixture: Dict[str, Dict[str, str]],
) -> Dict[str, str]:
    if fixture:
        row = fixture.get(run_accession.upper())
        if row:
            return row
        raise SrrFetchError(f"Run {run_accession} missing in --ena-fixture payload.")

    url = build_filreport_url(ena_api_url, run_accession)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "rnaseq-pipeline-srr-fetch/1.0"})
    try:
        with urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SrrFetchError(f"ENA API request failed for {run_accession}: {exc}") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SrrFetchError(f"ENA API returned invalid JSON for {run_accession}") from exc

    if not isinstance(payload, list) or not payload:
        raise SrrFetchError(f"ENA API returned no rows for {run_accession}")

    for row in payload:
        if str(row.get("run_accession", "")).upper() == run_accession.upper():
            return {k: str(v) if v is not None else "" for k, v in row.items()}
    first = payload[0]
    return {k: str(v) if v is not None else "" for k, v in first.items()}


def normalize_fastq_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "ftp", "file"}:
        return value
    return f"https://{value}"


def classify_read_side(file_name: str, index: int, total: int) -> str:
    lower = file_name.lower()
    if re.search(r"([._-]r?1)([._-]|\.fastq|\.fq|$)", lower):
        return "R1"
    if re.search(r"([._-]r?2)([._-]|\.fastq|\.fq|$)", lower):
        return "R2"
    if total >= 2:
        return "R1" if index == 0 else "R2"
    return "R1"


def parse_fastq_entries(ena_row: Dict[str, str]) -> List[Dict[str, str]]:
    ftp_items = [item.strip() for item in ena_row.get("fastq_ftp", "").split(";") if item.strip()]
    md5_items = [item.strip().lower() for item in ena_row.get("fastq_md5", "").split(";") if item.strip()]
    files: List[Dict[str, str]] = []
    for idx, raw_url in enumerate(ftp_items):
        url = normalize_fastq_url(raw_url)
        file_name = Path(urlparse(url).path).name or f"fastq_{idx + 1}.fastq.gz"
        md5 = md5_items[idx] if idx < len(md5_items) else ""
        files.append(
            {
                "url": url,
                "source_name": file_name,
                "md5": md5,
                "side": classify_read_side(file_name, idx, len(ftp_items)),
            }
        )
    return files


def md5_of_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_remote_size_http(url: str, timeout_sec: int) -> Optional[int]:
    req = Request(url, method="HEAD")
    try:
        with urlopen(req, timeout=timeout_sec) as response:
            length = response.headers.get("Content-Length")
            if length and str(length).isdigit():
                return int(length)
    except Exception:
        return None
    return None


def copy_file_url(url: str, dest: Path, force: bool) -> int:
    source_path = resolve_local_file_uri(url)
    if not isinstance(source_path, Path):
        source_path = Path(source_path)
    if not source_path.exists():
        raise SrrFetchError(f"File URL source not found: {source_path}")
    source_size = source_path.stat().st_size
    if force and dest.exists():
        dest.unlink()
    if dest.exists() and dest.stat().st_size == source_size and source_size > 0:
        return source_size
    if dest.exists() and dest.stat().st_size > source_size:
        dest.unlink()
    offset = dest.stat().st_size if dest.exists() else 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    mode = "ab" if offset > 0 else "wb"
    with source_path.open("rb") as src, dest.open(mode) as out:
        if offset:
            src.seek(offset)
        shutil.copyfileobj(src, out, length=1024 * 1024)
    return dest.stat().st_size


def download_http(
    url: str,
    dest: Path,
    timeout_sec: int,
    force: bool,
) -> int:
    if force and dest.exists():
        dest.unlink()

    remote_size = get_remote_size_http(url, timeout_sec)
    existing_size = dest.stat().st_size if dest.exists() else 0
    start_byte = 0
    mode = "wb"

    if dest.exists() and existing_size > 0 and remote_size is not None:
        if existing_size == remote_size:
            return existing_size
        if existing_size < remote_size:
            start_byte = existing_size
            mode = "ab"
        else:
            dest.unlink()
            existing_size = 0

    headers = {}
    if start_byte > 0:
        headers["Range"] = f"bytes={start_byte}-"

    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout_sec) as response:
        status = getattr(response, "status", response.getcode())
        if start_byte > 0 and int(status) != 206:
            start_byte = 0
            mode = "wb"
        if start_byte == 0:
            dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open(mode) as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)

    return dest.stat().st_size


def download_with_retry(
    url: str,
    dest: Path,
    expected_md5: str,
    force: bool,
    retries: int,
    retry_wait_sec: float,
    timeout_sec: int,
    logger: logging.Logger,
) -> Tuple[str, int, Optional[str]]:
    expected_md5 = (expected_md5 or "").strip().lower()

    if dest.exists() and dest.stat().st_size > 0 and not force:
        if not expected_md5:
            size = dest.stat().st_size
            logger.info("Skipping existing file=%s size=%d url=%s", dest.name, size, url)
            return ("skipped_existing", size, None)
        observed = md5_of_file(dest)
        if observed == expected_md5:
            size = dest.stat().st_size
            logger.info("Skipping verified file=%s size=%d url=%s", dest.name, size, url)
            return ("skipped_verified", size, observed)
        logger.warning("MD5 mismatch for existing file; re-downloading: %s", dest)
        dest.unlink()

    for attempt in range(1, retries + 1):
        try:
            logger.info("Downloading %s -> %s (attempt %d/%d)", url, dest, attempt, retries)
            scheme = urlparse(url).scheme.lower()
            if scheme == "file":
                bytes_written = copy_file_url(url, dest, force=force)
            else:
                bytes_written = download_http(url, dest, timeout_sec=timeout_sec, force=force)

            observed_md5 = None
            if expected_md5:
                observed_md5 = md5_of_file(dest)
                if observed_md5 != expected_md5:
                    raise SrrFetchError(
                        f"MD5 mismatch for {dest.name}: expected {expected_md5}, observed {observed_md5}"
                    )
            logger.info("Downloaded file=%s size=%d url=%s", dest.name, bytes_written, url)
            return ("downloaded", bytes_written, observed_md5)
        except Exception as exc:
            logger.warning("Download failed for %s: %s", url, exc)
            if dest.exists():
                try:
                    if dest.stat().st_size == 0:
                        dest.unlink()
                except OSError:
                    pass
            if attempt >= retries:
                raise
            sleep_sec = retry_wait_sec * attempt
            logger.info("Retrying in %.1f sec", sleep_sec)
            time.sleep(sleep_sec)

    raise SrrFetchError(f"Failed to download after retries: {url}")


def resolve_inputs(args: argparse.Namespace) -> Tuple[str, List[InputRun], str]:
    mode = ""
    source = ""
    if args.run_table:
        mode = "run_table"
        source = args.run_table
        entries = parse_run_table(Path(args.run_table), condition_from=args.condition_from)
    elif args.srr_list:
        mode = "accession_list"
        source = args.srr_list
        entries = parse_accession_list(Path(args.srr_list))
    elif args.input_file:
        detected = detect_input_mode(Path(args.input_file))
        source = args.input_file
        if detected == "run_table":
            mode = "run_table"
            entries = parse_run_table(Path(args.input_file), condition_from=args.condition_from)
        else:
            mode = "accession_list"
            entries = parse_accession_list(Path(args.input_file))
    elif args.runs:
        mode = "runs_arg"
        source = "CLI --runs"
        runs = validate_runs(parse_runs_arg(args.runs))
        entries = [InputRun(run_accession=run, sample_name=run, condition="", source_row={}) for run in runs]
    else:
        raise SrrFetchError("Specify one input source: --run-table, --srr-list, --input-file, or --runs.")

    ensure_unique_sample_names(entries)
    return mode, entries, source


def format_now_payload() -> Dict[str, str]:
    now_utc = datetime.now(timezone.utc)
    now_jst = now_utc.astimezone(JST)
    return {
        "utc": now_utc.isoformat(),
        "jst": now_jst.isoformat(),
        "run_id_stamp": now_jst.strftime("%Y%m%d_%H%M%S"),
    }


def write_samples_tsv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("sample\tcondition\tfastq1\tfastq2\n")
        for row in rows:
            handle.write(
                f"{row['sample']}\t{row['condition']}\t{row['fastq1']}\t{row['fastq2']}\n"
            )


def pick_fastq_pair(
    fastq_entries: List[Dict[str, str]],
    layout: str,
) -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
    if not fastq_entries:
        return (None, None)
    r1 = next((item for item in fastq_entries if item.get("side") == "R1"), None)
    r2 = next((item for item in fastq_entries if item.get("side") == "R2"), None)
    if layout.upper() == "PAIRED":
        if r1 is None and fastq_entries:
            r1 = fastq_entries[0]
        if r2 is None and len(fastq_entries) > 1:
            r2 = fastq_entries[1]
        return (r1, r2)
    if r1 is None:
        r1 = fastq_entries[0]
    return (r1, None)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    data_in_root = repo_root / "data_in"
    srr_root = data_in_root / "srr"

    clock = format_now_payload()
    run_id = f"run_{clock['run_id_stamp']}_{uuid.uuid4().hex[:6]}"
    run_root = srr_root / run_id
    fastq_root = run_root / "fastq"
    metadata_root = run_root / "metadata"
    run_meta_root = run_root / "run"
    run_meta_root.mkdir(parents=True, exist_ok=True)

    logger = setup_logger(run_meta_root / "srr_fetch.log")
    logger.info("Starting srr_fetch run_id=%s repo_root=%s", run_id, repo_root)

    manifest: Dict[str, object] = {
        "run_id": run_id,
        "created_at_utc": clock["utc"],
        "created_at_jst": clock["jst"],
        "status": "running",
        "source": {},
        "settings": {
            "argv": list(argv if argv is not None else sys.argv[1:]),
            "ena_api_url": args.ena_api_url,
            "force": bool(args.force),
            "retries": int(args.retries),
            "retry_wait_sec": float(args.retry_wait_sec),
            "timeout_sec": int(args.timeout_sec),
            "condition_from": args.condition_from or "",
            "condition_map": args.condition_map or "",
            "ena_fixture": args.ena_fixture or "",
        },
        "paths": {
            "run_root": str(run_root),
            "fastq_root": str(fastq_root),
            "samples_tsv": str(metadata_root / "samples.tsv"),
            "log": str(run_meta_root / "srr_fetch.log"),
        },
        "runs": [],
        "errors": [],
    }

    manifest_path = run_meta_root / "manifest.json"

    try:
        mode, entries, source = resolve_inputs(args)
        manifest["source"] = {"mode": mode, "value": source, "entry_count": len(entries)}
        logger.info("Resolved input mode=%s source=%s count=%d", mode, source, len(entries))

        if args.condition_map:
            mapping = load_condition_map(Path(args.condition_map))
            apply_condition_map(entries, mapping)
            logger.info("Applied condition map entries=%d", len(mapping))

        fixture = load_ena_fixture(Path(args.ena_fixture)) if args.ena_fixture else {}
        sample_rows: List[Dict[str, str]] = []

        for entry in entries:
            logger.info("Resolving run=%s sample=%s", entry.run_accession, entry.sample_name)
            ena_row = fetch_ena_row(
                run_accession=entry.run_accession,
                ena_api_url=args.ena_api_url,
                timeout_sec=args.timeout_sec,
                fixture=fixture,
            )
            fastq_entries = parse_fastq_entries(ena_row)
            if not fastq_entries:
                raise SrrFetchError(
                    f"ENA row for {entry.run_accession} has no fastq_ftp entries. "
                    "Check accession availability and ENA endpoint."
                )

            layout = (ena_row.get("library_layout") or "SINGLE").upper()
            r1_entry, r2_entry = pick_fastq_pair(fastq_entries, layout=layout)
            if not r1_entry:
                raise SrrFetchError(f"Could not resolve R1 FASTQ for {entry.run_accession}")

            sample = sanitize_sample_name(entry.sample_name)
            r1_name = f"{sample}_R1.fastq.gz"
            r2_name = f"{sample}_R2.fastq.gz"
            r1_dest = fastq_root / r1_name
            r2_dest = fastq_root / r2_name

            logger.info(
                "Run=%s layout=%s R1=%s URL=%s",
                entry.run_accession,
                layout,
                r1_name,
                r1_entry.get("url"),
            )
            r1_status, r1_size, r1_md5 = download_with_retry(
                url=r1_entry["url"],
                dest=r1_dest,
                expected_md5=r1_entry.get("md5", ""),
                force=args.force,
                retries=max(1, args.retries),
                retry_wait_sec=max(0.5, args.retry_wait_sec),
                timeout_sec=max(1, args.timeout_sec),
                logger=logger,
            )

            fastq2_rel = ""
            file_records = [
                {
                    "read": "R1",
                    "source_url": r1_entry.get("url", ""),
                    "source_name": r1_entry.get("source_name", ""),
                    "expected_md5": r1_entry.get("md5", ""),
                    "observed_md5": r1_md5 or "",
                    "dest_rel": f"fastq/{r1_name}",
                    "bytes": r1_size,
                    "status": r1_status,
                }
            ]

            if r2_entry:
                logger.info(
                    "Run=%s layout=%s R2=%s URL=%s",
                    entry.run_accession,
                    layout,
                    r2_name,
                    r2_entry.get("url"),
                )
                r2_status, r2_size, r2_md5 = download_with_retry(
                    url=r2_entry["url"],
                    dest=r2_dest,
                    expected_md5=r2_entry.get("md5", ""),
                    force=args.force,
                    retries=max(1, args.retries),
                    retry_wait_sec=max(0.5, args.retry_wait_sec),
                    timeout_sec=max(1, args.timeout_sec),
                    logger=logger,
                )
                fastq2_rel = f"fastq/{r2_name}"
                file_records.append(
                    {
                        "read": "R2",
                        "source_url": r2_entry.get("url", ""),
                        "source_name": r2_entry.get("source_name", ""),
                        "expected_md5": r2_entry.get("md5", ""),
                        "observed_md5": r2_md5 or "",
                        "dest_rel": f"fastq/{r2_name}",
                        "bytes": r2_size,
                        "status": r2_status,
                    }
                )

            condition_value = entry.condition if entry.condition is not None else ""
            sample_rows.append(
                {
                    "sample": sample,
                    "condition": condition_value,
                    "fastq1": f"fastq/{r1_name}",
                    "fastq2": fastq2_rel,
                }
            )

            manifest_runs = manifest.get("runs")
            if isinstance(manifest_runs, list):
                manifest_runs.append(
                    {
                        "run_accession": entry.run_accession,
                        "sample": sample,
                        "condition": condition_value,
                        "library_layout": layout,
                        "ena_row": {
                            key: ena_row.get(key, "")
                            for key in (
                                "run_accession",
                                "study_accession",
                                "sample_alias",
                                "sample_title",
                                "experiment_title",
                                "scientific_name",
                                "library_layout",
                                "fastq_ftp",
                                "fastq_md5",
                            )
                        },
                        "files": file_records,
                    }
                )

        write_samples_tsv(metadata_root / "samples.tsv", sample_rows)
        manifest["status"] = "ok"
        logger.info("Wrote %s with %d samples", metadata_root / "samples.tsv", len(sample_rows))
        logger.info("Completed run_id=%s", run_id)
    except Exception as exc:
        manifest["status"] = "error"
        errors = manifest.get("errors")
        if isinstance(errors, list):
            errors.append(str(exc))
        logger.error("Failed: %s", exc)
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
        raise
    finally:
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)

    if args.emit_run_id:
        print(run_id)
    else:
        print(f"run_id={run_id}")
        print(f"samples_tsv={metadata_root / 'samples.tsv'}")
        print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
