#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

COMMIT = "bf0db345b58127a438121b74ebf4ad843243a573"
SOURCE_PATH = "data/db/init/lerrcp-marked/A1.csv"
URL = f"https://raw.githubusercontent.com/tig12/g5/{COMMIT}/{SOURCE_PATH}"
EXPECTED_ROWS = 2087
EXPECTED_HEADER = ["NUM","NAME","OCCU","DATE","PLACE","CY","C2","LON","LAT","1955"]
FORBIDDEN_HEADER_TOKENS = (
    "death", "deces", "died", "p570", "lifespan", "longevity", "cause",
)

def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()

def validate(data: bytes) -> dict:
    text = data.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise SystemExit("FAIL-CLOSED empty A1 source")
    if rows[0] != EXPECTED_HEADER:
        raise SystemExit(f"FAIL-CLOSED header mismatch: {rows[0]}")
    lowered = " ".join(x.lower() for x in rows[0])
    if any(tok in lowered for tok in FORBIDDEN_HEADER_TOKENS):
        raise SystemExit("FAIL-CLOSED outcome-bearing source header")
    actual_rows = len(rows) - 1
    if actual_rows != EXPECTED_ROWS:
        raise SystemExit(f"FAIL-CLOSED expected {EXPECTED_ROWS} rows, got {actual_rows}")

    # NUM uniqueness is part of the source identity contract.
    nums = [r[0] for r in rows[1:]]
    if len(set(nums)) != EXPECTED_ROWS:
        raise SystemExit("FAIL-CLOSED duplicate NUM in A1 source")

    return {
        "repository": "tig12/g5",
        "commit": COMMIT,
        "path": SOURCE_PATH,
        "url": URL,
        "bytes": len(data),
        "git_blob_sha1": git_blob_sha1(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "rows": actual_rows,
        "header": rows[0],
        "outcome_accessed": False,
        "outcome_columns_present": False,
    }

def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: materialize_a1.py OUTPUT_A1.csv OUTPUT_SOURCE_LOCK.json")
    out = Path(sys.argv[1])
    lock = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    lock.parent.mkdir(parents=True, exist_ok=True)

    req = Request(URL, headers={"User-Agent": "DeathLab-A1-materializer/0.1"})
    with urlopen(req, timeout=90) as response:
        data = response.read()

    source_lock = validate(data)
    out.write_bytes(data)
    lock.write_text(json.dumps(source_lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(source_lock, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
