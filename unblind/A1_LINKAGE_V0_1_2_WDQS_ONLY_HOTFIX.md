# A1 linkage v0.1.2 — WDQS-only metadata hotfix

Pre-outcome engineering hotfix.

Observed failure:
- GitHub-hosted runner repeatedly received HTTP 429 from
  `https://www.wikidata.org/w/api.php`.
- The workflow exhausted its 6-hour timeout.

Change:
- Remove the MediaWiki action API / `wbgetentities` backend.
- Fetch the same allowed Wikidata labels and aliases through WDQS using
  `rdfs:label` and `skos:altLabel`.
- Continue using WDQS for P31/P569 candidate generation and P19/P625 tie-break metadata.
- Keep conservative request gating and 429 cooldown.

Unchanged scientific rules:
- same A1 2,087-record cohort;
- exact birth date first, then +/-1 day for unresolved cases;
- same EXACT_TOKEN_SIGNATURE and SUBSET_TOKEN_MATCH;
- same rank ordering and unique-top requirement;
- P19/P625 only breaks tied top candidates;
- prediction labels/status are never loaded;
- P570/P509/P20/P119 remain forbidden.

This is a transport/backend swap, not an outcome-driven linkage-rule change.
