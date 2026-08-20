from app.ui.error_messages import detect_error_key, extract_incomplete_files, summarize_error


def main():
    cases = [
        ("Directory cannot be locked: LockException", "msg.run.locked"),
        ("UnicodeDecodeError: 0x8b in fastp_stub", "msg.run.fastp_gzip"),
        (
            "MissingInputException in rule salmon_quant: Missing files:\nfastp/sample.fastq",
            "msg.run.fastp_missing",
        ),
        (
            "IncompleteFilesException:\nThe following files are incomplete:\n/output/fastp/a.json\n/output/fastp/a.html",
            "msg.run.incomplete_files",
        ),
    ]

    for text, expected in cases:
        key = detect_error_key(text)
        if key != expected:
            raise SystemExit(f"detect_error_key failed: expected {expected}, got {key}")
        summary = summarize_error(text, translate=lambda k: k)
        if summary["key"] != expected:
            raise SystemExit(f"summarize_error failed: expected {expected}, got {summary['key']}")

    fallback = summarize_error("some other error", translate=lambda k: k)
    if fallback["key"] != "msg.run_generic":
        raise SystemExit(f"fallback failed: expected msg.run_generic, got {fallback['key']}")

    files = extract_incomplete_files(
        "IncompleteFilesException:\nThe following files are incomplete:\n/output/fastp/a.json\n/output/fastp/a.html\n"
    )
    if files != ["/output/fastp/a.json", "/output/fastp/a.html"]:
        raise SystemExit(f"extract_incomplete_files failed: {files}")


def test_error_message_contracts():
    main()


if __name__ == "__main__":
    main()
