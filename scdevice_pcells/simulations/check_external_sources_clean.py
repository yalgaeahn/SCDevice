"""Check that SCDevice simulations do not modify external source trees."""

import base64
import csv
import hashlib
import subprocess
import sys
from importlib import metadata
from pathlib import Path

SCDEVICE_ROOT = Path(__file__).resolve().parents[2]
KQC_ROOT = SCDEVICE_ROOT / "KQCircuits"


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(1)


def check_kqcircuits_clean():
    if not KQC_ROOT.exists():
        fail(f"Missing KQCircuits directory: {KQC_ROOT}")

    commands = (
        ("unstaged", ["diff", "--name-only"]),
        ("staged", ["diff", "--cached", "--name-only"]),
    )
    dirty = []
    for label, git_args in commands:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={KQC_ROOT.as_posix()}",
                "-C",
                str(KQC_ROOT),
                *git_args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        dirty.extend(f"{label}: {line}" for line in result.stdout.splitlines() if line.strip())

    if dirty:
        fail("KQCircuits tracked source has local changes:\n" + "\n".join(dirty))


def record_hash_matches(path, expected_hash):
    algorithm, encoded_hash = expected_hash.split("=", 1)
    if algorithm != "sha256":
        return True

    digest = hashlib.sha256(path.read_bytes()).digest()
    actual_hash = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return actual_hash == encoded_hash


def check_pyepr_record_clean():
    try:
        distribution = metadata.distribution("pyEPR-quantum")
    except metadata.PackageNotFoundError as exc:
        fail("pyEPR-quantum is not installed in this Python environment.")

    record_path = None
    for distribution_file in distribution.files or []:
        if distribution_file.name == "RECORD" and ".dist-info" in str(distribution_file):
            record_path = Path(distribution.locate_file(distribution_file))
            break
    if record_path is None or not record_path.exists():
        fail("Could not find pyEPR-quantum RECORD file.")

    site_packages = record_path.parent.parent
    mismatches = []
    with record_path.open(newline="", encoding="utf-8") as record_file:
        for row in csv.reader(record_file):
            if len(row) < 2 or not row[1]:
                continue
            file_path = site_packages / row[0]
            if not file_path.exists() or not record_hash_matches(file_path, row[1]):
                mismatches.append(row[0])

    if mismatches:
        fail("pyEPR installed files differ from wheel RECORD:\n" + "\n".join(mismatches))


def main():
    check_kqcircuits_clean()
    check_pyepr_record_clean()
    print("External KQCircuits and pyEPR sources are clean.")


if __name__ == "__main__":
    main()
