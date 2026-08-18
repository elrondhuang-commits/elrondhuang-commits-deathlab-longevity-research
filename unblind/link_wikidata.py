#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import threading
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "DeathLab-Longevity-Research/0.1.1 (https://github.com/elrondhuang-commits/elrondhuang-commits-deathlab-longevity-research)"

EXPECTED_ROWS = 3643
EXPECTED_HEADER = ["NUM","NAME","OCCU","DATE","PLACE","CY","C2","LON","LAT","1955"]
FROZEN_PREDICTION_SHA256 = "f213787a1bc950313acc4a06d6c9f952a904cdcf6540b616389f53ca7b94cdcc"

LANGUAGES = ("en", "fr", "de", "it")
SEARCH_LIMIT = 10
HUMAN_QID = "Q5"

# Strictly outcome-blind properties allowed in Stage A.
ALLOWED_PROPERTIES = ("P31", "P569")
FORBIDDEN_PROPERTIES = ("P570", "P509", "P20", "P119")


# Wikimedia 2026 global API rate limits apply across Action/REST APIs.
# Keep a single process-wide gate so worker threads cannot burst past the service.
_rate_lock = threading.Lock()
_last_request_at = 0.0
_blocked_until = 0.0
MIN_REQUEST_INTERVAL_SECONDS = 0.50  # <= ~120 req/min, below 200 req/min User-Agent-only ceiling.

def _rate_wait():
    global _last_request_at
    while True:
        with _rate_lock:
            now = time.monotonic()
            wait_for = max(
                0.0,
                _blocked_until - now,
                MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at),
            )
            if wait_for <= 0:
                _last_request_at = now
                return
        time.sleep(min(wait_for, 5.0))

def _rate_block(seconds: float):
    global _blocked_until
    with _rate_lock:
        _blocked_until = max(_blocked_until, time.monotonic() + max(0.0, seconds))

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def http_json(url: str, params: dict | None = None, *, method: str = "GET", timeout: int = 60, retries: int = 20):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }
    body = None
    request_url = url
    params = dict(params or {})

    # Action API etiquette: non-interactive clients should use maxlag.
    if url == API:
        params.setdefault("maxlag", 5)

    if params:
        encoded = urlencode(params).encode("utf-8")
        if method == "POST":
            body = encoded
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        else:
            request_url = url + "?" + encoded.decode("ascii")

    last = None
    for attempt in range(retries):
        _rate_wait()
        try:
            req = Request(request_url, data=body, headers=headers, method=method)
            with urlopen(req, timeout=timeout) as r:
                raw = r.read()
                # urllib normally handles neither gzip nor deflate automatically.
                encoding = (r.headers.get("Content-Encoding") or "").lower()
                if encoding == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                elif encoding == "deflate":
                    import zlib
                    raw = zlib.decompress(raw)
                return json.loads(raw.decode("utf-8"))
        except HTTPError as e:
            last = e
            code = getattr(e, "code", None)
            if code not in (429, 500, 502, 503, 504):
                raise

            retry_after = None
            try:
                retry_after = e.headers.get("Retry-After")
            except Exception:
                pass

            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = 60.0
            elif code == 429:
                delay = max(60.0, min(300.0, 2.0 ** min(attempt, 8)))
            else:
                delay = min(120.0, 2.0 ** min(attempt, 7))

            # One 429 pauses ALL worker threads, not just the failing one.
            _rate_block(delay)
            print(
                f"WIKIMEDIA_BACKOFF code={code} attempt={attempt+1}/{retries} "
                f"delay={delay:.1f}s",
                flush=True,
            )
            time.sleep(min(delay, 5.0))  # remaining wait is enforced by _rate_wait()
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            delay = min(60.0, 1.5 ** attempt)
            _rate_block(delay)
            time.sleep(min(delay, 5.0))

    raise RuntimeError(f"HTTP failed after retries: {last}")

def normalize_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())

def tokens(s: str) -> tuple[str, ...]:
    return tuple(t for t in normalize_name(s).split() if t)

def rotate_name(s: str) -> str:
    ts = list(tokens(s))
    if len(ts) < 2:
        return normalize_name(s)
    return " ".join(ts[1:] + ts[:1])

def token_signature(s: str) -> tuple[str, ...]:
    return tuple(sorted(tokens(s)))

def name_class(source_name: str, candidate_texts: list[str]) -> tuple[int, str]:
    src = set(tokens(source_name))
    src_sig = token_signature(source_name)
    best = (0, "NO_NAME_MATCH")
    for text in candidate_texts:
        cand_t = tokens(text)
        cand = set(cand_t)
        if not src or not cand:
            continue
        if src_sig == tuple(sorted(cand_t)):
            best = max(best, (2, "EXACT_TOKEN_SIGNATURE"))
            continue
        smaller = min(len(src), len(cand))
        larger = max(len(src), len(cand))
        shared = len(src & cand)
        subset = src.issubset(cand) or cand.issubset(src)
        if subset and shared >= 2 and smaller / larger >= (2/3):
            best = max(best, (1, "SUBSET_TOKEN_MATCH"))
    return best

def parse_source_date(s: str):
    dt = datetime.fromisoformat(s)
    return dt.date()

def search_one(query: str, language: str) -> list[dict]:
    data = http_json(API, {
        "action": "wbsearchentities",
        "search": query,
        "language": language,
        "uselang": language,
        "type": "item",
        "limit": SEARCH_LIMIT,
        "format": "json",
        "formatversion": 2,
    })
    out = []
    for item in data.get("search", []):
        qid = item.get("id")
        if not qid or not re.fullmatch(r"Q\d+", qid):
            continue
        # Deliberately project only identity text and QID. Do not retain description.
        texts = []
        for key in ("label",):
            v = item.get(key)
            if isinstance(v, str) and v:
                texts.append(v)
        match = item.get("match") or {}
        if isinstance(match, dict):
            v = match.get("text")
            if isinstance(v, str) and v:
                texts.append(v)
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            texts.extend(v for v in aliases if isinstance(v, str) and v)
        out.append({"qid": qid, "texts": sorted(set(texts))})
    return out

def sparql_metadata(qids: list[str], batch_size: int = 120) -> dict:
    meta = defaultdict(lambda: {"instances": set(), "births": []})
    for start in range(0, len(qids), batch_size):
        batch = qids[start:start+batch_size]
        values = " ".join(f"wd:{q}" for q in batch)
        query = f"""
SELECT ?item ?instance ?dob ?dobPrecision WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P31 ?instance . }}
  OPTIONAL {{
    ?item p:P569 ?birthStatement .
    ?birthStatement psv:P569 ?birthNode .
    ?birthNode wikibase:timeValue ?dob ;
               wikibase:timePrecision ?dobPrecision .
  }}
}}
"""
        for forbidden in FORBIDDEN_PROPERTIES:
            assert forbidden not in query, f"FORBIDDEN PROPERTY IN STAGE A QUERY: {forbidden}"
        data = http_json(SPARQL, {"query": query, "format": "json"}, method="POST", timeout=90)
        for row in data.get("results", {}).get("bindings", []):
            item_uri = row.get("item", {}).get("value", "")
            qid = item_uri.rsplit("/", 1)[-1]
            if not re.fullmatch(r"Q\d+", qid):
                continue
            inst_uri = row.get("instance", {}).get("value")
            if inst_uri:
                meta[qid]["instances"].add(inst_uri.rsplit("/", 1)[-1])
            dob = row.get("dob", {}).get("value")
            precision = row.get("dobPrecision", {}).get("value")
            if dob and precision:
                try:
                    meta[qid]["births"].append((dob, int(float(precision))))
                except ValueError:
                    pass
    return meta

def parse_wikidata_day(value: str):
    # Wikidata time values are ISO-like; strip leading '+' used for CE years.
    v = value.strip()
    if v.startswith("+"):
        v = v[1:]
    # Day-precision linkage only supports positive CE dates for this cohort.
    return datetime.fromisoformat(v.replace("Z", "+00:00")).date()

def resolve_record(source: dict, candidates: dict[str, dict], meta: dict) -> dict:
    src_date = parse_source_date(source["DATE"])
    eligible = []

    for qid, cand in candidates.items():
        m = meta.get(qid, {})
        if HUMAN_QID not in m.get("instances", set()):
            continue

        date_best = None
        for dob_value, precision in m.get("births", []):
            if precision < 11:
                continue
            try:
                d = parse_wikidata_day(dob_value)
            except ValueError:
                continue
            delta = abs((d - src_date).days)
            if delta <= 1 and (date_best is None or delta < date_best):
                date_best = delta
        if date_best is None:
            continue

        n_rank, n_class = name_class(source["NAME"], cand["texts"])
        if n_rank < 1:
            continue

        # Lexicographic rank. Larger is better.
        date_rank = 2 if date_best == 0 else 1
        rank = (date_rank, n_rank)
        eligible.append({
            "qid": qid,
            "rank": rank,
            "date_delta_days": date_best,
            "name_match_class": n_class,
            "first_seen_pass": cand["first_seen_pass"],
        })

    if not candidates:
        return {
            "link_status": "NO_SEARCH_HIT", "QID": "", "date_delta_days": "",
            "name_match_class": "", "candidate_count": 0, "eligible_candidate_count": 0,
            "first_seen_pass": ""
        }
    if not eligible:
        return {
            "link_status": "NO_IDENTITY_MATCH", "QID": "", "date_delta_days": "",
            "name_match_class": "", "candidate_count": len(candidates), "eligible_candidate_count": 0,
            "first_seen_pass": ""
        }

    eligible.sort(key=lambda x: x["rank"], reverse=True)
    top_rank = eligible[0]["rank"]
    top = [x for x in eligible if x["rank"] == top_rank]
    if len(top) != 1:
        return {
            "link_status": "AMBIGUOUS", "QID": "", "date_delta_days": "",
            "name_match_class": "", "candidate_count": len(candidates),
            "eligible_candidate_count": len(eligible), "first_seen_pass": ""
        }

    hit = top[0]
    return {
        "link_status": "LINKED",
        "QID": hit["qid"],
        "date_delta_days": hit["date_delta_days"],
        "name_match_class": hit["name_match_class"],
        "candidate_count": len(candidates),
        "eligible_candidate_count": len(eligible),
        "first_seen_pass": hit["first_seen_pass"],
    }

def run_search_pass(records, unresolved_nums, all_candidates, query_variant, language, workers):
    todo = []
    for r in records:
        num = r["NUM"]
        if num not in unresolved_nums:
            continue
        query = normalize_name(r["NAME"]) if query_variant == "raw" else rotate_name(r["NAME"])
        if query:
            todo.append((num, query))
    label = f"{query_variant}:{language}"
    print(f"SEARCH PASS {label}: {len(todo)} records", flush=True)

    def task(item):
        num, query = item
        return num, search_one(query, language)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(task, x) for x in todo]
        done = 0
        for fut in as_completed(futs):
            num, results = fut.result()
            target = all_candidates[num]
            for c in results:
                qid = c["qid"]
                if qid not in target:
                    target[qid] = {"texts": set(), "first_seen_pass": label}
                target[qid]["texts"].update(c["texts"])
            done += 1
            if done % 250 == 0:
                print(f"  {label}: {done}/{len(todo)}", flush=True)

def materialize_meta(all_candidates):
    qids = sorted({qid for d in all_candidates.values() for qid in d})
    print(f"FETCH IDENTITY-ONLY METADATA: {len(qids)} unique QIDs", flush=True)
    return sparql_metadata(qids)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a2_csv")
    ap.add_argument("output_csv")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    args.workers = max(1, min(args.workers, 2))  # Wikimedia-friendly hard cap

    src = Path(args.a2_csv)
    out = Path(args.output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)

    with src.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != EXPECTED_HEADER:
            raise SystemExit(f"FAIL-CLOSED header mismatch: {reader.fieldnames}")
        records = list(reader)

    if len(records) != EXPECTED_ROWS:
        raise SystemExit(f"FAIL-CLOSED rows {len(records)} != {EXPECTED_ROWS}")
    nums = [r["NUM"] for r in records]
    if len(set(nums)) != EXPECTED_ROWS:
        raise SystemExit("FAIL-CLOSED duplicate NUM")

    all_candidates = defaultdict(dict)
    resolutions = {r["NUM"]: {"link_status": "UNRESOLVED"} for r in records}

    passes = []
    for variant in ("raw", "rotate"):
        for lang in LANGUAGES:
            passes.append((variant, lang))

    meta = {}
    for variant, lang in passes:
        unresolved = {n for n, x in resolutions.items() if x["link_status"] != "LINKED"}
        if not unresolved:
            break
        run_search_pass(records, unresolved, all_candidates, variant, lang, args.workers)

        # Convert text sets to sorted lists for deterministic matching.
        canonical_candidates = {}
        for num, candmap in all_candidates.items():
            canonical_candidates[num] = {
                qid: {
                    "texts": sorted(v["texts"]),
                    "first_seen_pass": v["first_seen_pass"]
                }
                for qid, v in candmap.items()
            }

        meta = materialize_meta(canonical_candidates)
        for r in records:
            num = r["NUM"]
            if resolutions[num]["link_status"] == "LINKED":
                continue
            resolutions[num] = resolve_record(r, canonical_candidates.get(num, {}), meta)

        linked_now = sum(1 for x in resolutions.values() if x["link_status"] == "LINKED")
        print(f"AFTER {variant}:{lang}: LINKED={linked_now}/{EXPECTED_ROWS}", flush=True)

    fields = [
        "NUM","link_status","QID","date_delta_days","name_match_class",
        "candidate_count","eligible_candidate_count","first_seen_pass"
    ]
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in records:
            row = {"NUM": r["NUM"], **resolutions[r["NUM"]]}
            w.writerow(row)

    counts = defaultdict(int)
    match_counts = defaultdict(int)
    pass_counts = defaultdict(int)
    for x in resolutions.values():
        counts[x["link_status"]] += 1
        if x["name_match_class"]:
            match_counts[x["name_match_class"]] += 1
        if x["first_seen_pass"]:
            pass_counts[x["first_seen_pass"]] += 1

    digest = sha256_file(out)
    summary = {
        "protocol": "A2_WIKIDATA_IDENTITY_LINKAGE_V0_1_FROZEN",
        "source_rows": EXPECTED_ROWS,
        "frozen_prediction_sha256": FROZEN_PREDICTION_SHA256,
        "linkage_sha256": digest,
        "death_truth_accessed": False,
        "forbidden_properties_queried": [],
        "status_counts": dict(sorted(counts.items())),
        "name_match_counts": dict(sorted(match_counts.items())),
        "first_seen_pass_counts": dict(sorted(pass_counts.items())),
        "linked_fraction": counts["LINKED"] / EXPECTED_ROWS,
    }
    out.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    out.with_suffix(".sha256").write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)

if __name__ == "__main__":
    main()
