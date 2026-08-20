# A1 linkage v0.1.1 — 429 transport/cache hotfix

Pre-outcome engineering hotfix only.

Scientific identity-linkage rules are unchanged:
- same A1 2,087-record cohort;
- same exact-date then +/-1-day candidate universe;
- same name classes and ranking;
- same P19/P625 tie-break restriction;
- same unique-top requirement;
- prediction labels/status are not loaded;
- P570/death truth remains forbidden.

Transport changes only:
1. WDQS request gate slowed to ~20 requests/minute.
2. Wikidata API request gate slowed to ~60 requests/minute.
3. Repeated HTTP 429 now escalates global cooldown: 90s → 180s → 360s → 720s.
4. +/-1-day dates already queried in the exact-date pass are reused from memory.
5. QID labels/aliases already fetched are reused from memory.

These cache changes eliminate redundant network calls but do not alter the candidate
set or ranking for any record.
