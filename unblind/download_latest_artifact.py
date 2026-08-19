#!/usr/bin/env python3
import argparse
import io
import json
import os
import urllib.request
import urllib.error
import zipfile

API = "https://api.github.com"
UA = "DeathLab-Longevity-Research/0.2"

class StripAuthOnCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward GitHub Authorization to GitHub's signed artifact blob URL."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        from urllib.parse import urlparse
        if urlparse(req.full_url).netloc != urlparse(newurl).netloc:
            new.remove_header("Authorization")
        return new

def api_json(url, token):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": UA,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

def artifact_zip_bytes(url, token):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": UA,
        },
    )
    opener = urllib.request.build_opener(StripAuthOnCrossHostRedirect())
    with opener.open(req, timeout=120) as r:
        payload = r.read()
    # Fail closed: artifact endpoint must ultimately yield a ZIP.
    if not payload.startswith(b"PK"):
        raise RuntimeError(
            f"Artifact download did not return ZIP bytes; first16={payload[:16]!r}"
        )
    return payload

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("outdir")
    args = ap.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]

    data = api_json(
        f"{API}/repos/{repo}/actions/artifacts?per_page=100&name={args.name}",
        token,
    )
    arts = [x for x in data.get("artifacts", []) if not x.get("expired")]
    if not arts:
        raise SystemExit(f"No non-expired artifact named {args.name}")

    arts.sort(key=lambda x: x["created_at"], reverse=True)
    art = arts[0]

    payload = artifact_zip_bytes(art["archive_download_url"], token)

    os.makedirs(args.outdir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        bad = z.testzip()
        if bad is not None:
            raise RuntimeError(f"Corrupt artifact ZIP member: {bad}")
        z.extractall(args.outdir)

    print(
        f"Downloaded artifact id={art['id']} "
        f"created={art['created_at']} "
        f"name={art['name']}"
    )

if __name__ == "__main__":
    main()
