#!/usr/bin/env python3
import csv,hashlib,io,sys
from pathlib import Path
from urllib.request import Request,urlopen
COMMIT="bf0db345b58127a438121b74ebf4ad843243a573"
PATH="data/db/init/lerrcp-marked/A1.csv"
URL=f"https://raw.githubusercontent.com/tig12/g5/{COMMIT}/{PATH}"
ROWS=2087
SHA256="613b965d54ba429231167034d7564ac2db9aabc6f5e6821810518b7f80a88913"
BLOB="8832bdb1d0ba7d937b7b2da9a50762c5ad7d126f"
HEADER=["NUM","NAME","OCCU","DATE","PLACE","CY","C2","LON","LAT","1955"]
def blob(data):return hashlib.sha1(f"blob {len(data)}\0".encode()+data).hexdigest()
def main():
    req=Request(URL,headers={"User-Agent":"DeathLab-Combined-StageB/0.2"})
    with urlopen(req,timeout=90) as r:data=r.read()
    assert hashlib.sha256(data).hexdigest()==SHA256
    assert blob(data)==BLOB
    rows=list(csv.reader(io.StringIO(data.decode())))
    assert rows[0]==HEADER and len(rows)-1==ROWS and len({r[0] for r in rows[1:]})==ROWS
    Path(sys.argv[1]).write_bytes(data)
if __name__=="__main__":main()
