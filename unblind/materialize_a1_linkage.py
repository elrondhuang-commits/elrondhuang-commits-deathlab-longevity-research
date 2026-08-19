#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, io, json, sys
from pathlib import Path
from urllib.request import Request, urlopen

COMMIT="bf0db345b58127a438121b74ebf4ad843243a573"
PATH="data/db/init/lerrcp-marked/A1.csv"
URL=f"https://raw.githubusercontent.com/tig12/g5/{COMMIT}/{PATH}"
ROWS=2087
SHA256="613b965d54ba429231167034d7564ac2db9aabc6f5e6821810518b7f80a88913"
BLOB="8832bdb1d0ba7d937b7b2da9a50762c5ad7d126f"
HEADER=["NUM","NAME","OCCU","DATE","PLACE","CY","C2","LON","LAT","1955"]

def blob_sha1(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode()+data).hexdigest()

def main():
    if len(sys.argv)!=2: raise SystemExit("usage: materialize_a1_linkage.py OUT.csv")
    req=Request(URL,headers={"User-Agent":"DeathLab-A1-Linkage/0.1"})
    with urlopen(req,timeout=90) as r: data=r.read()
    if hashlib.sha256(data).hexdigest()!=SHA256: raise SystemExit("FAIL source sha256")
    if blob_sha1(data)!=BLOB: raise SystemExit("FAIL source blob sha1")
    rows=list(csv.reader(io.StringIO(data.decode("utf-8"))))
    if rows[0]!=HEADER or len(rows)-1!=ROWS: raise SystemExit("FAIL source structure")
    if len({r[0] for r in rows[1:]})!=ROWS: raise SystemExit("FAIL duplicate NUM")
    Path(sys.argv[1]).write_bytes(data)
    print("PASS exact A1 source", ROWS)

if __name__=="__main__": main()
