import subprocess
import sys


def main() -> int:
    try:
        proc = subprocess.run(
            ["git", "show-ref"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        print("[git-sanity] git not found on PATH")
        return 1

    if proc.returncode != 0:
        print("[git-sanity] git show-ref failed")
        print(proc.stderr.strip())
        return proc.returncode

    bad_refs = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        refname = parts[1]
        if refname.startswith("refs/heads/origin/"):
            bad_refs.append(refname)

    if bad_refs:
        print("[git-sanity] ERROR: local branches under refs/heads/origin/ cause ambiguous origin/*")
        for ref in bad_refs:
            print(f"[git-sanity] {ref}")
        print("[git-sanity] Delete them with: git branch -D origin/<name>")
        return 2

    print("[git-sanity] OK: no refs/heads/origin/*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
