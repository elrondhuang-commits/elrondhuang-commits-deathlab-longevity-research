"""Deterministic, outcome-blind reimplementation of the frozen two-pair Challenger.

IMPORTANT
---------
This file is a NEW byte-frozen implementation created before any DeathLab A2
death-truth unblind. It implements the recovered frozen specification but does
NOT claim byte identity with the historical predictor whose SHA-256 is recorded
in protocol/CHALLENGER_SPEC_LOCK.json.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Dict

import swisseph as swe

MOVABLE = "MOVABLE"
FIXED = "FIXED"
DUAL = "DUAL"

SHORT = "SHORT"
MEDIUM = "MEDIUM"
LONG = "LONG"
ABSTAIN = "ABSTAIN"

SIGN_NAMES = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)

MODALITY_BY_SIGN = (
    MOVABLE, FIXED, DUAL, MOVABLE, FIXED, DUAL,
    MOVABLE, FIXED, DUAL, MOVABLE, FIXED, DUAL,
)

# Classical Parashari rulership only.
LORD_BY_SIGN = (
    "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
    "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
)

BODY_ID = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
}

# The recovered frozen mapping, treated as unordered modality pairs.
PAIR_CLASS = {
    frozenset((MOVABLE,)): LONG,                   # movable + movable
    frozenset((FIXED, DUAL)): LONG,               # fixed + dual
    frozenset((MOVABLE, FIXED)): MEDIUM,          # movable + fixed
    frozenset((DUAL,)): MEDIUM,                   # dual + dual
    frozenset((MOVABLE, DUAL)): SHORT,            # movable + dual
    frozenset((FIXED,)): SHORT,                   # fixed + fixed
}

@dataclass(frozen=True)
class Prediction:
    prediction_label: str
    pair1_class: str
    pair2_class: str
    lagna_sign: int
    eighth_sign: int
    lagna_lord: str
    lagna_lord_sign: int
    eighth_lord: str
    eighth_lord_sign: int
    saturn_sign: int
    moon_sign: int
    min_boundary_margin_deg: float

def normalize360(x: float) -> float:
    return x % 360.0

def sign_index(longitude_deg: float) -> int:
    return int(math.floor(normalize360(longitude_deg) / 30.0)) % 12

def sign_boundary_margin(longitude_deg: float) -> float:
    x = normalize360(longitude_deg) % 30.0
    return min(x, 30.0 - x)

def modality_pair_class(sign_a: int, sign_b: int) -> str:
    a = MODALITY_BY_SIGN[sign_a]
    b = MODALITY_BY_SIGN[sign_b]
    return PAIR_CLASS[frozenset((a, b))]

def consensus(pair1_class: str, pair2_class: str) -> str:
    return pair1_class if pair1_class == pair2_class else ABSTAIN

def _julian_day(dt_utc: datetime) -> float:
    if dt_utc.tzinfo is None:
        raise ValueError("birth datetime must be timezone-aware")
    dt = dt_utc.astimezone(timezone.utc)
    hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0 + dt.microsecond / 3.6e9
    return swe.julday(dt.year, dt.month, dt.day, hour, swe.GREG_CAL)

def _sidereal_longitude(jd_ut: float, body_name: str) -> float:
    # Explicit Moshier makes the reimplementation independent of external ephemeris files.
    # This is a newly frozen engineering choice; the historical code bytes are unavailable.
    flags = swe.FLG_MOSEPH | swe.FLG_SIDEREAL
    xx, returned_flags = swe.calc_ut(jd_ut, BODY_ID[body_name], flags)
    if not (returned_flags & swe.FLG_SIDEREAL):
        raise RuntimeError("Swiss Ephemeris did not return sidereal coordinates")
    return normalize360(xx[0])

def chart_prediction(dt_utc: datetime, longitude_deg: float, latitude_deg: float) -> Prediction:
    if not (-180.0 <= longitude_deg <= 180.0):
        raise ValueError("longitude out of range")
    if not (-90.0 <= latitude_deg <= 90.0):
        raise ValueError("latitude out of range")

    swe.set_sid_mode(swe.SIDM_LAHIRI)
    jd_ut = _julian_day(dt_utc)

    # Ascendant sign only is needed. Whole-sign houses then define the 8th sign as +7.
    _, ascmc = swe.houses_ex(
        jd_ut, latitude_deg, longitude_deg, b"P", swe.FLG_SIDEREAL
    )
    asc_lon = normalize360(ascmc[0])
    lagna_sign = sign_index(asc_lon)
    eighth_sign = (lagna_sign + 7) % 12

    lagna_lord = LORD_BY_SIGN[lagna_sign]
    eighth_lord = LORD_BY_SIGN[eighth_sign]

    needed = {lagna_lord, eighth_lord, "Saturn", "Moon"}
    longs: Dict[str, float] = {
        name: _sidereal_longitude(jd_ut, name) for name in sorted(needed)
    }

    lagna_lord_sign = sign_index(longs[lagna_lord])
    eighth_lord_sign = sign_index(longs[eighth_lord])
    saturn_sign = sign_index(longs["Saturn"])
    moon_sign = sign_index(longs["Moon"])

    pair1 = modality_pair_class(lagna_lord_sign, eighth_lord_sign)
    pair2 = modality_pair_class(saturn_sign, moon_sign)

    margins = [sign_boundary_margin(asc_lon)] + [
        sign_boundary_margin(v) for v in longs.values()
    ]

    return Prediction(
        prediction_label=consensus(pair1, pair2),
        pair1_class=pair1,
        pair2_class=pair2,
        lagna_sign=lagna_sign,
        eighth_sign=eighth_sign,
        lagna_lord=lagna_lord,
        lagna_lord_sign=lagna_lord_sign,
        eighth_lord=eighth_lord,
        eighth_lord_sign=eighth_lord_sign,
        saturn_sign=saturn_sign,
        moon_sign=moon_sign,
        min_boundary_margin_deg=min(margins),
    )
