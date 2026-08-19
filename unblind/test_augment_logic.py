from pathlib import Path
import importlib.util

p=Path(__file__).resolve().parent/"augment_by_birthdate.py"
spec=importlib.util.spec_from_file_location("a",p)
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)

def test_name_rules_match_v01():
    assert a.normalize_name("Émile Dupré")=="emile dupre"
    assert a.name_class("FARGUE LOUIS",["Louis Fargue"])==(2,"EXACT_TOKEN_SIGNATURE")
    assert a.name_class("SMITH JOHN",["John William Smith"])==(1,"SUBSET_TOKEN_MATCH")

def test_resolve_exact_beats_pm1():
    cand={"Q1":1,"Q2":0}
    texts={"Q1":["John Smith"],"Q2":["John Smith"]}
    hit,n=a.resolve_one("SMITH JOHN",cand,texts)
    assert hit[2]=="Q2"

def test_exact_name_beats_subset_same_date():
    cand={"Q1":0,"Q2":0}
    texts={"Q1":["John William Smith"],"Q2":["John Smith"]}
    hit,n=a.resolve_one("SMITH JOHN",cand,texts)
    assert hit[2]=="Q2"

def test_tied_top_is_ambiguous():
    cand={"Q1":0,"Q2":0}
    texts={"Q1":["John Smith"],"Q2":["Smith John"]}
    hit,n=a.resolve_one("SMITH JOHN",cand,texts)
    assert hit=="AMBIGUOUS"

def test_no_name_match_is_none():
    hit,n=a.resolve_one("SMITH JOHN",{"Q1":0},{"Q1":["Marie Curie"]})
    assert hit is None
