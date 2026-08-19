from pathlib import Path
import importlib.util
import hashlib

def load(name):
    p = Path(__file__).resolve().parents[1] / "scripts" / name
    s = importlib.util.spec_from_file_location(name.replace(".py",""), p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m

def test_materializer_git_blob_formula():
    m = load("materialize_a1.py")
    data = b"hello\n"
    expected = hashlib.sha1(b"blob 6\0hello\n").hexdigest()
    assert m.git_blob_sha1(data) == expected

def test_a1_constants():
    m = load("materialize_a1.py")
    assert m.EXPECTED_ROWS == 2088
    assert m.EXPECTED_HEADER == ["NUM","NAME","OCCU","DATE","PLACE","CY","C2","LON","LAT","1955"]

def test_no_outcome_header():
    m = load("materialize_a1.py")
    assert all("death" not in x.lower() for x in m.EXPECTED_HEADER)
