#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,math,re,threading,time,unicodedata
from collections import defaultdict
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

SPARQL="https://query.wikidata.org/sparql"
API="https://www.wikidata.org/w/api.php"
UA="DeathLab-Longevity-Research-A1-Linkage/0.1"
FORBIDDEN=("P570","P509","P20","P119")
LANGS="en|fr|de|it|es|nl|pt|pl|ru|sv|no|da|cs|hu|ro|el|la|mul"
ROWS=2087

def norm(s):
    s=unicodedata.normalize("NFKD",s or "")
    s="".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())

def toks(s): return tuple(norm(s).split())
def sig(s): return tuple(sorted(toks(s)))

def name_class(source,texts):
    src=set(toks(source)); ss=sig(source); best=(0,"NO_NAME_MATCH")
    for text in texts:
        ct=toks(text); cs=set(ct)
        if not src or not cs: continue
        if ss==tuple(sorted(ct)):
            best=max(best,(2,"EXACT_TOKEN_SIGNATURE")); continue
        small=min(len(src),len(cs)); large=max(len(src),len(cs)); shared=len(src&cs)
        if (src.issubset(cs) or cs.issubset(src)) and shared>=2 and small/large>=2/3:
            best=max(best,(1,"SUBSET_TOKEN_MATCH"))
    return best

def hav(lat1,lon1,lat2,lon2):
    R=6371.0088
    a1,a2=math.radians(lat1),math.radians(lat2)
    da=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    x=math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))

def place_text_match(a,texts):
    a=norm(a); aset=set(a.split())
    if not a:return False
    for x in texts:
        b=norm(x); bset=set(b.split())
        if not b:continue
        if aset==bset:return True
        if aset and bset and (aset.issubset(bset) or bset.issubset(aset)):return True
        if len(a)>=4 and len(b)>=4 and (a in b or b in a):return True
    return False

lock=threading.Lock(); last=0.0; blocked=0.0; MIN=.55
def gate():
    global last
    while True:
        with lock:
            now=time.monotonic(); d=max(0.0,blocked-now,MIN-(now-last))
            if d<=0: last=now; return
        time.sleep(min(d,5))
def block(sec):
    global blocked
    with lock: blocked=max(blocked,time.monotonic()+sec)

def req(url,params,retries=20):
    data=urlencode(params).encode()
    headers={"User-Agent":UA,"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded"}
    err=None
    for i in range(retries):
        gate()
        try:
            with urlopen(Request(url,data=data,headers=headers,method="POST"),timeout=90) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            err=e
            if e.code not in (429,500,502,503,504): raise
            ra=e.headers.get("Retry-After") if e.headers else None
            try:d=float(ra) if ra else (60 if e.code==429 else min(120,2**min(i,7)))
            except ValueError:d=60
            block(d); print(f"BACKOFF {e.code} {d}s",flush=True); time.sleep(min(d,5))
        except (URLError,TimeoutError,json.JSONDecodeError) as e:
            err=e; d=min(60,1.5**i); block(d); time.sleep(min(d,5))
    raise RuntimeError(err)

def candidates(dates,batch=20):
    out=defaultdict(set); ds=sorted(dates)
    for i in range(0,len(ds),batch):
        vals=" ".join(f'"{d.isoformat()}T00:00:00Z"^^xsd:dateTime' for d in ds[i:i+batch])
        q=f"""SELECT DISTINCT ?item ?dob WHERE {{
VALUES ?dob {{ {vals} }}
?item wdt:P31 wd:Q5 ; p:P569 ?st .
?st wikibase:rank ?rank ; psv:P569 ?node .
FILTER(?rank != wikibase:DeprecatedRank)
?node wikibase:timeValue ?dob ; wikibase:timePrecision ?precision .
FILTER(?precision=11)
}}"""
        for x in FORBIDDEN: assert x not in q
        data=req(SPARQL,{"query":q,"format":"json"})
        for row in data.get("results",{}).get("bindings",[]):
            qid=row.get("item",{}).get("value","").rsplit("/",1)[-1]
            dv=row.get("dob",{}).get("value","")
            if not re.fullmatch(r"Q\d+",qid): continue
            try:d=datetime.fromisoformat(dv.lstrip("+").replace("Z","+00:00")).date()
            except ValueError: continue
            out[d].add(qid)
        print(f"birthdate batches {min(i+batch,len(ds))}/{len(ds)}",flush=True)
    return out

def entity_texts(qids,batch=50):
    out=defaultdict(set); qs=sorted(qids)
    for i in range(0,len(qs),batch):
        data=req(API,{"action":"wbgetentities","ids":"|".join(qs[i:i+batch]),
          "props":"labels|aliases","languages":LANGS,"languagefallback":1,
          "format":"json","formatversion":2,"maxlag":5})
        for q,e in data.get("entities",{}).items():
            for obj in (e.get("labels") or {}).values():
                if isinstance(obj,dict) and obj.get("value"): out[q].add(obj["value"])
            for arr in (e.get("aliases") or {}).values():
                for obj in arr or []:
                    if isinstance(obj,dict) and obj.get("value"): out[q].add(obj["value"])
    return {q:sorted(v) for q,v in out.items()}

def place_meta(qids,batch=100):
    out=defaultdict(list); qs=sorted(qids)
    for i in range(0,len(qs),batch):
        vals=" ".join(f"wd:{q}" for q in qs[i:i+batch])
        q=f"""SELECT ?item ?pob ?coord WHERE {{
VALUES ?item {{ {vals} }}
OPTIONAL {{ ?item wdt:P19 ?pob . OPTIONAL {{ ?pob wdt:P625 ?coord . }} }}
}}"""
        for x in FORBIDDEN: assert x not in q
        data=req(SPARQL,{"query":q,"format":"json"})
        for row in data.get("results",{}).get("bindings",[]):
            item=row.get("item",{}).get("value","").rsplit("/",1)[-1]
            pob=row.get("pob",{}).get("value","").rsplit("/",1)[-1]
            coord=row.get("coord",{}).get("value","")
            lat=lon=None
            m=re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)",coord)
            if m: lon=float(m.group(1)); lat=float(m.group(2))
            if re.fullmatch(r"Q\d+",item):
                out[item].append((pob if re.fullmatch(r"Q\d+",pob) else "",lat,lon))
    return out

def place_matches(src_place,slat,slon,meta,pobtexts):
    hits=False
    for pob,lat,lon in meta:
        if place_text_match(src_place,pobtexts.get(pob,[])): hits=True
        if lat is not None and lon is not None and hav(slat,slon,lat,lon)<=50: hits=True
    return hits

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--a1",required=True); ap.add_argument("--out",required=True)
    a=ap.parse_args()
    with open(a.a1,encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
    if len(rows)!=ROWS or len({r["NUM"] for r in rows})!=ROWS: raise SystemExit("FAIL A1 rows")

    exact_dates={datetime.fromisoformat(r["DATE"]).date() for r in rows}
    bydate=candidates(exact_dates)

    # First-pass candidate universe on exact date.
    exact_by_num={r["NUM"]:bydate.get(datetime.fromisoformat(r["DATE"]).date(),set()) for r in rows}
    allq=set().union(*exact_by_num.values()) if exact_by_num else set()
    ntxt=entity_texts(allq)

    unresolved=[]
    provisional={}
    for r in rows:
        ranked=[]
        for q in exact_by_num[r["NUM"]]:
            nr,nc=name_class(r["NAME"],ntxt.get(q,[]))
            if nr: ranked.append((2,nr,q,nc)) # exact date rank = 2
        if ranked:
            best=max((x[0],x[1]) for x in ranked)
            top=[x for x in ranked if (x[0],x[1])==best]
            if len(top)==1: provisional[r["NUM"]]=top[0]
            else: unresolved.append((r,top))
        else:
            unresolved.append((r,[]))

    # +/-1 day only for records not uniquely resolved on exact date.
    plusminus_dates=set()
    for r,_ in unresolved:
        d=datetime.fromisoformat(r["DATE"]).date()
        plusminus_dates.update((d-timedelta(days=1),d+timedelta(days=1)))
    pm_bydate=candidates(plusminus_dates) if plusminus_dates else {}
    pmq=set().union(*pm_bydate.values()) if pm_bydate else set()
    pmtexts=entity_texts(pmq) if pmq else {}
    ntxt.update(pmtexts)

    # Re-rank unresolved with exact date + +/-1.
    tied={}
    for r,_ in unresolved:
        d=datetime.fromisoformat(r["DATE"]).date()
        ranked=[]
        for delta,dd in ((0,d),(-1,d-timedelta(days=1)),(1,d+timedelta(days=1))):
            qset=exact_by_num[r["NUM"]] if delta==0 else pm_bydate.get(dd,set())
            for q in qset:
                nr,nc=name_class(r["NAME"],ntxt.get(q,[]))
                if nr: ranked.append((2 if delta==0 else 1,nr,q,nc,delta))
        if not ranked: continue
        best=max((x[0],x[1]) for x in ranked)
        top=[x for x in ranked if (x[0],x[1])==best]
        if len(top)==1:
            provisional[r["NUM"]]=top[0]
        else:
            tied[r["NUM"]]=(r,top)

    # Place only tie-breaks tied highest-rank candidates.
    tied_q={x[2] for _,top in tied.values() for x in top}
    pmeta=place_meta(tied_q) if tied_q else {}
    pobq={p for arr in pmeta.values() for p,_,_ in arr if p}
    pobtexts=entity_texts(pobq) if pobq else {}

    final_tie={}
    for n,(r,top) in tied.items():
        hits=[x for x in top if place_matches(r["PLACE"],float(r["LAT"]),float(r["LON"]),pmeta.get(x[2],[]),pobtexts)]
        if len(hits)==1: final_tie[n]=hits[0]
    provisional.update(final_tie)

    fields=["NUM","link_status","QID","date_delta_days","name_match_class","candidate_count","eligible_candidate_count","first_seen_pass"]
    out=[]
    counts=defaultdict(int)
    for r in rows:
        n=r["NUM"]
        if n in provisional:
            x=provisional[n]
            # exact provisional tuple has 4 elements; reranked has 5.
            if len(x)==4:
                _,nr,q,nc=x; delta=0
            else:
                _,nr,q,nc,delta=x
            status="LINKED"; counts[status]+=1
            out.append({"NUM":n,"link_status":status,"QID":q,"date_delta_days":str(delta),
              "name_match_class":nc,"candidate_count":"","eligible_candidate_count":"","first_seen_pass":"A1_v0.1"})
        else:
            status="UNRESOLVED"; counts[status]+=1
            out.append({"NUM":n,"link_status":status,"QID":"","date_delta_days":"",
              "name_match_class":"","candidate_count":"","eligible_candidate_count":"","first_seen_pass":""})

    op=Path(a.out); op.parent.mkdir(parents=True,exist_ok=True)
    with op.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(out)
    digest=hashlib.sha256(op.read_bytes()).hexdigest()
    summ={
      "protocol":"A1_WIKIDATA_IDENTITY_LINKAGE_V0_1_FROZEN",
      "source_rows":ROWS,
      "total_linked":counts["LINKED"],
      "linked_fraction":counts["LINKED"]/ROWS,
      "status_counts":dict(sorted(counts.items())),
      "linkage_sha256":digest,
      "death_truth_accessed":False,
      "prediction_used_for_linkage":False,
      "forbidden_properties_queried":[]
    }
    op.with_suffix(".summary.json").write_text(json.dumps(summ,indent=2,sort_keys=True)+"\n")
    op.with_suffix(".sha256").write_text(f"{digest}  {op.name}\n")
    print(json.dumps(summ,indent=2,sort_keys=True),flush=True)

if __name__=="__main__": main()
