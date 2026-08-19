#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,math,re,threading,time,unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

SPARQL="https://query.wikidata.org/sparql"
API="https://www.wikidata.org/w/api.php"
UA="DeathLab-Longevity-Research/0.4"
BASE_SHA="94487b31133d8c198adad2b7c2e2c48b405286fb4003295b4a64abe2e272b646"
N=3643
FORBIDDEN=("P570","P509","P20","P119")
LANGS="en|fr|de|it|es|nl|pt|pl|ru|sv|no|da|cs|hu|ro|el|la|mul"

def norm(s):
    s=unicodedata.normalize("NFKD",s or "")
    s="".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())
def toks(s): return tuple(norm(s).split())
def sig(s): return tuple(sorted(toks(s)))

def ed1(a,b):
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

def name_strength(source,texts):
    st=toks(source); ss=sig(source); src=set(st); best=(0,"NONE")
    for text in texts:
        ct=toks(text); cs=set(ct)
        if not src or not cs:continue
        if ss==tuple(sorted(ct)): best=max(best,(4,"EXACT_TOKEN_SIGNATURE"));continue
        smaller=min(len(src),len(cs));larger=max(len(src),len(cs));shared=len(src&cs)
        if (src.issubset(cs) or cs.issubset(src)) and shared>=2 and smaller/larger>=2/3:
            best=max(best,(3,"SUBSET_TOKEN_MATCH"))
    if best[0]>=3 or not st:return best
    surname=st[0]
    for text in texts:
        ct=toks(text)
        if not ct:continue
        if surname in (ct[0],ct[-1]):
            best=max(best,(2,"SURNAME_EXACT"))
        # two distinct source tokens approximately matching two distinct candidate tokens
        matches=0; used=set()
        for a in st:
            found=None
            for j,b in enumerate(ct):
                if j not in used and len(a)>=4 and len(b)>=4 and ed1(a,b):
                    found=j;break
            if found is not None:
                used.add(found);matches+=1
        if matches>=2:
            best=max(best,(1,"TWO_TOKEN_EDIT1"))
    return best

def hav(lat1,lon1,lat2,lon2):
    R=6371.0088
    a1,a2=math.radians(lat1),math.radians(lat2)
    da=math.radians(lat2-lat1);do=math.radians(lon2-lon1)
    x=math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(do/2)**2
    return 2*R*math.asin(math.sqrt(x))

def text_place_match(a,texts):
    a=norm(a); aset=set(a.split())
    if not a:return False
    for x in texts:
        b=norm(x); bset=set(b.split())
        if not b:continue
        if tuple(sorted(aset))==tuple(sorted(bset)):return True
        if aset and bset and (aset.issubset(bset) or bset.issubset(aset)):return True
        if len(a)>=4 and len(b)>=4 and (a in b or b in a):return True
    return False

lock=threading.Lock();last=0.0;blocked=0.0;MIN=.55
def gate():
    global last
    while True:
        with lock:
            now=time.monotonic();d=max(0.0,blocked-now,MIN-(now-last))
            if d<=0:last=now;return
        time.sleep(min(d,5))
def block(sec):
    global blocked
    with lock:blocked=max(blocked,time.monotonic()+sec)
def req(url,params,retries=18):
    data=urlencode(params).encode();headers={"User-Agent":UA,"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded"}
    last_err=None
    for attempt in range(retries):
        gate()
        try:
            with urlopen(Request(url,data=data,headers=headers,method="POST"),timeout=90) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            last_err=e
            if e.code not in (429,500,502,503,504):raise
            ra=e.headers.get("Retry-After") if e.headers else None
            try:d=float(ra) if ra else (60 if e.code==429 else min(120,2**min(attempt,7)))
            except ValueError:d=60
            block(d);time.sleep(min(d,5))
        except (URLError,TimeoutError,json.JSONDecodeError) as e:
            last_err=e;d=min(60,1.5**attempt);block(d);time.sleep(min(d,5))
    raise RuntimeError(last_err)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def candidates(dates,batch=20):
    out=defaultdict(set);ds=sorted(dates)
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
        for f in FORBIDDEN:assert f not in q
        data=req(SPARQL,{"query":q,"format":"json"})
        for row in data.get("results",{}).get("bindings",[]):
            qid=row.get("item",{}).get("value","").rsplit("/",1)[-1]
            dv=row.get("dob",{}).get("value","")
            if not re.fullmatch(r"Q\d+",qid):continue
            try:d=datetime.fromisoformat(dv.lstrip("+").replace("Z","+00:00")).date()
            except ValueError:continue
            out[d].add(qid)
    return out

def entity_texts(qids,batch=50):
    out=defaultdict(set);qs=sorted(qids)
    for i in range(0,len(qs),batch):
        data=req(API,{"action":"wbgetentities","ids":"|".join(qs[i:i+batch]),"props":"labels|aliases",
          "languages":LANGS,"languagefallback":1,"format":"json","formatversion":2,"maxlag":5})
        for q,e in data.get("entities",{}).items():
            for obj in (e.get("labels") or {}).values():
                if isinstance(obj,dict) and obj.get("value"):out[q].add(obj["value"])
            for arr in (e.get("aliases") or {}).values():
                for obj in arr or []:
                    if isinstance(obj,dict) and obj.get("value"):out[q].add(obj["value"])
    return {q:sorted(v) for q,v in out.items()}

def place_meta(qids,batch=100):
    # candidate -> [(pob qid, lat, lon)]
    out=defaultdict(list);qs=sorted(qids)
    for i in range(0,len(qs),batch):
        vals=" ".join(f"wd:{q}" for q in qs[i:i+batch])
        q=f"""SELECT ?item ?pob ?coord WHERE {{
VALUES ?item {{ {vals} }}
OPTIONAL {{
 ?item wdt:P19 ?pob .
 OPTIONAL {{ ?pob wdt:P625 ?coord . }}
}}
}}"""
        for f in FORBIDDEN:assert f not in q
        data=req(SPARQL,{"query":q,"format":"json"})
        for row in data.get("results",{}).get("bindings",[]):
            item=row.get("item",{}).get("value","").rsplit("/",1)[-1]
            pob=row.get("pob",{}).get("value","").rsplit("/",1)[-1]
            coord=row.get("coord",{}).get("value","")
            lat=lon=None
            m=re.match(r"Point\(([-0-9.]+) ([-0-9.]+)\)",coord)
            if m:lon=float(m.group(1));lat=float(m.group(2))
            if re.fullmatch(r"Q\d+",item):
                out[item].append((pob if re.fullmatch(r"Q\d+",pob) else "",lat,lon))
    return out

def place_strength(src_place,slat,slon,meta,pobtexts):
    best=(0,"NONE")
    for pob,lat,lon in meta:
        txt=pobtexts.get(pob,[])
        if text_place_match(src_place,txt):best=max(best,(2,"PLACE_TEXT"))
        if lat is not None and lon is not None:
            d=hav(slat,slon,lat,lon)
            if d<=20:best=max(best,(3,"COORD_20KM"))
            elif d<=50:best=max(best,(2,"COORD_50KM"))
    return best

def resolve(src_name,src_place,slat,slon,qids,ntxt,pmeta,pobtexts):
    ranked=[]
    for q in qids:
        ps,pcls=place_strength(src_place,slat,slon,pmeta.get(q,[]),pobtexts)
        ns,ncls=name_strength(src_name,ntxt.get(q,[]))
        if ps>=1 and ns>=1:ranked.append((ps,ns,q,pcls,ncls))
    if not ranked:return None
    best=max((x[0],x[1]) for x in ranked)
    top=[x for x in ranked if (x[0],x[1])==best]
    if len(top)!=1:return "AMBIGUOUS"
    return top[0]

def main():
    ap=argparse.ArgumentParser()
    for x in ("a2","base_links","base_links_sha","base_summary","out"):ap.add_argument("--"+x.replace("_","-"),dest=x,required=True)
    a=ap.parse_args()
    bp=Path(a.base_links);side=Path(a.base_links_sha).read_text().split()[0]
    if side!=BASE_SHA or sha(bp)!=BASE_SHA:raise SystemExit("FAIL base SHA")
    bs=json.loads(Path(a.base_summary).read_text())
    if bs.get("death_truth_accessed") is not False or bs.get("prediction_used_for_linkage") is not False or bs.get("forbidden_properties_queried")!=[]:
        raise SystemExit("FAIL base state")
    with open(a.a2,encoding="utf-8",newline="") as f:src=list(csv.DictReader(f))
    with bp.open(encoding="utf-8",newline="") as f:base=list(csv.DictReader(f))
    if len(src)!=N or len(base)!=N:raise SystemExit("rows")
    S={r["NUM"]:r for r in src};B={r["NUM"]:r for r in base}
    unresolved={n for n,r in B.items() if r["link_status"]!="LINKED"}
    dates={datetime.fromisoformat(S[n]["DATE"]).date() for n in unresolved}
    bydate=candidates(dates)
    bynum={n:bydate.get(datetime.fromisoformat(S[n]["DATE"]).date(),set()) for n in unresolved}
    allq=set().union(*bynum.values()) if bynum else set()
    ntxt=entity_texts(allq);pmeta=place_meta(allq)
    pobq={p for arr in pmeta.values() for p,_,_ in arr if p}
    pobtexts=entity_texts(pobq) if pobq else {}
    new={};amb=0;classes=defaultdict(int);places=defaultdict(int)
    for n in unresolved:
        r=S[n]
        hit=resolve(r["NAME"],r["PLACE"],float(r["LAT"]),float(r["LON"]),bynum[n],ntxt,pmeta,pobtexts)
        if hit is None:continue
        if hit=="AMBIGUOUS":amb+=1;continue
        ps,ns,q,pcls,ncls=hit;new[n]=(q,pcls,ncls);classes[ncls]+=1;places[pcls]+=1
    fields=["NUM","link_status","QID","date_delta_days","name_match_class","candidate_count","eligible_candidate_count","first_seen_pass"]
    final=[]
    for r in src:
        n=r["NUM"];br=B[n]
        if br["link_status"]=="LINKED":final.append({k:br.get(k,"") for k in fields})
        elif n in new:
            q,pcls,ncls=new[n]
            final.append({"NUM":n,"link_status":"LINKED","QID":q,"date_delta_days":"0","name_match_class":ncls,
             "candidate_count":str(len(bynum[n])),"eligible_candidate_count":"1","first_seen_pass":"v0.4:"+pcls})
        else:final.append({k:br.get(k,"") for k in fields})
    op=Path(a.out);op.parent.mkdir(parents=True,exist_ok=True)
    with op.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(final)
    dig=sha(op);counts=defaultdict(int)
    for r in final:counts[r["link_status"]]+=1
    summ={"protocol":"A2_WIKIDATA_IDENTITY_LINKAGE_AUGMENT_V0_4_FINAL_A2_FROZEN","base_linkage_sha256":BASE_SHA,
      "linkage_sha256":dig,"source_rows":N,"base_linked":bs["total_linked"],
      "new_linked":counts["LINKED"]-bs["total_linked"],"total_linked":counts["LINKED"],
      "linked_fraction":counts["LINKED"]/N,"new_name_classes":dict(sorted(classes.items())),
      "new_place_classes":dict(sorted(places.items())),"ambiguous_v0_4":amb,
      "status_counts":dict(sorted(counts.items())),"death_truth_accessed":False,
      "prediction_used_for_linkage":False,"forbidden_properties_queried":[]}
    op.with_suffix(".summary.json").write_text(json.dumps(summ,indent=2,sort_keys=True)+"\n")
    op.with_suffix(".sha256").write_text(f"{dig}  {op.name}\n")
    print(json.dumps(summ,indent=2,sort_keys=True),flush=True)
if __name__=="__main__":main()
