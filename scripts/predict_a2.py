#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import csv, hashlib, json, sys

from deathlab_longevity.challenger import chart_prediction, SIGN_NAMES, ABSTAIN

EXPECTED_HEADER = ["NUM","NAME","OCCU","DATE","PLACE","CY","C2","LON","LAT","1955"]
FORBIDDEN_HEADER_TOKENS = (
    "death", "deces", "died", "p570", "lifespan", "longevity", "cause",
)

OUT_FIELDS = [
    "NUM",
    "prediction_status",
    "prediction_label",
    "pair1_class",
    "pair2_class",
    "lagna_sign",
    "eighth_sign",
    "lagna_lord",
    "lagna_lord_sign",
    "eighth_lord",
    "eighth_lord_sign",
    "saturn_sign",
    "moon_sign",
    "min_boundary_margin_deg",
]

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: predict_a2.py INPUT_A2.csv OUTPUT_predictions.csv")
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)

    counts = Counter()
    rows_total = 0

    with src.open("r", encoding="utf-8", newline="") as f, dst.open("w", encoding="utf-8", newline="") as out:
        reader = csv.DictReader(f)
        if reader.fieldnames != EXPECTED_HEADER:
            raise SystemExit(f"FAIL-CLOSED header mismatch: {reader.fieldnames}")
        lowered = " ".join(x.lower() for x in reader.fieldnames)
        if any(token in lowered for token in FORBIDDEN_HEADER_TOKENS):
            raise SystemExit("FAIL-CLOSED outcome-bearing source header")

        writer = csv.DictWriter(out, fieldnames=OUT_FIELDS, lineterminator="\n")
        writer.writeheader()

        seen = set()
        for raw in reader:
            rows_total += 1
            sid = int(raw["NUM"])
            if sid in seen:
                raise SystemExit(f"FAIL-CLOSED duplicate NUM {sid}")
            seen.add(sid)

            if not raw["DATE"].strip() or not raw["LON"].strip() or not raw["LAT"].strip():
                counts["INELIGIBLE_MISSING_BIRTH_FIELDS"] += 1
                writer.writerow({
                    "NUM": sid,
                    "prediction_status": "INELIGIBLE_MISSING_BIRTH_FIELDS",
                    "prediction_label": "",
                    **{k: "" for k in OUT_FIELDS[3:]},
                })
                continue

            dt = datetime.fromisoformat(raw["DATE"])
            pred = chart_prediction(dt, float(raw["LON"]), float(raw["LAT"]))
            status = "COVERED" if pred.prediction_label != ABSTAIN else "ABSTAIN"
            counts[status] += 1
            counts[pred.prediction_label] += 1

            writer.writerow({
                "NUM": sid,
                "prediction_status": status,
                "prediction_label": pred.prediction_label,
                "pair1_class": pred.pair1_class,
                "pair2_class": pred.pair2_class,
                "lagna_sign": SIGN_NAMES[pred.lagna_sign],
                "eighth_sign": SIGN_NAMES[pred.eighth_sign],
                "lagna_lord": pred.lagna_lord,
                "lagna_lord_sign": SIGN_NAMES[pred.lagna_lord_sign],
                "eighth_lord": pred.eighth_lord,
                "eighth_lord_sign": SIGN_NAMES[pred.eighth_lord_sign],
                "saturn_sign": SIGN_NAMES[pred.saturn_sign],
                "moon_sign": SIGN_NAMES[pred.moon_sign],
                "min_boundary_margin_deg": f"{pred.min_boundary_margin_deg:.9f}",
            })

    if rows_total != 3643:
        raise SystemExit(f"FAIL-CLOSED expected 3643 rows, got {rows_total}")

    digest = sha256_file(dst)
    summary = {
        "source_rows": rows_total,
        "covered": counts["COVERED"],
        "abstain": counts["ABSTAIN"],
        "ineligible_missing_birth_fields": counts["INELIGIBLE_MISSING_BIRTH_FIELDS"],
        "labels": {k: counts[k] for k in ("SHORT","MEDIUM","LONG","ABSTAIN")},
        "coverage": counts["COVERED"] / rows_total,
        "predictions_sha256": digest,
        "outcome_accessed": False,
        "engine": {
            "zodiac": "sidereal",
            "ayanamsa": "Lahiri",
            "planet_ephemeris": "Moshier via pyswisseph 2.10.3.2",
            "houses": "whole-sign semantics; sidereal ascendant from Swiss Ephemeris"
        }
    }
    summary_path = dst.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    dst.with_suffix(".sha256").write_text(digest + "  " + dst.name + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
