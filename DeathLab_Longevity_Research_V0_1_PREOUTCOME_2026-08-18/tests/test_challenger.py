from datetime import datetime, timezone
import itertools
import math

import swisseph as swe

from deathlab_longevity.challenger import (
    ABSTAIN, DUAL, FIXED, LONG, MEDIUM, MOVABLE, SHORT,
    LORD_BY_SIGN, MODALITY_BY_SIGN, chart_prediction, consensus,
    modality_pair_class, normalize360, sign_index,
)

REP = {MOVABLE: 0, FIXED: 1, DUAL: 2}

def test_modality_mapping_all_ordered_pairs():
    expected = {
        (MOVABLE, MOVABLE): LONG,
        (MOVABLE, FIXED): MEDIUM,
        (MOVABLE, DUAL): SHORT,
        (FIXED, MOVABLE): MEDIUM,
        (FIXED, FIXED): SHORT,
        (FIXED, DUAL): LONG,
        (DUAL, MOVABLE): SHORT,
        (DUAL, FIXED): LONG,
        (DUAL, DUAL): MEDIUM,
    }
    for (a, b), want in expected.items():
        assert modality_pair_class(REP[a], REP[b]) == want

def test_consensus_gate_is_exact():
    for label in (SHORT, MEDIUM, LONG):
        assert consensus(label, label) == label
    for a, b in itertools.permutations((SHORT, MEDIUM, LONG), 2):
        assert consensus(a, b) == ABSTAIN

def test_classical_rulership_table():
    assert LORD_BY_SIGN == (
        "Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
        "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter",
    )

def test_sign_index_boundaries():
    assert sign_index(0.0) == 0
    assert sign_index(29.999999) == 0
    assert sign_index(30.0) == 1
    assert sign_index(359.999999) == 11
    assert sign_index(360.0) == 0

def test_sidereal_planet_longitude_matches_tropical_minus_lahiri():
    dt = datetime(1873, 12, 15, 15, 59, 40, tzinfo=timezone.utc)
    hour = dt.hour + dt.minute / 60 + dt.second / 3600
    jd = swe.julday(dt.year, dt.month, dt.day, hour, swe.GREG_CAL)
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    ayan = swe.get_ayanamsa_ut(jd)
    tropical = swe.calc_ut(jd, swe.SATURN, swe.FLG_MOSEPH)[0][0]
    sidereal = swe.calc_ut(jd, swe.SATURN, swe.FLG_MOSEPH | swe.FLG_SIDEREAL)[0][0]
    delta = abs(((sidereal - normalize360(tropical - ayan) + 180) % 360) - 180)
    assert delta < 0.01

def test_sidereal_ascendant_is_consistent_with_lahiri_frame():
    dt = datetime(1873, 12, 15, 15, 59, 40, tzinfo=timezone.utc)
    hour = dt.hour + dt.minute / 60 + dt.second / 3600
    jd = swe.julday(dt.year, dt.month, dt.day, hour, swe.GREG_CAL)
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    ayan = swe.get_ayanamsa_ut(jd)
    tropical_asc = swe.houses_ex(jd, 43.23333, 0.08333, b"P", 0)[1][0]
    sidereal_asc = swe.houses_ex(jd, 43.23333, 0.08333, b"P", swe.FLG_SIDEREAL)[1][0]
    approximate = normalize360(tropical_asc - ayan)
    delta = abs(((sidereal_asc - approximate + 180) % 360) - 180)
    assert delta < 0.02

def test_first_a2_row_regression_is_deterministic():
    pred = chart_prediction(
        datetime(1873, 12, 15, 15, 59, 40, tzinfo=timezone.utc),
        0.08333,
        43.23333,
    )
    # Frozen after implementation, before any outcome access.
    assert pred.lagna_sign == 1
    assert pred.eighth_sign == 8
    assert pred.lagna_lord == "Venus"
    assert pred.eighth_lord == "Jupiter"
    assert pred.lagna_lord_sign == 7
    assert pred.eighth_lord_sign == 5
    assert pred.saturn_sign == 9
    assert pred.moon_sign == 6
    assert pred.pair1_class == LONG
    assert pred.pair2_class == LONG
    assert pred.prediction_label == LONG
