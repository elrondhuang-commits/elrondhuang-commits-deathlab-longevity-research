#!/usr/bin/env python3
import argparse,io,json,os,urllib.request,zipfile
from urllib.parse import urlparse

API="https://api.github.com"
UA="DeathLab-Combined-StageB/0.2"

class StripAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        new=super().redirect_request(req,fp,code,msg,headers,newurl)
        if new is not None and urlparse(req.full_url).netloc!=urlparse(newurl).netloc:
            new.remove_header("Authorization")
        return new

def j(url,token):
    req=urllib.request.Request(url,headers={
      "Authorization":f"Bearer {token}",
      "Accept":"application/vnd.github+json",
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":UA})
    with urllib.request.urlopen(req,timeout=60) as r:return json.loads(r.read())

def main():
    ap=argparse.ArgumentParser();ap.add_argument("name");ap.add_argument("outdir");a=ap.parse_args()
    repo=os.environ["GITHUB_REPOSITORY"];token=os.environ["GITHUB_TOKEN"]
    data=j(f"{API}/repos/{repo}/actions/artifacts?per_page=100&name={a.name}",token)
    arts=[x for x in data.get("artifacts",[]) if not x.get("expired")]
    if not arts:raise SystemExit(f"No non-expired artifact named {a.name}")
    arts.sort(key=lambda x:x["created_at"],reverse=True);art=arts[0]
    req=urllib.request.Request(art["archive_download_url"],headers={
      "Authorization":f"Bearer {token}",
      "Accept":"application/vnd.github+json",
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":UA})
    op=urllib.request.build_opener(StripAuthOnCrossHostRedirect())
    with op.open(req,timeout=120) as r:b=r.read()
    if not b.startswith(b"PK"):raise RuntimeError("artifact endpoint did not return ZIP")
    os.makedirs(a.outdir,exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        bad=z.testzip()
        if bad:raise RuntimeError(f"corrupt artifact member {bad}")
        z.extractall(a.outdir)
    print(f"Downloaded {art['name']} id={art['id']} created={art['created_at']}")
if __name__=="__main__":main()
