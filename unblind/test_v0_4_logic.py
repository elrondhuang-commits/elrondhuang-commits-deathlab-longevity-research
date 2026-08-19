from pathlib import Path
import importlib.util
p=Path(__file__).resolve().parent/"augment_v0_4_place.py"
s=importlib.util.spec_from_file_location("m",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_name_exact(): assert m.name_strength("FARGUE LOUIS",["Louis Fargue"])[0]==4
def test_surname(): assert m.name_strength("DUPONT MARCEL",["Jean Dupont"])[0]==2
def test_two_edit(): assert m.name_strength("SCHMIDT HANS",["Hans Schmitt"])[0]>=1
def test_distance(): assert m.hav(0,0,0,0)==0
def test_place_text(): assert m.text_place_match("München",["Munchen"])
def test_place_coord20(): assert m.place_strength("x",0,0,[("",0.1,0.1)],{})[0]>=3
def test_requires_both():
    assert m.resolve("Smith John","Paris",48.8566,2.3522,{"Q1"},{"Q1":["John Smith"]},{"Q1":[]},{}) is None
