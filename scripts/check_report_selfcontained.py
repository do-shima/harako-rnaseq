import re
import sys
from pathlib import Path


BAD_PATTERNS = [
    r"https?://",
    r"fonts\.googleapis",
    r"fonts\.gstatic",
    r"cdn\.",
    r"unpkg\.com",
]


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--report":
        print("usage: check_report_selfcontained.py --report <report.html>")
        return 2
    path = Path(sys.argv[2])
    if not path.exists():
        print(f"report not found: {path}")
        return 2
    text = path.read_text(encoding="utf-8", errors="ignore")

    hits = []
    for pattern in BAD_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(pattern)

    if hits:
        print("FAIL: external references detected")
        for pattern in hits:
            print(f"- {pattern}")
        return 49

    if "data:image/" in text:
        print("INFO: data:image/ found")
    print("PASS: report appears self-contained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
