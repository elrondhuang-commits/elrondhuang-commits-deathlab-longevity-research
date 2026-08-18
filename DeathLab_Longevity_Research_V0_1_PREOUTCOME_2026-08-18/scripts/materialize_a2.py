#!/usr/bin/env python3
from pathlib import Path
from urllib.request import Request, urlopen
import csv, hashlib, io, sys

URL = "https://raw.githubusercontent.com/tig12/g5/bf0db345b58127a438121b74ebf4ad843243a573/data/db/init/lerrcp-marked/A2.csv"
EXPECTED_GIT_BLOB_SHA1 = "0b58382c3213900e03960bdc4046dacb7f26b6a2"
EXPECTED_BYTES = 529373
EXPECTED_ROWS = 3643
EXPECTED_HEADER = ["NUM","NAME","OCCU","DATE","PLACE","CY","C2","LON","LAT","1955"]

def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()

def validate(data: bytes) -> None:
    if len(data) != EXPECTED_BYTES:
        raise SystemExit(f"FAIL-CLOSED byte size {len(data)} != {EXPECTED_BYTES}")
    blob = git_blob_sha1(data)
    if blob != EXPECTED_GIT_BLOB_SHA1:
        raise SystemExit(f"FAIL-CLOSED Git blob {blob} != {EXPECTED_GIT_BLOB_SHA1}")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    if not rows or rows[0] != EXPECTED_HEADER:
        raise SystemExit(f"FAIL-CLOSED header mismatch: {rows[0] if rows else None}")
    if len(rows) - 1 != EXPECTED_ROWS:
        raise SystemExit(f"FAIL-CLOSED row count {len(rows)-1} != {EXPECTED_ROWS}")

def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/A2.frozen.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    req = Request(URL, headers={"User-Agent": "DeathLab-A2-materializer/0.1"})
    with urlopen(req, timeout=60) as response:
        data = response.read()
    validate(data)
    out.write_bytes(data)
    print(f"PASS rows={EXPECTED_ROWS} bytes={len(data)} git_blob_sha1={git_blob_sha1(data)}")

if __name__ == "__main__":
    main()
