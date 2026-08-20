from pathlib import Path


def _scan_blocks(lines, kinds):
    errors = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        for kind in kinds:
            if stripped.startswith(f"{kind}:"):
                indent = len(line) - len(line.lstrip())
                if "lambda" in stripped or "wildcards" in stripped:
                    errors.append(f"{kind} line contains function: {idx + 1}: {stripped}")
                idx += 1
                while idx < len(lines):
                    nxt = lines[idx]
                    if not nxt.strip():
                        idx += 1
                        continue
                    indent2 = len(nxt) - len(nxt.lstrip())
                    if indent2 <= indent:
                        idx -= 1
                        break
                    text = nxt.strip()
                    if "lambda" in text or "wildcards" in text:
                        errors.append(f"{kind} block contains function: {idx + 1}: {text}")
                    idx += 1
        idx += 1
    return errors


def main():
    repo_root = Path(__file__).resolve().parents[1]
    snakefile = repo_root / "workflow" / "Snakefile"
    lines = snakefile.read_text(encoding="utf-8").splitlines()
    errors = _scan_blocks(lines, ("output", "log", "params"))
    if errors:
        raise SystemExit("Snakefile output/log/params must not use functions:\n" + "\n".join(errors))


def test_snakefile_output_log_and_params_are_static():
    main()


if __name__ == "__main__":
    main()
