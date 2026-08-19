#!/usr/bin/env python3
import argparse, io, json, os, zipfile
from urllib.request import Request, urlopen

API="https://api.github.com"

def get_json(url,token):
    req=Request(url,headers={
        "Authorization":f"Bearer {token}",
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"DeathLab-Longevity-Research/0.2"
    })
    with urlopen(req,timeout=60) as r:
        return json.loads(r.read())

def get_bytes(url,token):
    req=Request(url,headers={
        "Authorization":f"Bearer {token}",
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"DeathLab-Longevity-Research/0.2"
    })
    with urlopen(req,timeout=120) as r:
        return r.read()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("outdir")
    a=ap.parse_args()
    repo=os.environ["GITHUB_REPOSITORY"]
    token=os.environ["GITHUB_TOKEN"]
    data=get_json(f"{API}/repos/{repo}/actions/artifacts?per_page=100&name={a.name}",token)
    arts=[x for x in data.get("artifacts",[]) if not x.get("expired")]
    if not arts:
        raise SystemExit(f"No non-expired artifact named {a.name}")
    arts.sort(key=lambda x:x["created_at"],reverse=True)
    art=arts[0]
    payload=get_bytes(art["archive_download_url"],token)
    os.makedirs(a.outdir,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        z.extractall(a.outdir)
    print(f"Downloaded artifact id={art['id']} created={art['created_at']} name={art['name']}")
if __name__=="__main__":
    main()
