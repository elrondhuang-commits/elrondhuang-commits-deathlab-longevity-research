#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, hashlib, json, re, threading, time, unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SPARQL="https://query.wikidata.org/sparql"
API="https://www.wikidata.org/w/api.php"
USER_AGENT="DeathLab-Longevity-Research/0.2 (https://github.com/elrondhuang-commits/elrondhuang-commits-deathlab-longevity-research)"
BASE_LINKAGE_SHA256="7f04b2b6dfa052c5a87871ef1caea01e18f7740d9b22cc9e2739bf5dff859191"
EXPECTED_ROWS=3643
FORBIDDEN=("P570","P509","P20","P119")

# Exact copy of Stage-A V0.1 identity name rules.
def normalize_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())

def tokens(s: str) -> tuple[str, ...]:
    return tuple(t for t in normalize_name(s).split() if t)

def token_signature(s: str) -> tuple[str, ...]:
    return tuple(sorted(tokens(s)))

def name_class(source_name: str, candidate_texts: list[str]) -> tuple[int, str]:
    src = set(tokens(source_name))
    src_sig = token_signature(source_name)
    best = (0, "NO_NAME_MATCH")
    for text in candidate_texts:
        cand_t = tokens(text)
        cand = set(cand_t)
        if not src or not cand:
            continue
        if src_sig == tuple(sorted(cand_t)):
            best = max(best, (2, "EXACT_TOKEN_SIGNATURE"))
            continue
        smaller = min(len(src), len(cand))
        larger = max(len(src), len(cand))
        shared = len(src & cand)
        subset = src.issubset(cand) or cand.issubset(src)
        if subset and shared >= 2 and smaller / larger >= (2/3):
            best = max(best, (1, "SUBSET_TOKEN_MATCH"))
    return best

_rate_lock=threading.Lock()
_last_request_at=0.0
_blocked_until=0.0
MIN_INTERVAL=0.55

def sha256_file(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def _wait():
    global _last_request_at
    while True:
        with _rate_lock:
            now=time.monotonic()
            delay=max(0.0,_blocked_until-now,MIN_INTERVAL-(now-_last_request_at))
            if delay<=0:
                _last_request_at=now
                return
        time.sleep(min(delay,5.0))

def _block(seconds:float):
    global _blocked_until
    with _rate_lock:
        _blocked_until=max(_blocked_until,time.monotonic()+seconds)

def request_json(url:str, params:dict, method="POST", retries=18):
    headers={"User-Agent":USER_AGENT,"Accept":"application/json"}
    encoded=urlencode(params).encode()
    last=None
    for attempt in range(retries):
        _wait()
        try:
            if method=="POST":
                req=Request(url,data=encoded,headers={**headers,"Content-Type":"application/x-www-form-urlencoded"},method="POST")
            else:
                req=Request(url+"?"+encoded.decode("ascii"),headers=headers,method="GET")
            with urlopen(req,timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            last=e
            if e.code not in (429,500,502,503,504):
                raise
            ra=e.headers.get("Retry-After") if e.headers else None
            try:
                delay=float(ra) if ra else (60.0 if e.code==429 else min(120.0,2**min(attempt,7)))
            except ValueError:
                delay=60.0
            _block(delay)
            print(f"BACKOFF code={e.code} delay={delay:.1f}s",flush=True)
            time.sleep(min(delay,5.0))
        except (URLError,TimeoutError,json.JSONDecodeError) as e:
            last=e
            delay=min(60.0,1.5**attempt)
            _block(delay)
            time.sleep(min(delay,5.0))
    raise RuntimeError(f"network failed after retries: {last}")

def iso_day(d):
    return f'"{d.isoformat()}T00:00:00Z"^^xsd:dateTime'

def query_birthdate_candidates(target_dates, batch_size=20):
    by_date=defaultdict(set)
    dates=sorted(target_dates)
    for start in range(0,len(dates),batch_size):
        batch=dates[start:start+batch_size]
        values=" ".join(iso_day(d) for d in batch)
        q=f"""
SELECT DISTINCT ?item ?dob WHERE {{
  VALUES ?dob {{ {values} }}
  ?item wdt:P31 wd:Q5 ;
        p:P569 ?statement .
  ?statement wikibase:rank ?rank ;
             psv:P569 ?node .
  FILTER(?rank != wikibase:DeprecatedRank)
  ?node wikibase:timeValue ?dob ;
        wikibase:timePrecision ?precision .
  FILTER(?precision = 11)
}}
"""
        for forbidden in FORBIDDEN:
            assert forbidden not in q
        data=request_json(SPARQL,{"query":q,"format":"json"},"POST")
        for row in data.get("results",{}).get("bindings",[]):
            uri=row.get("item",{}).get("value","")
            qid=uri.rsplit("/",1)[-1]
            dob=row.get("dob",{}).get("value","")
            if not re.fullmatch(r"Q\d+",qid):
                continue
            try:
                d=datetime.fromisoformat(dob.lstrip("+").replace("Z","+00:00")).date()
            except ValueError:
                continue
            by_date[d].add(qid)
        print(f"birthdate batches {min(start+batch_size,len(dates))}/{len(dates)}",flush=True)
    return by_date

def fetch_texts(qids,batch_size=50):
    texts=defaultdict(set)
    qs=sorted(qids)
    for start in range(0,len(qs),batch_size):
        batch=qs[start:start+batch_size]
        data=request_json(API,{
            "action":"wbgetentities",
            "ids":"|".join(batch),
            "props":"labels|aliases",
            "languages":"en|fr|de|it|mul",
            "languagefallback":1,
            "format":"json",
            "formatversion":2,
            "maxlag":5
        },"POST")
        entities=data.get("entities",{})
        for qid,ent in entities.items():
            if not re.fullmatch(r"Q\d+",qid):
                continue
            for obj in (ent.get("labels") or {}).values():
                if isinstance(obj,dict) and isinstance(obj.get("value"),str):
                    texts[qid].add(obj["value"])
            for arr in (ent.get("aliases") or {}).values():
                if isinstance(arr,list):
                    for obj in arr:
                        if isinstance(obj,dict) and isinstance(obj.get("value"),str):
                            texts[qid].add(obj["value"])
        print(f"label batches {min(start+batch_size,len(qs))}/{len(qs)}",flush=True)
    return {q:sorted(v) for q,v in texts.items()}

def resolve_one(name, candidate_deltas, qid_texts):
    eligible=[]
    for qid,delta in candidate_deltas.items():
        rank,name_cls=name_class(name,qid_texts.get(qid,[]))
        if rank<1:
            continue
        date_rank=2 if delta==0 else 1
        eligible.append((date_rank,rank,qid,delta,name_cls))
    if not eligible:
        return None,0
    eligible.sort(reverse=True)
    top=(eligible[0][0],eligible[0][1])
    tied=[x for x in eligible if (x[0],x[1])==top]
    if len(tied)!=1:
        return "AMBIGUOUS",len(eligible)
    return tied[0],len(eligible)

def augment_pass(records, unresolved_nums, mode):
    num_to_birth={r["NUM"]:datetime.fromisoformat(r["DATE"]).date() for r in records if r["NUM"] in unresolved_nums}
    target_to_nums=defaultdict(set)
    for num,b in num_to_birth.items():
        offsets=(0,) if mode=="exact" else (-1,1)
        for off in offsets:
            target_to_nums[b+timedelta(days=off)].add(num)

    by_date=query_birthdate_candidates(set(target_to_nums))
    num_candidates=defaultdict(dict)
    all_qids=set()
    for d,qids in by_date.items():
        for num in target_to_nums.get(d,()):
            delta=abs((d-num_to_birth[num]).days)
            for qid in qids:
                old=num_candidates[num].get(qid)
                if old is None or delta<old:
                    num_candidates[num][qid]=delta
                all_qids.add(qid)
    print(f"{mode}: {len(all_qids)} unique birthdate candidate QIDs",flush=True)
    qid_texts=fetch_texts(all_qids)

    results={}
    for r in records:
        num=r["NUM"]
        if num not in unresolved_nums:
            continue
        hit,eligible_count=resolve_one(r["NAME"],num_candidates.get(num,{}),qid_texts)
        if hit is None:
            continue
        if hit=="AMBIGUOUS":
            results[num]={"status":"AMBIGUOUS","eligible_count":eligible_count}
            continue
        _,_,qid,delta,ncls=hit
        results[num]={
            "status":"LINKED","QID":qid,"date_delta_days":delta,
            "name_match_class":ncls,
            "candidate_count":len(num_candidates.get(num,{})),
            "eligible_count":eligible_count,
            "first_seen_pass":f"birthdate:{mode}"
        }
    return results

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--a2",required=True)
    ap.add_argument("--base-links",required=True)
    ap.add_argument("--base-links-sha",required=True)
    ap.add_argument("--base-summary",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    basep=Path(args.base_links)
    side=Path(args.base_links_sha).read_text(encoding="utf-8").split()[0]
    if side!=BASE_LINKAGE_SHA256 or sha256_file(basep)!=BASE_LINKAGE_SHA256:
        raise SystemExit("FAIL-CLOSED base linkage SHA mismatch")
    summary=json.loads(Path(args.base_summary).read_text(encoding="utf-8"))
    if summary.get("death_truth_accessed") is not False or summary.get("forbidden_properties_queried")!=[]:
        raise SystemExit("FAIL-CLOSED base linkage not proven outcome-blind")

    with open(args.a2,encoding="utf-8",newline="") as f:
        records=list(csv.DictReader(f))
    with basep.open(encoding="utf-8",newline="") as f:
        base_rows=list(csv.DictReader(f))
    if len(records)!=EXPECTED_ROWS or len(base_rows)!=EXPECTED_ROWS:
        raise SystemExit("FAIL-CLOSED row count")
    source={r["NUM"]:r for r in records}
    base={r["NUM"]:r for r in base_rows}
    if set(source)!=set(base):
        raise SystemExit("FAIL-CLOSED NUM mismatch")

    unresolved={n for n,r in base.items() if r["link_status"]!="LINKED"}
    print(f"BASE LINKED={EXPECTED_ROWS-len(unresolved)}/{EXPECTED_ROWS}; AUGMENT unresolved={len(unresolved)}",flush=True)

    exact=augment_pass(records,unresolved,"exact")
    newly={n:x for n,x in exact.items() if x.get("status")=="LINKED"}
    unresolved2=unresolved-set(newly)
    print(f"AFTER birthdate:exact NEW_LINKED={len(newly)} remaining={len(unresolved2)}",flush=True)

    pm1=augment_pass(records,unresolved2,"pm1")
    for n,x in pm1.items():
        if x.get("status")=="LINKED":
            newly[n]=x
    print(f"AFTER birthdate:pm1 TOTAL_NEW_LINKED={len(newly)}",flush=True)

    fields=["NUM","link_status","QID","date_delta_days","name_match_class","candidate_count","eligible_candidate_count","first_seen_pass"]
    outp=Path(args.out); outp.parent.mkdir(parents=True,exist_ok=True)
    final=[]
    for r in records:
        n=r["NUM"]
        br=base[n]
        if br["link_status"]=="LINKED":
            final.append({k:br.get(k,"") for k in fields})
        elif n in newly:
            x=newly[n]
            final.append({
                "NUM":n,"link_status":"LINKED","QID":x["QID"],
                "date_delta_days":x["date_delta_days"],
                "name_match_class":x["name_match_class"],
                "candidate_count":x["candidate_count"],
                "eligible_candidate_count":x["eligible_count"],
                "first_seen_pass":x["first_seen_pass"]
            })
        else:
            final.append({k:br.get(k,"") for k in fields})

    with outp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(final)
    digest=sha256_file(outp)
    counts=defaultdict(int)
    for r in final: counts[r["link_status"]]+=1
    summ={
        "protocol":"A2_WIKIDATA_IDENTITY_LINKAGE_AUGMENT_V0_2_FROZEN",
        "base_linkage_sha256":BASE_LINKAGE_SHA256,
        "linkage_sha256":digest,
        "source_rows":EXPECTED_ROWS,
        "base_linked":summary["status_counts"]["LINKED"],
        "new_linked":counts["LINKED"]-summary["status_counts"]["LINKED"],
        "total_linked":counts["LINKED"],
        "linked_fraction":counts["LINKED"]/EXPECTED_ROWS,
        "status_counts":dict(sorted(counts.items())),
        "death_truth_accessed":False,
        "forbidden_properties_queried":[],
        "prediction_used_for_linkage":False
    }
    outp.with_suffix(".summary.json").write_text(json.dumps(summ,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    outp.with_suffix(".sha256").write_text(f"{digest}  {outp.name}\n",encoding="utf-8")
    print(json.dumps(summ,indent=2,sort_keys=True),flush=True)

if __name__=="__main__":
    main()
