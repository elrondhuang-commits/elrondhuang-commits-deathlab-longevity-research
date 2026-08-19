from pathlib import Path
import importlib.util
p=Path(__file__).resolve().parent/"augment_v0_3_fuzzy.py"
s=importlib.util.spec_from_file_location("m",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_exact(): assert m.name_class("FARGUE LOUIS",["Louis Fargue"])[0]==4
def test_initial(): assert m.name_class("DUPONT MARCEL",["Maurice Dupont"])[0]==2
def test_wrong_initial(): assert m.name_class("DUPONT MARCEL",["Jean Dupont"])[0]==0
def test_edit1(): assert m.name_class("SCHMIDT HANS",["Hans Schmitt"])[0]==1
def test_place(): assert m.place_match("München",["Munchen"])
def test_tie(): assert m.resolve("DUPONT MARCEL","Nowhere",{"Q1","Q2"},{"Q1":["Maurice Dupont"],"Q2":["Michel Dupont"]},{})=="AMBIGUOUS"
def test_place_break():
    h=m.resolve("DUPONT MARCEL","Paris",{"Q1","Q2"},{"Q1":["Maurice Dupont"],"Q2":["Michel Dupont"]},{"Q1":["Paris"],"Q2":["Lyon"]})
    assert h[1]=="Q1"
