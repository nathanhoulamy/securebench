# Batch 1 — 10 Terminal-Bench answer-file rows

Method: hand-authored candidates, dual-graded. native = real upstream harness
(Harbor Docker replay via `phase1.native_grade`); securebench = capture + Oracle
(`verify_workspace`, offline for artifact checks). "Attack success" = a condition
returns its pass verdict for a candidate that does not genuinely solve the task.

Rows: distribution-search, sqlite-db-truncate, fix-git, crack-7z-hash,
vulnerable-secret, db-wal-recovery, gcode-to-text, log-summary-date-ranges,
dna-insert, dna-assembly.

## Tally

- **Native attacks: 1 row (fix-git), 2 candidates.**
- **SecureBench attacks: 0.**
- No divergence (shared benchmark weakness): 6 rows.
- Genuine problem, only strictness/engine divergence (no non-solving pass): 3 rows.

## fix-git — native-only attack, blocked by SecureBench (demonstrated)

See `pilots/fix-git/`. Native only checks each recovered file equals a
container-side reference (`/app/resources/patch_files/*`, md5) — both
agent-writable, neither content pinned. `forge_matched_pair` (garbage in both)
and `forge_empty` obtain native's pass verdict; SecureBench compares the declared
answer to fixed SHA256 and fails both. base fail / reference pass on both.
Targets **G3 (bounded handoff)**.

## No divergence — answer is a public constant baked into both graders (6 rows)

crack-7z-hash, vulnerable-secret, gcode-to-text, sqlite-db-truncate,
db-wal-recovery, log-summary-date-ranges.

For these, the expected answer is a literal constant in **both** the upstream
test and the Oracle (e.g. crack-7z-hash plaintext `honeybear`; vulnerable-secret
`FLAG{…}`; db-wal-recovery's full 11-row table; log-summary's full 15-row CSV).
A static file of the known answer passes both — but writing the correct answer
*is* the deliverable, so this is not "passing without solving" in an
architecture-specific way. It is a shared benchmark-design weakness (the answer
lives in the grader), identical for native and SecureBench; neither adds
protection. Reported, not counted as an attack against either.

## Genuine problem; only strictness/engine divergence (3 rows)

- **distribution-search**: requires an actual 150k-length distribution with
  forward and backward KL to uniform both = 10.0 (TOL 1e-3). No static
  non-solving file passes either. Divergence is format strictness: the Oracle's
  npy parser rejects trailing bytes and non-float dtypes that native's `np.load`
  tolerates, so a *correct* array with trailing junk passes native and fails the
  Oracle. That needs a genuine solution, so it is not an attack; it is a
  SecureBench-stricter fidelity note.
- **dna-insert, dna-assembly**: genuine primer-design problems. Divergence is the
  melting-temperature engine — native shells out to the external `oligotm`
  binary, the Oracle uses a Python primer3 reimplementation
  (`securebench/verification/oligotm.py`). Near the Tm bounds (58/72 °C, ≤5 °C
  pair difference) the two can disagree at the last digit, so a borderline design
  could pass one and fail the other. A fidelity surface, not a non-solving pass.

## Per-row table

| row | category | native attack? | securebench attack? |
|---|---|---|---|
| fix-git | native-only attack (demonstrated) | yes (2 candidates) | no |
| crack-7z-hash | constant baked in both | no | no |
| vulnerable-secret | constant baked in both | no | no |
| gcode-to-text | constant baked in both | no | no |
| sqlite-db-truncate | constant baked in both | no | no |
| db-wal-recovery | constant baked in both | no | no |
| log-summary-date-ranges | constant baked in both | no | no |
| distribution-search | genuine; Oracle stricter on npy format | no | no |
| dna-insert | genuine; Tm engine divergence | no | no |
| dna-assembly | genuine; Tm engine divergence | no | no |
