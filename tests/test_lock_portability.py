from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LOCKS = (ROOT / "requirements.lock.txt", ROOT / "requirements-test.lock.txt")


def _colorama_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r'^colorama==0\.4\.6\s*;\s*sys_platform == "win32"\s*\\\n'
        r'(?P<body>(?:    --hash=sha256:[0-9a-f]{64}(?: \\\n|\n))+)',
        text,
        flags=re.MULTILINE,
    )
    assert match, f"missing exact Windows colorama pin in {path.name}"
    return match.group(0)


@pytest.mark.parametrize("path", LOCKS)
def test_windows_colorama_is_exactly_pinned_and_hashed(path):
    block = _colorama_block(path)
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", block)) >= 2
    entries = re.findall(r"^colorama.*$", path.read_text(), re.MULTILINE)
    assert entries == ['colorama==0.4.6 ; sys_platform == "win32" \\']


def test_lock_inputs_pin_windows_colorama():
    expected = 'colorama==0.4.6 ; sys_platform == "win32"'
    assert expected in (ROOT / "requirements.in").read_text(encoding="utf-8")
    assert expected in (ROOT / "requirements-test.in").read_text(encoding="utf-8")


def test_runtime_lock_pins_windows_humanfriendly_dependency():
    text = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    assert 'pyreadline3==3.5.6 ; sys_platform == "win32" \\' in text


def test_ci_keeps_hash_enforcement():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert workflow.count("--require-hashes -r requirements.lock.txt") == 3
    assert workflow.count("--require-hashes -r requirements-test.lock.txt") == 3
