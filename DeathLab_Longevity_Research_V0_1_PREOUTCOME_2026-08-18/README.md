# DeathLab Longevity Research ☠️🔬

Outcome-blind research repository for the DeathLab lifespan-validation program.

## Current phase

**BIRTH-ONLY PREDICTION FREEZE.**

This repository intentionally contains **no death-truth loader and no efficacy scorer yet**.
The first legal transition is:

1. Verify the recovered frozen Challenger specification.
2. Materialize the exact version-locked Gauquelin A2 birth corpus.
3. Generate all birth-only predictions.
4. Freeze the prediction bytes with SHA-256.
5. Only in a later commit, after the prediction hash exists, open the separate death-truth rail.

## Primary cohort

Gauquelin LERRCP A2 via `tig12/g5`:

- commit: `bf0db345b58127a438121b74ebf4ad843243a573`
- path: `data/db/init/lerrcp-marked/A2.csv`
- Git blob SHA-1: `0b58382c3213900e03960bdc4046dacb7f26b6a2`
- expected rows: **3,643**
- source header: birth-side only

The raw third-party CSV is not committed. GitHub Actions materializes the exact bytes and fails closed on drift.

## Predictor

Recovered historical frozen specification:

- Pair 1: Lagna lord × 8th lord
- Pair 2: Saturn × Moon
- Emit `SHORT`, `MEDIUM`, or `LONG` only when Pair 1 and Pair 2 agree
- Otherwise `ABSTAIN`
- Sidereal / Lahiri / whole-sign / classical rulership
- Birth data only

The historical predictor SHA-256 is preserved in `protocol/CHALLENGER_SPEC_LOCK.json`.
Because the original code bytes were not recovered, the implementation in this repo is explicitly a
**new preregistered reimplementation**, created before A2 death outcomes are accessed. It receives its own hash.

## Run locally

```bash
pip install -r requirements.txt
pip install -e .
pytest -q
python scripts/materialize_a2.py artifacts/A2.frozen.csv
python scripts/predict_a2.py artifacts/A2.frozen.csv artifacts/CHALLENGER_A2_predictions.csv
```

## Methodological hard rule

Do not add a death loader, P570 query, lifespan column, truth label, or efficacy scorer until
`CHALLENGER_A2_predictions.csv` has been generated and its SHA-256 frozen.
