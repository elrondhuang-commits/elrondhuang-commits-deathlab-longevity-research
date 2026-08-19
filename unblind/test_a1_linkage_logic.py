from pathlib import Path
import importlib.util
p=Path(__file__).resolve().parent/"link_a1_wikidata.py"
s=importlib.util.spec_from_file_location("m",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_exact(): assert m.name_class("FARGUE LOUIS",["Louis Fargue"])[0]==2
def test_subset(): assert m.name_class("VAN DEN BERG JAN",["Jan van den Berg"])[0]>=1
def test_reject_single_token(): assert m.name_class("SMITH JOHN",["Smith"])[0]==0
def test_place_text(): assert m.place_text_match("München",["Munchen"])
def test_distance_zero(): assert m.hav(1,2,1,2)==0
