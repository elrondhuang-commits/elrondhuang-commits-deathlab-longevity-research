#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,hashlib,json,math,random,re,statistics,time
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

SPARQL="https://query.wikidata.org/sparql"
UA="DeathLab-Combined-StageB/0.2"
GREGORIAN_QID="Q1985727"
LABEL_TO_ORD={"SHORT":0,"MEDIUM":1,"LONG":2}
ORD_TO_LABEL={v:k for k,v in LABEL_TO_ORD.items()}
SEED=20260820
B=10000
EXPECTED={
 "A2":{"rows":3643,"pred":"f213787a1bc950313acc4a06d6c9f952a904cdcf6540b616389f53ca7b94cdcc","link":"26b32c2b0874f236b407e9237f1f1ac20b3a9fafa8833ca6b00c0cc41251503d"},
 "A1":{"rows":2087,"pred":"6caab259e169bdaf196b0dc6096ba3c1659811206dbad7f4f87272704dc3aa0f","link":"3a39f02448a74ea9e96595f7f8e1e8d00cd193a913bf0912fc79891d73128142"}
}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def side(p):
    s=Path(p).read_text().split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}",s):raise SystemExit("bad sha sidecar")
    return s

last_req=0.0
blocked=0.0
def http(params,retries=24):
    global last_req,blocked
    data=urlencode(params).encode()
    headers={"User-Agent":UA,"Accept":"application/sparql-results+json","Content-Type":"application/x-www-form-urlencoded"}
    strikes=0
    err=None
    for i in range(retries):
        while True:
            now=time.monotonic()
            delay=max(0.0,blocked-now,3.0-(now-last_req))
            if delay<=0:break
            time.sleep(min(delay,10))
        last_req=time.monotonic()
        try:
            with urlopen(Request(SPARQL,data=data,headers=headers,method="POST"),timeout=120) as r:
                strikes=0
                return json.loads(r.read().decode())
        except HTTPError as e:
            err=e
            if e.code==429:
                strikes+=1
                ra=e.headers.get("Retry-After") if e.headers else None
                try:r=float(ra) if ra else 0
                except ValueError:r=0
                d=max(r,min(720,90*(2**min(strikes-1,3))))
                blocked=time.monotonic()+d
                print(f"P570 BACKOFF 429 {d:.0f}s",flush=True)
                continue
            if e.code not in (500,502,503,504):raise
            d=min(120,5*(2**min(i,5)));blocked=time.monotonic()+d
        except (URLError,TimeoutError,json.JSONDecodeError) as e:
            err=e;d=min(90,3*(1.7**min(i,7)));blocked=time.monotonic()+d
    raise RuntimeError(err)

def fetch_p570(qids,batch=80):
    out=defaultdict(list)
    for i in range(0,len(qids),batch):
        vals=" ".join(f"wd:{q}" for q in qids[i:i+batch])
        q=f"""SELECT ?item ?rank ?death ?precision ?calendar WHERE {{
VALUES ?item {{ {vals} }}
OPTIONAL {{
 ?item p:P570 ?statement .
 ?statement wikibase:rank ?rank ; psv:P570 ?node .
 FILTER(?rank != wikibase:DeprecatedRank)
 ?node wikibase:timeValue ?death ;
       wikibase:timePrecision ?precision ;
       wikibase:timeCalendarModel ?calendar .
}}
}}"""
        assert "P570" in q
        for f in ("P509","P20","P119"):assert f not in q
        data=http({"query":q,"format":"json"})
        for row in data.get("results",{}).get("bindings",[]):
            qid=row.get("item",{}).get("value","").rsplit("/",1)[-1]
            if not re.fullmatch(r"Q\d+",qid):continue
            if "death" not in row:
                out[qid];continue
            out[qid].append({
              "rank":re.split(r"[/#]", row["rank"]["value"])[-1],
              "death":row["death"]["value"],
              "precision":int(float(row["precision"]["value"])),
              "calendar":row["calendar"]["value"].rsplit("/",1)[-1]})
        print(f"P570 {min(i+batch,len(qids))}/{len(qids)}",flush=True)
    return out

def wd_date(v):
    if v.startswith("+"):v=v[1:]
    return datetime.fromisoformat(v.replace("Z","+00:00")).date()
def lastday(y,m):
    nxt=date(y+1,1,1) if m==12 else date(y,m+1,1)
    return (nxt-timedelta(days=1)).day
def death_interval(v,precision,calendar):
    if calendar!=GREGORIAN_QID:return None,"UNSUPPORTED_CALENDAR"
    d=wd_date(v)
    if precision==11:return (d,d),"DAY"
    if precision==10:return (date(d.year,d.month,1),date(d.year,d.month,lastday(d.year,d.month))),"MONTH"
    if precision==9:return (date(d.year,1,1),date(d.year,12,31)),"YEAR"
    return None,"UNSUPPORTED_PRECISION"
def anniversary(b,years):
    try:return b.replace(year=b.year+years)
    except ValueError:return date(b.year+years,2,28)
def classify_interval(b,lo,hi):
    if hi<b:return "INVALID_BEFORE_BIRTH"
    b32=anniversary(b,32);b64=anniversary(b,64)
    if hi<b32:return "SHORT"
    if lo>=b32 and hi<b64:return "MEDIUM"
    if lo>=b64:return "LONG"
    return "AMBIGUOUS_BOUNDARY"
def select_truth(b,stmts):
    empty={"truth_status":"NO_DEATH_TRUTH","truth_label":"","precision":"","death_min":"","death_max":"","selected_statement_count":0}
    if not stmts:return empty
    pref=[s for s in stmts if s["rank"]=="PreferredRank"]
    chosen=pref if pref else [s for s in stmts if s["rank"]=="NormalRank"]
    if not chosen:return {**empty,"truth_status":"NO_USABLE_RANK"}
    resolved=[];unsupported=[]
    for s in chosen:
        try:interval,pcls=death_interval(s["death"],s["precision"],s["calendar"])
        except Exception:unsupported.append("PARSE_ERROR");continue
        if interval is None:unsupported.append(pcls);continue
        lo,hi=interval;resolved.append((classify_interval(b,lo,hi),lo,hi,pcls))
    if not resolved:return {**empty,"truth_status":unsupported[0] if unsupported else "NO_RESOLVED_STATEMENT","selected_statement_count":len(chosen)}
    labels={x[0] for x in resolved}
    if len(labels)!=1:return {**empty,"truth_status":"AMBIGUOUS_DEATH_TRUTH","selected_statement_count":len(chosen)}
    label=next(iter(labels))
    if label not in LABEL_TO_ORD:return {**empty,"truth_status":label,"selected_statement_count":len(chosen)}
    return {"truth_status":"RESOLVED","truth_label":label,
      "precision":",".join(sorted({x[3] for x in resolved})),
      "death_min":min(x[1] for x in resolved).isoformat(),
      "death_max":max(x[2] for x in resolved).isoformat(),
      "selected_statement_count":len(chosen)}

def mae(p,t):return sum(abs(a-b) for a,b in zip(p,t))/len(p)
def acc(p,t):return sum(a==b for a,b in zip(p,t))/len(p)
def avg_ranks(v):
    order=sorted(range(len(v)),key=lambda i:v[i]);r=[0.0]*len(v);i=0
    while i<len(v):
        j=i+1
        while j<len(v) and v[order[j]]==v[order[i]]:j+=1
        a=(i+1+j)/2
        for k in range(i,j):r[order[k]]=a
        i=j
    return r
def pearson(x,y):
    if len(x)<2:return None
    mx,my=statistics.fmean(x),statistics.fmean(y)
    dx=[a-mx for a in x];dy=[b-my for b in y]
    den=math.sqrt(sum(a*a for a in dx)*sum(b*b for b in dy))
    return None if den==0 else sum(a*b for a,b in zip(dx,dy))/den
def spearman(x,y):return pearson(avg_ranks(x),avg_ranks(y))
def oracle(truth):
    return min((sum(abs(c-t) for t in truth)/len(truth),c) for c in (0,1,2))

def strat_oracle(rows):
    # rows: [(cohort,pred_ord,truth_ord)]
    total=0;n=0;labels={}
    for cohort in sorted({r[0] for r in rows}):
        rr=[r for r in rows if r[0]==cohort]
        om,oc=oracle([r[2] for r in rr])
        total+=om*len(rr);n+=len(rr);labels[cohort]=ORD_TO_LABEL[oc]
    return total/n,labels

def delta(rows):
    p=[r[1] for r in rows];t=[r[2] for r in rows]
    om,_=strat_oracle(rows)
    return mae(p,t)-om

def bootstrap(rows):
    rng=random.Random(SEED);by=defaultdict(list)
    for r in rows:by[r[0]].append(r)
    vals=[]
    for _ in range(B):
        sample=[]
        for c,rr in by.items():
            sample.extend(rr[rng.randrange(len(rr))] for __ in range(len(rr)))
        vals.append(delta(sample))
    vals.sort()
    return vals[int(.025*B)],vals[min(B-1,int(.975*B))]

def permutation(rows,obs):
    rng=random.Random(SEED);by=defaultdict(list)
    for c,p,t in rows:by[c].append([p,t])
    oracle_m,_=strat_oracle(rows);count=0
    for _ in range(B):
        pp=[];tt=[]
        for c,rr in by.items():
            truths=[x[1] for x in rr];rng.shuffle(truths)
            for x,t in zip(rr,truths):pp.append(x[0]);tt.append(t)
        d=mae(pp,tt)-oracle_m
        if d<=obs:count+=1
    return (1+count)/(B+1)

def read_map(path):
    with open(path,encoding="utf-8",newline="") as f:return {r["NUM"]:r for r in csv.DictReader(f)}

def main():
    ap=argparse.ArgumentParser()
    for c in ("a1","a2"):
        ap.add_argument(f"--{c}-birth",required=True)
        ap.add_argument(f"--{c}-pred",required=True)
        ap.add_argument(f"--{c}-pred-sha",required=True)
        ap.add_argument(f"--{c}-link",required=True)
        ap.add_argument(f"--{c}-link-sha",required=True)
        ap.add_argument(f"--{c}-link-summary",required=True)
    ap.add_argument("--out-dir",required=True);a=ap.parse_args()
    outd=Path(a.out_dir);outd.mkdir(parents=True,exist_ok=True)

    cohorts={}
    for C in ("A1","A2"):
        c=C.lower();E=EXPECTED[C]
        birth=read_map(getattr(a,f"{c}_birth"));pred=read_map(getattr(a,f"{c}_pred"));link=read_map(getattr(a,f"{c}_link"))
        if not(len(birth)==len(pred)==len(link)==E["rows"]):raise SystemExit(f"FAIL {C} row counts")
        if set(birth)!=set(pred) or set(birth)!=set(link):raise SystemExit(f"FAIL {C} NUM alignment")
        if sha(getattr(a,f"{c}_pred"))!=E["pred"] or side(getattr(a,f"{c}_pred_sha"))!=E["pred"]:raise SystemExit(f"FAIL {C} pred SHA")
        if sha(getattr(a,f"{c}_link"))!=E["link"] or side(getattr(a,f"{c}_link_sha"))!=E["link"]:raise SystemExit(f"FAIL {C} link SHA")
        s=json.load(open(getattr(a,f"{c}_link_summary"),encoding="utf-8"))
        if s.get("death_truth_accessed") is not False or s.get("prediction_used_for_linkage") is not False or s.get("forbidden_properties_queried")!=[]:raise SystemExit(f"FAIL {C} preoutcome state")
        cohorts[C]=(birth,pred,link)

    a1q={r["QID"] for r in cohorts["A1"][2].values() if r["link_status"]=="LINKED" and re.fullmatch(r"Q\d+",r["QID"] or "")}
    a2q={r["QID"] for r in cohorts["A2"][2].values() if r["link_status"]=="LINKED" and re.fullmatch(r"Q\d+",r["QID"] or "")}
    if a1q&a2q:raise SystemExit(f"FAIL-CLOSED cross-cohort duplicate linked QID count={len(a1q&a2q)}")

    premax=sum(1 for C,(birth,pred,link) in cohorts.items() for n in birth if link[n]["link_status"]=="LINKED" and pred[n]["prediction_label"] in LABEL_TO_ORD)
    if premax!=1334:raise SystemExit(f"FAIL-CLOSED pre-unblind covered max drift {premax} != 1334")

    p570=fetch_p570(sorted(a1q|a2q))
    truth_rows=[];eval_rows=[];cohort_reports={}
    for C,(birth,pred,link) in cohorts.items():
        linked_n=sum(r["link_status"]=="LINKED" for r in link.values())
        resolved=0;covered=0;status=Counter();labels=Counter()
        for n in sorted(birth,key=lambda x:int(x)):
            lr=link[n]
            if lr["link_status"]!="LINKED":
                tr={"truth_status":"NOT_LINKED","truth_label":"","precision":"","death_min":"","death_max":"","selected_statement_count":0}
            else:
                tr=select_truth(datetime.fromisoformat(birth[n]["DATE"]).date(),p570.get(lr["QID"],[]))
            row={"cohort":C,"NUM":n,"QID":lr.get("QID",""),"link_status":lr["link_status"],**tr}
            truth_rows.append(row);status[tr["truth_status"]]+=1
            if tr["truth_status"]=="RESOLVED":
                resolved+=1;labels[tr["truth_label"]]+=1
                if pred[n]["prediction_label"] in LABEL_TO_ORD:
                    covered+=1
                    eval_rows.append((C,LABEL_TO_ORD[pred[n]["prediction_label"]],LABEL_TO_ORD[tr["truth_label"]],n,pred[n]["prediction_label"],tr["truth_label"]))
        cohort_reports[C]={"N_total":len(birth),"N_linked":linked_n,"N_truth_resolved":resolved,"Ncovered_eval":covered,
          "truth_status_counts":dict(sorted(status.items())),"truth_label_counts":dict(sorted(labels.items()))}

    tf=outd/"COMBINED_death_truth.csv"
    fields=["cohort","NUM","QID","link_status","truth_status","truth_label","precision","death_min","death_max","selected_statement_count"]
    with tf.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(truth_rows)
    (outd/"COMBINED_death_truth.sha256").write_text(f"{sha(tf)}  {tf.name}\n")

    if not eval_rows:raise SystemExit("NO covered truth cases")
    metric_rows=[r[:3] for r in eval_rows]
    po=[r[1] for r in metric_rows];to=[r[2] for r in metric_rows]
    ch_mae=mae(po,to);ch_acc=acc(po,to);rho=spearman(po,to)
    om,olabels=strat_oracle(metric_rows);obs=ch_mae-om
    lo,hi=bootstrap(metric_rows);pp=permutation(metric_rows,obs)
    confusion={p:{t:0 for t in LABEL_TO_ORD} for p in LABEL_TO_ORD}
    for C,p,t,n,pl,tl in eval_rows:confusion[pl][tl]+=1

    for C in cohort_reports:
        rr=[r for r in metric_rows if r[0]==C]
        if rr:
            p=[r[1] for r in rr];t=[r[2] for r in rr];cohort_reports[C]["challenger_MAE"]=mae(p,t)
            co,_=oracle(t);cohort_reports[C]["best_constant_oracle_MAE"]=co
            cohort_reports[C]["delta_MAE"]=mae(p,t)-co
            cohort_reports[C]["accuracy"]=acc(p,t)
            cohort_reports[C]["spearman_rho"]=spearman(p,t)

    N=len(metric_rows)
    passed=N>=1000 and obs<0 and hi<0 and pp<0.05
    report={
      "protocol":"A1_A2_COMBINED_DEATH_TRUTH_UNBLIND_EFFICACY_V0_2_FROZEN",
      "death_truth_sha256":sha(tf),
      "preunblind_max_covered_eval":1334,
      "Ncovered_eval":N,
      "formal_N_ge_1000":N>=1000,
      "cohorts":cohort_reports,
      "challenger":{"pooled_ordinal_MAE":ch_mae,"pooled_accuracy":ch_acc,"pooled_spearman_rho":rho,"confusion_pred_rows_truth_cols":confusion},
      "cohort_stratified_best_constant_oracle":{"labels":olabels,"pooled_ordinal_MAE":om},
      "primary_delta_MAE":obs,
      "stratified_bootstrap95_primary_delta":[lo,hi],
      "within_cohort_permutation_p_one_sided":pp,
      "bootstrap_iterations":B,"permutation_iterations":B,"seed":SEED,
      "first_signal_gate_PASS":passed,
      "claim_boundary":"PASS means evidence of ordinal lifespan signal in the frozen linked/P570-resolved A1+A2 subset; not proof of deterministic individual lifespan."
    }
    rp=outd/"COMBINED_EFFICACY_REPORT.json";rp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    (outd/"COMBINED_EFFICACY_REPORT.sha256").write_text(f"{sha(rp)}  {rp.name}\n")
    print(json.dumps(report,indent=2,sort_keys=True))
if __name__=="__main__":main()
