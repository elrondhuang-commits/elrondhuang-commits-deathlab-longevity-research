# DeathLab A2 Pre-Unblind Audit V0.1

Prediction freeze verdict: **PASS WITH PRE-UNBLIND ADDENDUM**.

Frozen prediction CSV SHA-256:

`f213787a1bc950313acc4a06d6c9f952a904cdcf6540b616389f53ca7b94cdcc`

Verified from the frozen CSV:

- rows: 3,643
- unique NUM: 3,643
- duplicates: 0
- COVERED: 1,453
- ABSTAIN: 2,190
- SHORT: 502
- MEDIUM: 458
- LONG: 493
- outcome_accessed: false

Two pre-unblind provenance/reporting notes are recorded:

1. The workflow summary double-counted ABSTAIN because the same counter key was incremented once for status and once for label. The frozen CSV is unaffected.
2. The successful A2 materializer uses the observed exact file size 351,839 bytes. The earlier source-lock metadata still records 529,373; exact source identity remained guarded by Git blob SHA-1, exact header, and exact 3,643-row count.

Do not regenerate or tune the frozen prediction CSV because of these reporting/provenance corrections.
