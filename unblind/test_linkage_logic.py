from pathlib import Path
import importlib.util

p = Path(__file__).resolve().parent / "link_wikidata.py"
spec = importlib.util.spec_from_file_location("linker", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def test_normalize_and_exact_token_order():
    assert m.normalize_name("Émile Dupré") == "emile dupre"
    rank, cls = m.name_class("FARGUE LOUIS", ["Louis Fargue"])
    assert (rank, cls) == (2, "EXACT_TOKEN_SIGNATURE")

def test_subset_match_with_middle_name():
    rank, cls = m.name_class("SMITH JOHN", ["John William Smith"])
    assert (rank, cls) == (1, "SUBSET_TOKEN_MATCH")

def test_too_weak_subset_rejected():
    rank, cls = m.name_class("SMITH JOHN", ["John William Peter Smith"])
    assert rank == 0

def test_rotate_first_token_to_end():
    assert m.rotate_name("FARGUE LOUIS") == "louis fargue"

def test_forbidden_properties_not_allowed():
    assert "P570" in m.FORBIDDEN_PROPERTIES
    assert "P570" not in m.ALLOWED_PROPERTIES
