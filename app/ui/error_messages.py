import re
from typing import Callable, Dict, Optional


DEFAULT_KEY = "msg.run_generic"


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _has_any(text: str, patterns) -> bool:
    return any(_has(text, pat) for pat in patterns)


def _has_all(text: str, patterns) -> bool:
    return all(_has(text, pat) for pat in patterns)


def detect_error_key(log_text: str, state: Optional[Dict] = None) -> str:
    _ = state
    text = log_text or ""

    if _has_any(text, [r"Directory cannot be locked", r"LockException"]):
        return "msg.run.locked"

    if _has_all(text, [r"UnicodeDecodeError", r"0x8b"]):
        return "msg.run.fastp_gzip"

    if _has_all(text, [r"MissingInputException", r"salmon_quant"]) and _has(
        text,
        r"fastp[/\\\\].+\.fastq",
    ):
        return "msg.run.fastp_missing"

    if _has(text, r"IncompleteFilesException"):
        return "msg.run.incomplete_files"

    return DEFAULT_KEY


def extract_incomplete_files(log_text: str):
    if not log_text or "IncompleteFilesException" not in log_text:
        return []
    lines = log_text.splitlines()
    files = []
    capture = False
    for line in lines:
        if re.search(r"incomplete files|files are incomplete|following files are incomplete", line, re.IGNORECASE):
            capture = True
            tail = line.split(":", 1)[1].strip() if ":" in line else ""
            if tail:
                files.append(tail)
            continue
        if capture:
            if not line.strip():
                if files:
                    break
                continue
            if re.search(r"(RuleException|Error in rule|Traceback|jobid|Wildcards|Resources|rule )", line):
                break
            cleaned = line.strip()
            if cleaned.startswith("- "):
                cleaned = cleaned[2:].strip()
            if cleaned.startswith("* "):
                cleaned = cleaned[2:].strip()
            files.append(cleaned)

    if not files:
        for line in lines:
            if "/output" not in line:
                continue
            for token in re.findall(r"/output[^\s\]]+", line):
                files.append(token)

    deduped = []
    seen = set()
    for path in files:
        if not path:
            continue
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def summarize_error(
    log_text: str,
    state: Optional[Dict] = None,
    translate: Optional[Callable[[str], str]] = None,
) -> Dict[str, object]:
    key = detect_error_key(log_text, state)
    lines = []
    if translate:
        msg = translate(key)
        lines = [line for line in msg.splitlines() if line.strip()]
    title = lines[0] if lines else ""
    return {"key": key, "lines": lines, "title": title}
