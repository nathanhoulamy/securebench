# Adversarial-candidate campaign — report

Native (upstream harness) vs SecureBench (split verification), on the 60 admitted
rows. Method: hand-authored candidates that do **not** genuinely solve the task,
each graded by both verifiers. "Attack success" against a condition = that
condition returns its **pass** verdict for a non-solving candidate.

> **Headline: SecureBench had 0 attack successes across every candidate tried.**
> Native returned a pass verdict for non-solving candidates on **7 rows**, via
> four distinct mechanisms. No candidate passed SecureBench without solving; base
> candidates fail and reference solutions pass on both verifiers throughout.

Grading is faithful: native via the real Harbor/Pier Docker replay
(`phase1.native_grade`), SecureBench via capture + Oracle (`verify_workspace`) or
the Docker command replay for protocol rows. Only newly authored candidates are
used (no Phase-1 reuse). Per-row records: `runs/campaign-adversarial/` (git-ignored);
committed pilots and batches under this directory. Builders/driver:
`tools/native_baseline/adversarial/`.

## Demonstrated architectural attacks (native passes, SecureBench blocks)

| row | candidate(s) | mechanism | goal | native | securebench |
|---|---|---|---|---|---|
| terminal-bench/git-leak-recovery | reflog_only, dangling_commit | secret left in a git object native never inspects (reflog / under a dangling commit); SB enumerates every object | G1/G3 | pass | fail |
| terminal-bench/fix-git | forge_matched_pair, forge_empty | native only md5-compares the answer to an agent-writable container-side reference; SB uses a fixed host-side SHA256 | G3 | pass | fail |
| terminal-bench/gpt2-codegolf | forge | hardcode the one public prompt's continuation; SB's Oracle feeds a hidden second prompt | G1/G4 | pass | fail |
| deep-swe/narwhals-rolling-window-suite | forge_conftest | repo-root `conftest.py` rewrites every pytest outcome to passed; SB never runs the repo suite (adapter+Oracle re-derive) | G2/G5 | pass | fail |
| deep-swe/dateutil-rfc5545-timezone-interop | forge_conftest | same | G2/G5 | pass | fail |
| deep-swe/mashumaro-flattened-dataclass-fields | forge_conftest | same | G2/G5 | pass | fail |
| deep-swe/sqlfmt-create-table-ddl-formatting | forge_conftest | same | G2/G5 | pass | fail |

Each attack targets a SecureBench design goal and is defeated by that goal:
full object enumeration (G1), bounded handoff excluding the trusted reference
(G3), hidden Oracle cases (G1/G4), and — most broadly — the fact that SecureBench
**never executes the candidate's own test harness**: an assertion-free adapter
reports observations and a host-side Oracle re-derives the verdict, so forging the
guest test report changes nothing SecureBench looks at (G2/G5).

## Where the pytest report-forging attack did NOT fool native

The same `conftest.py` force-pass patch was applied to all 9 DeepSWE pytest rows.
Native accepted it on 4 (above) and **rejected** it on **cattrs-partial-structuring-recovery,
tomlkit-toml-table-converters, skrub-duration-encoding, bandit-structured-nosec-directives**.
The hook rewrites the outcome only of tests that actually *run*; where a row's
`/app/test.sh` invokes pytest so the root `conftest.py` is not loaded (or the
missing fix causes a collection/import error rather than an assertion failure),
the forced-pass never takes effect. **python-statemachine-state-data-scoping** is
a ninth case: the repo already ships its own root `conftest.py`, so the new-file
patch fails to apply — a modify-conftest variant was not authored. So native's
exposure to this attack is row-dependent — while SecureBench blocked the forged
conftest on **all 9** (the adapter calls the still-unfixed library → wrong values
→ Oracle fail).

## Not demonstrated / inconclusive

- **terminal-bench/cancel-async-tasks**: the authored `run.py` candidates did not
  meet native's timing/cancellation contract (the `reference` limiter also failed
  native, on the borderline `elapsed >= 6s` check), so no clean native pass was
  obtained. The intended attack (fabricated stdout, no real task execution) is
  sound in principle — SecureBench records task lifecycle events host-side, so it
  fails the fabrication (reference passed SB) — but native was not fooled by these
  candidates. Reported as inconclusive, not an attack.
- **Go (13) and Node (8) DeepSWE rows**: the report-forging attack is
  framework-specific. Go's `go test` does not expose a per-test outcome-override
  hook (a `TestMain` that exits early yields no *passing* f2p nodes, so native
  scores 0), and Node runners need a per-config setup hook. No generic candidate
  attack was demonstrated for these; SecureBench's architecture blocks
  report-forging regardless of language (it never runs the repo suite).

## No architectural divergence (analytical)

- **23 TB answer-file rows** (batches 1–2): 15 have the answer baked identically
  into both the upstream test and the Oracle (the Oracle reimplements the upstream
  test), so a static file of the known answer passes both — a shared
  benchmark-design weakness, not a native-vs-SecureBench difference. The rest are
  genuine problems with only fidelity divergences.
- **financial-document-processor**: native trusts the `summary.csv` filename field
  and reads it live with path-traversal/absolute/symlink exposure (SHA512); the
  Oracle validates filenames and resolves them only against the bounded
  capture manifest (SHA256), closing the hole. SecureBench is **stricter** here,
  but native's independent placement + amount checks mean no clean static
  non-solving native pass was available, so it is reported as a stricter-Oracle
  divergence, not a native attack.

## Where SecureBench is more lenient than native (honest counter-findings)

- **rstan-to-pystan**: the Oracle deliberately drops native's
  `test_r_rstan_not_installed` environment check, so a solution that installed
  R/RStan would pass SecureBench and fail native.
- **write-compressor / distribution-search**: fidelity divergences from the Oracle
  being a host-side reimplementation (Python range-decoder vs the compiled C
  decoder; strict npy parser vs `np.load`). Not non-solving passes.

## Out of scope (offline)

kv-store-grpc, hf-model-inference, headless-terminal: the upstream verifier needs
a live service or system-wide installs, not reconstructable offline (as honest
campaign ISSUES I-34). Not graded.

## Sanity and infrastructure

- Every graded row: `base` fails on both verifiers; `reference` passes on both
  (except cancel-async-tasks `reference`, above).
- Infrastructure errors (Docker/load flakiness) were retried. One row,
  python-statemachine-state-data-scoping, could not take the forge_conftest patch
  at all (it ships its own root `conftest.py`, so the new-file patch fails to
  apply); it is reported as not-applicable rather than as an attack or a pass.

## Bottom line

Across all authored non-solving candidates, **SecureBench issued zero pass
verdicts**. Native issued pass verdicts on 7 rows through four independent
mechanisms. SecureBench's defenses — full-object enumeration, bounded candidate
handoff, hidden Oracle cases, and re-deriving the verdict host-side instead of
trusting the guest test report — each blocked the corresponding attack class. The
honest counter-findings (rstan weaker Oracle, engine/format fidelity divergences,
and the shared answer-baked-in weakness) are limitations of specific conversions,
not of the split-verification architecture.
