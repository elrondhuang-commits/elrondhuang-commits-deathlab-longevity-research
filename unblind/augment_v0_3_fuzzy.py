#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,re,threading,time,unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

SPARQL="https://query.wikidata.org/sparql"
API="https://www.wikidata.org/w/api.php"
UA="DeathLab-Longevity-Research/0.3"
BASE_SHA="a3080e44b50382665d063dc2d7249f764a0d77efc368535e2581b0d2a50c7982"
EXPECTED_ROWS=3643
FORBIDDEN=("P570","P509","P20","P119")
LANGS="en|fr|de|it|es|nl|pt|pl|ru|sv|no|da|cs|hu|ro|el|la|mul"

def norm(s):
    s=unicodedata.normalize("NFKD",s or "")
    s="".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())

def toks(s): return tuple(norm(s).split())
def sig(s): return tuple(sorted(toks(s)))

def edit1(a,b):
    if a==b:return True
    if abs(len(a)-len(b))>1:return False
    if len(a)>len(b):a,b=b,a
    i=j=d=0
    while i<len(a) and j<len(b):
        if a[i]==b[j]:i+=1;j+=1;continue
        d+=1
        if d>1:return False
        if len(a)==len(b):i+=1;j+=1
        else:j+=1
    if i<len(a) or j<len(b):d+=1
    return d<=1

def name_class(source,texts):
    st=toks(source); ss=sig(source); src=set(st); best=(0,"NO_NAME_MATCH")
    for text in texts:
        ct=toks(text); cs=set(ct)
        if not src or not cs: continue
        if ss==tuple(sorted(ct)): best=max(best,(4,"EXACT_TOKEN_SIGNATURE")); continue
        smaller=min(len(src),len(cs)); larger=max(len(src),len(cs)); shared=len(src&cs)
        if (src.issubset(cs) or cs.issubset(src)) and shared>=2 and smaller/larger>=2/3:
            best=max(best,(3,"SUBSET_TOKEN_MATCH"))
    if best[0]>=3 or len(st)<2:return best
    surname=st[0]; initials={x[0] for x in st[1:] if x}
    for text in texts:
        ct=toks(text)
        if len(ct)<2:continue
        edge=(ct[0],ct[-1])
        other=list(ct[1:])+list(ct[:-1])
        if not (initials & {x[0] for x in other if x}):continue
        if surname in edge:best=max(best,(2,"SURNAME_EXACT_GIVEN_INITIAL"))
        elif len(surname)>=6 and any(edit1(surname,x) for x in edge):
            best=max(best,(1,"SURNAME_EDIT1_GIVEN_INITIAL"))
    return best

def place_match(a,texts):
    a=norm(a); aset=set(a.split())
    if not a:return False
    for x in texts:
        b=norm(x); bset=set(b.split())
        if not b:continue
        if tuple(sorted(aset))==tuple(sorted(bset)):return True
        if aset and bset and (aset.issubset(bset) or bset.issubset(aset)):return True
        if len(a)>=4 and len(b)>=4 and (a in b or b in a):return True
    return False

lock=threading.Lock(); last=0.0; blocked=0.0; MIN=0.55
def gate():
    global last
    while True:
        with lock:
            now=time.monotonic(); d=max(0.0,blocked-now,MIN-(now-last))
            if d<=0:last=now;return
        time.sleep(min(d,5))
def backoff(sec):
    global blocked
    with lock:blocked=max(blocked,time.monotonic()+sec)

def request_json(url,params,retries=18):
    data=urlencode(params).encode()
    headers={"User-Agent":UA,"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded"}
    err=None
    for attempt in range(retries):
        gate()
        try:
            with urlopen(Request(url,data=data,headers=headers,method="POST"),timeout=90) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            err=e
            if e.code not in (429,500,502,503,504):raise
            ra=e.headers.get("Retry-After") if e.headers else None
            try:d=float(ra) if ra else (60 if e.code==429 else min(120,2**min(attempt,7)))
            except ValueError:d=60
            backoff(d); print(f"BACKOFF {e.code} {d}s",flush=True); time.sleep(min(d,5))
        except (URLError,TimeoutError,json.JSONDecodeError) as e:
            err=e; d=min(60,1.5**attempt); backoff(d); time.sleep(min(d,5))
    raise RuntimeError(err)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def same_date_candidates(dates,batch=20):
    out=defaultdict(set); ds=sorted(dates)
    for i in range(0,len(ds),batch):
        chunk=ds[i:i+batch]
        vals=" ".join(f'"{d.isoformat()}T00:00:00Z"^^xsd:dateTime' for d in chunk)
        q=f"""SELECT DISTINCT ?item ?dob WHERE {{
VALUES ?dob {{ {vals} }}
?item wdt:P31 wd:Q5 ; p:P569 ?st .
?st wikibase:rank ?rank ; psv:P569 ?node .
FILTER(?rank != wikibase:DeprecatedRank)
?node wikibase:timeValue ?dob ; wikibase:timePrecision ?precision .
FILTER(?precision=11)
}}"""
        for f in FORBIDDEN:assert f not in q
        data=request_json(SPARQL,{"query":q,"format":"json"})
        for row in data.get("results",{}).get("bindings",[]):
            qid=row.get("item",{}).get("value","").rsplit("/",1)[-1]
            dv=row.get("dob",{}).get("value","")
            if not re.fullmatch(r"Q\d+",qid):continue
            try:d=datetime.fromisoformat(dv.lstrip("+").replace("Z","+00:00")).date()
            except ValueError:continue
            out[d].add(qid)
        print(f"date batches {min(i+batch,len(ds))}/{len(ds)}",flush=True)
    return out

def texts(qids,batch=50):
    out=defaultdict(set); qs=sorted(qids)
    for i in range(0,len(qs),batch):
        data=request_json(API,{"action":"wbgetentities","ids":"|".join(qs[i:i+batch]),
          "props":"labels|aliases","languages":LANGS,"languagefallback":1,
          "format":"json","formatversion":2,"maxlag":5})
        for q,e in data.get("entities",{}).items():
            for obj in (e.get("labels") or {}).values():
                if isinstance(obj,dict) and obj.get("value"):out[q].add(obj["value"])
            for arr in (e.get("aliases") or {}).values():
                for obj in arr or []:
                    if isinstance(obj,dict) and obj.get("value"):out[q].add(obj["value"])
    return {q:sorted(v) for q,v in out.items()}

def p19(qids,batch=100):
    out=defaultdict(set); qs=sorted(qids)
    for i in range(0,len(qs),batch):
        vals=" ".join(f"wd:{q}" for q in qs[i:i+batch])
        q=f"SELECT ?item ?pob WHERE {{ VALUES ?item {{ {vals} }} OPTIONAL {{ ?item wdt:P19 ?pob . }} }}"
        for f in FORBIDDEN:assert f not in q
        data=request_json(SPARQL,{"query":q,"format":"json"})
        for row in data.get("results",{}).get("bindings",[]):
            item=row.get("item",{}).get("value","").rsplit("/",1)[-1]
            pob=row.get("pob",{}).get("value","").rsplit("/",1)[-1]
            if re.fullmatch(r"Q\d+",item) and re.fullmatch(r"Q\d+",pob):out[item].add(pob)
    return out

def resolve(name,place,qids,ntxt,ptxt):
    ranked=[(name_class(name,ntxt.get(q,[]))[0],q,name_class(name,ntxt.get(q,[]))[1]) for q in qids]
    ranked=[x for x in ranked if x[0]>0]
    if not ranked:return None
    mr=max(x[0] for x in ranked); top=[x for x in ranked if x[0]==mr]
    if len(top)==1:return (*top[0],"UNIQUE_TOP")
    ph=[x for x in top if place_match(place,ptxt.get(x[1],[]))]
    if len(ph)==1:return (*ph[0],"PLACE_TIEBREAK")
    return "AMBIGUOUS"

def main():
    ap=argparse.ArgumentParser()
    for x in ("a2","base_links","base_links_sha","base_summary","out"):ap.add_argument("--"+x.replace("_","-"),dest=x,required=True)
    a=ap.parse_args()
    bp=Path(a.base_links); side=Path(a.base_links_sha).read_text().split()[0]
    if side!=BASE_SHA or sha(bp)!=BASE_SHA:raise SystemExit("FAIL base SHA")
    summ=json.loads(Path(a.base_summary).read_text())
    if summ.get("death_truth_accessed") is not False or summ.get("prediction_used_for_linkage") is not False or summ.get("forbidden_properties_queried")!=[]:
        raise SystemExit("FAIL base state")
    with open(a.a2,encoding="utf-8",newline="") as f:src=list(csv.DictReader(f))
    with bp.open(encoding="utf-8",newline="") as f:base=list(csv.DictReader(f))
    if len(src)!=EXPECTED_ROWS or len(base)!=EXPECTED_ROWS:raise SystemExit("rows")
    S={r["NUM"]:r for r in src}; B={r["NUM"]:r for r in base}
    unresolved={n for n,r in B.items() if r["link_status"]!="LINKED"}
    dates={datetime.fromisoformat(S[n]["DATE"]).date() for n in unresolved}
    bydate=same_date_candidates(dates)
    bynum={n:bydate.get(datetime.fromisoformat(S[n]["DATE"]).date(),set()) for n in unresolved}
    allq=set().union(*bynum.values()) if bynum else set()
    ntxt=texts(allq)
    tied=set()
    for n in unresolved:
        ranks=[(name_class(S[n]["NAME"],ntxt.get(q,[]))[0],q) for q in bynum[n]]
        ranks=[x for x in ranks if x[0]>0]
        if ranks:
            mr=max(x[0] for x in ranks); top=[q for r,q in ranks if r==mr]
            if len(top)>1:tied.update(top)
    pob=p19(tied); pobq={x for s in pob.values() for x in s}; pobtxt=texts(pobq) if pobq else {}
    ptxt={q:sorted({t for p in pob.get(q,set()) for t in pobtxt.get(p,[])}) for q in tied}
    new={}; ambiguous=0; classes=defaultdict(int)
    for n in unresolved:
        hit=resolve(S[n]["NAME"],S[n]["PLACE"],bynum[n],ntxt,ptxt)
        if hit is None:continue
        if hit=="AMBIGUOUS":ambiguous+=1;continue
        rank,qid,cls,how=hit
        new[n]=(qid,cls,how);classes[cls]+=1
    fields=["NUM","link_status","QID","date_delta_days","name_match_class","candidate_count","eligible_candidate_count","first_seen_pass"]
    final=[]
    for r in src:
        n=r["NUM"]; br=B[n]
        if br["link_status"]=="LINKED":final.append({k:br.get(k,"") for k in fields})
        elif n in new:
            qid,cls,how=new[n]
            elig=sum(name_class(S[n]["NAME"],ntxt.get(q,[]))[0]>0 for q in bynum[n])
            final.append({"NUM":n,"link_status":"LINKED","QID":qid,"date_delta_days":"0","name_match_class":cls,
              "candidate_count":str(len(bynum[n])),"eligible_candidate_count":str(elig),"first_seen_pass":"v0.3:"+how})
        else:final.append({k:br.get(k,"") for k in fields})
    op=Path(a.out);op.parent.mkdir(parents=True,exist_ok=True)
    with op.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(final)
    digest=sha(op);counts=defaultdict(int)
    for r in final:counts[r["link_status"]]+=1
    out={"protocol":"A2_WIKIDATA_IDENTITY_LINKAGE_AUGMENT_V0_3_FROZEN","base_linkage_sha256":BASE_SHA,
      "linkage_sha256":digest,"source_rows":EXPECTED_ROWS,"base_linked":summ["total_linked"],
      "new_linked":counts["LINKED"]-summ["total_linked"],"total_linked":counts["LINKED"],
      "linked_fraction":counts["LINKED"]/EXPECTED_ROWS,"new_match_classes":dict(sorted(classes.items())),
      "ambiguous_v0_3":ambiguous,"status_counts":dict(sorted(counts.items())),
      "death_truth_accessed":False,"prediction_used_for_linkage":False,"forbidden_properties_queried":[]}
    op.with_suffix(".summary.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    op.with_suffix(".sha256").write_text(f"{digest}  {op.name}\n")
    print(json.dumps(out,indent=2,sort_keys=True),flush=True)
if __name__=="__main__":main()
