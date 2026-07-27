from pathlib import PurePosixPath, PureWindowsPath

import pytest

from scripts.srr_fetch import (
    SrrFetchError,
    normalize_fastq_url,
    resolve_local_file_uri,
    validate_runs,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("file:///C:/data/sample.fastq.gz", PureWindowsPath("C:/data/sample.fastq.gz")),
        ("file://C:/data/sample.fastq.gz", PureWindowsPath("C:/data/sample.fastq.gz")),
        (
            "file:///D:/path%20with%20spaces/sample.fastq.gz",
            PureWindowsPath("D:/path with spaces/sample.fastq.gz"),
        ),
        (r"C:\data\sample.fastq.gz", PureWindowsPath(r"C:\data\sample.fastq.gz")),
        ("C:/data/sample.fastq.gz", PureWindowsPath("C:/data/sample.fastq.gz")),
        ("c:/data/sample.fastq.gz", PureWindowsPath("c:/data/sample.fastq.gz")),
    ],
)
def test_resolve_windows_local_paths(value, expected):
    assert resolve_local_file_uri(value, platform="windows") == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("file:///home/user/data/sample.fastq.gz", PurePosixPath("/home/user/data/sample.fastq.gz")),
        ("/home/user/data/sample.fastq.gz", PurePosixPath("/home/user/data/sample.fastq.gz")),
        ("fixtures/sample.fastq.gz", PurePosixPath("fixtures/sample.fastq.gz")),
    ],
)
def test_resolve_posix_local_paths(value, expected):
    assert resolve_local_file_uri(value, platform="posix") == expected


def test_resolve_unc_file_uri_preserves_host_and_share():
    resolved = resolve_local_file_uri(
        "file://server/share/path/sample.fastq.gz",
        platform="windows",
    )
    assert resolved == PureWindowsPath(r"\\server\share\path\sample.fastq.gz")


def test_percent_encoding_is_decoded_exactly_once():
    resolved = resolve_local_file_uri(
        "file:///C:/data/literal%2520name.fastq.gz",
        platform="windows",
    )
    assert resolved == PureWindowsPath("C:/data/literal%20name.fastq.gz")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://example.org/sample.fastq.gz",
        "file://",
        "file://server",
        "file:///C:/bad%escape/sample.fastq.gz",
    ],
)
def test_invalid_local_file_uri_is_actionable(value):
    with pytest.raises(SrrFetchError):
        resolve_local_file_uri(value, platform="windows")


def test_ena_url_and_accession_behavior_is_unchanged():
    assert normalize_fastq_url("ftp.sra.ebi.ac.uk/sample.fastq.gz") == (
        "https://ftp.sra.ebi.ac.uk/sample.fastq.gz"
    )
    assert normalize_fastq_url("https://example.org/sample.fastq.gz") == (
        "https://example.org/sample.fastq.gz"
    )
    assert validate_runs(["srr123", "ERR456", "drr789"]) == ["SRR123", "ERR456", "DRR789"]
