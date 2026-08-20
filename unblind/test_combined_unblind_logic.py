from pathlib import Path
import importlib.util
from datetime import date
p=Path(__file__).resolve().parent/"combined_unblind_and_score.py"
s=importlib.util.spec_from_file_location("m",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def test_anniversary(): assert m.anniversary(date(2000,2,29),1)==date(2001,2,28)
def test_boundaries():
    b=date(1900,1,1)
    assert m.classify_interval(b,date(1931,12,31),date(1931,12,31))=="SHORT"
    assert m.classify_interval(b,date(1932,1,1),date(1963,12,31))=="MEDIUM"
    assert m.classify_interval(b,date(1964,1,1),date(1964,1,1))=="LONG"
def test_missing_not_long():
    r=m.select_truth(date(1900,1,1),[])
    assert r["truth_status"]=="NO_DEATH_TRUTH" and r["truth_label"]==""
def test_stratified_oracle():
    rows=[("A1",0,0),("A1",1,0),("A2",2,2),("A2",1,2)]
    om,l=m.strat_oracle(rows)
    assert abs(om-0.0)<1e-12 and l=={"A1":"SHORT","A2":"LONG"}
def test_stratification_blocks_cohort_only_signal():
    # Challenger merely identifies cohort; within each cohort it has no individual information.
    rows=[("A1",0,0),("A1",0,1),("A2",2,1),("A2",2,2)]
    assert abs(m.delta(rows))<1e-12
def test_truth_precision():
    x,c=m.death_interval("+1950-04-12T00:00:00Z",11,m.GREGORIAN_QID)
    assert x==(date(1950,4,12),date(1950,4,12)) and c=="DAY"


def test_wikidata_rank_uri_shape():
    import re
    assert re.split(r"[/#]", "http://wikiba.se/ontology#NormalRank")[-1] == "NormalRank"
    assert re.split(r"[/#]", "http://wikiba.se/ontology#PreferredRank")[-1] == "PreferredRank"

def test_normal_rank_statement_is_usable():
    s=[{
        "rank":"NormalRank",
        "death":"+1970-01-01T00:00:00Z",
        "precision":11,
        "calendar":m.GREGORIAN_QID
    }]
    r=m.select_truth(date(1900,1,1),s)
    assert r["truth_status"]=="RESOLVED"
    assert r["truth_label"]=="LONG"
