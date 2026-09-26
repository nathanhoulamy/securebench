# Campaign report

Native (A: upstream harness + verifier) vs SecureBench (B: split verification), Claude Code 2.1.283, claude-sonnet-5, effort medium, Claude subscription. See FREEZE.md for pins and ISSUES.md for known differences.

Scope: the current admitted set (30 DeepSWE + 30 Terminal-Bench). Phase 1 (fixed-candidate agreement) is model-independent and reused from the 2026-09-25 Luna campaign.

Phase 4 records (reps 1; 60 tasks × 2 conditions × 1 rep planned = 120): 120. DeepSWE rows flagged by the F2P audit (Weaker or Missing > 0): 20; the `clean-f2p` scope drops them.

## Phase 4: pass rates

### Pass rates (all)

| benchmark | condition | tasks | runs | mean pass rate (task-averaged) | 95% bootstrap CI over tasks |
|---|---|---:|---:|---:|---|
| deep-swe | native | 30 | 30 | 0.267 | [0.100, 0.433] |
| deep-swe | securebench | 30 | 30 | 0.367 | [0.200, 0.533] |
| terminal-bench | native | 30 | 30 | 0.667 | [0.500, 0.833] |
| terminal-bench | securebench | 30 | 30 | 0.667 | [0.500, 0.833] |

### Paired difference B − A per task (all)

| benchmark | paired tasks | mean diff | 95% bootstrap CI | sign-flip p | Wilcoxon W (n≠0) p |
|---|---:|---:|---|---:|---|
| deep-swe | 30 | 0.100 | [-0.133, 0.333] | 0.6072 | 72.0 (15) 0.4579 |
| terminal-bench | 30 | 0.000 | [-0.167, 0.167] | 1.0000 | 10.5 (6) 0.9071 |

Per-task means, SDs and differences: `aggregate/per_task_all.csv`.

### Infrastructure errors (all; excluded from pass rates)

| condition | benchmark | runs with infrastructure_error |
|---|---|---:|
| - | - | 0 |

### Runtime, tokens and cost per run (all)

| benchmark | condition | runs | wall s (median) | agent s (median) | verify s (median) | capture s (median) | input tok (mean) | output tok (mean) | reasoning tok (mean) | cost USD (mean) | cost USD (total) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deep-swe | native | 30 | 999 | 818 | 54 | n/a | 7261022 | 51494 | 0 | 2.8713 | 86.14 |
| deep-swe | securebench | 30 | 813 | 733 | 64 | 1 | 4911369 | 46750 | 0 | 1.9701 | 29.55 |
| terminal-bench | native | 30 | 340 | 79 | 9 | n/a | 666866 | 11018 | 0 | 0.3397 | 10.19 |
| terminal-bench | securebench | 30 | 145 | 119 | 0 | 0 | 751357 | 11149 | 0 | 0.3505 | 9.46 |

Tokens come from Claude Code's last `result` event. Runs without one are excluded as unknown usage: timeouts, crashes, and SecureBench runs whose 1 MiB bounded stdout cut the stream (ISSUES S-08), which are mostly the long DeepSWE runs, so B's DeepSWE means cover the shorter sessions only and are not comparable to A's. Cost is Claude Code's API-price estimate (`total_cost_usd`, final event only); the runs were billed to a subscription, so it is notional. Runs with unknown usage: deep-swe/native 0, deep-swe/securebench 15, terminal-bench/native 0, terminal-bench/securebench 3.

SecureBench overhead = capture + evaluation (verify) time in B against native verification time in A; both are host wall-clock. Native verify time includes Pier/Harbor verifier container start.

### Pass rates (clean-f2p)

| benchmark | condition | tasks | runs | mean pass rate (task-averaged) | 95% bootstrap CI over tasks |
|---|---|---:|---:|---:|---|
| deep-swe | native | 11 | 11 | 0.091 | [0.000, 0.273] |
| deep-swe | securebench | 11 | 11 | 0.455 | [0.182, 0.727] |
| terminal-bench | native | 30 | 30 | 0.667 | [0.500, 0.833] |
| terminal-bench | securebench | 30 | 30 | 0.667 | [0.500, 0.833] |

### Paired difference B − A per task (clean-f2p)

| benchmark | paired tasks | mean diff | 95% bootstrap CI | sign-flip p | Wilcoxon W (n≠0) p |
|---|---:|---:|---|---:|---|
| deep-swe | 11 | 0.364 | [0.091, 0.636] | 0.1250 | 10.0 (4) 0.0719 |
| terminal-bench | 30 | 0.000 | [-0.167, 0.167] | 1.0000 | 10.5 (6) 0.9071 |

Per-task means, SDs and differences: `aggregate/per_task_clean-f2p.csv`.

### Infrastructure errors (clean-f2p; excluded from pass rates)

| condition | benchmark | runs with infrastructure_error |
|---|---|---:|
| - | - | 0 |

### Runtime, tokens and cost per run (clean-f2p)

| benchmark | condition | runs | wall s (median) | agent s (median) | verify s (median) | capture s (median) | input tok (mean) | output tok (mean) | reasoning tok (mean) | cost USD (mean) | cost USD (total) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deep-swe | native | 11 | 1019 | 897 | 43 | n/a | 7752088 | 60404 | 0 | 3.1123 | 34.24 |
| deep-swe | securebench | 11 | 910 | 762 | 69 | 4 | 5755971 | 56230 | 0 | 2.2311 | 11.16 |
| terminal-bench | native | 30 | 340 | 79 | 9 | n/a | 666866 | 11018 | 0 | 0.3397 | 10.19 |
| terminal-bench | securebench | 30 | 145 | 119 | 0 | 0 | 751357 | 11149 | 0 | 0.3505 | 9.46 |

Tokens come from Claude Code's last `result` event. Runs without one are excluded as unknown usage: timeouts, crashes, and SecureBench runs whose 1 MiB bounded stdout cut the stream (ISSUES S-08), which are mostly the long DeepSWE runs, so B's DeepSWE means cover the shorter sessions only and are not comparable to A's. Cost is Claude Code's API-price estimate (`total_cost_usd`, final event only); the runs were billed to a subscription, so it is notional. Runs with unknown usage: deep-swe/native 0, deep-swe/securebench 6, terminal-bench/native 0, terminal-bench/securebench 3.

SecureBench overhead = capture + evaluation (verify) time in B against native verification time in A; both are host wall-clock. Native verify time includes Pier/Harbor verifier container start.

### Runs where SecureBench graded no candidate

| benchmark | task | producer | capture | reason | native verdict |
|---|---|---|---|---|---|
| deep-swe | mashumaro-flattened-dataclass-fields | failed | - | - | failed |
| deep-swe | skrub-duration-encoding | failed | - | - | failed |
| terminal-bench | db-wal-recovery | ok | rejected | candidate path does not exist: /app/recovered.json | passed |
| terminal-bench | extract-moves-from-video | ok | rejected | candidate path does not exist: /app/solution.txt | failed |
| terminal-bench | feal-linear-cryptanalysis | failed | - | - | failed |
| terminal-bench | gpt2-codegolf | failed | - | - | failed |
| terminal-bench | mteb-leaderboard | ok | rejected | candidate path does not exist: /app/result.txt | passed |

## Verifier agreement

### Phase 1: fixed candidates

#### Phase 1, all

Comparable pairs: 745 (of 796). Cohen's κ = 0.929.

| | securebench_verdict pass | securebench_verdict fail |
|---|---:|---:|
| native_verdict pass | 120 | 13 |
| native_verdict fail | 2 | 610 |

Disagreements (accepting side named):

- deep-swe/ink-grid-box-layout [mutant] `test_semantic_mutants_fail[fr-rounding]#1`: accepted by **native_verdict** only
- deep-swe/termenv-preserve-ansi-resets [mutant] `test_mutant_no_split_guarantee_fails#1`: accepted by **native_verdict** only
- deep-swe/meriyah-explicit-resource-declarations [reference] `test_reference_passes_in_fresh_evaluations#1`: accepted by **securebench_verdict** only
- deep-swe/happy-dom-deterministic-intersectionobserver [mutant] `test_semantic_mutants_fail[root-margin-3value-wrong-expansion]#1`: accepted by **native_verdict** only
- deep-swe/happy-dom-deterministic-intersectionobserver [mutant] `test_semantic_mutants_fail[order-not-preserved]#1`: accepted by **native_verdict** only
- deep-swe/sqlfmt-create-table-ddl-formatting [mutant] `test_targeted_real_code_mutant_fails[unique-table-constraint-misclassified]#1`: accepted by **native_verdict** only
- deep-swe/tomlkit-toml-table-converters [mutant] `test_targeted_real_code_mutant_fails[max-depth-ignored]#1`: accepted by **native_verdict** only
- deep-swe/helm-array-merge-strategies [mutant] `test_cli_override_precedence_mutant_fails#1`: accepted by **native_verdict** only
- terminal-bench/constraints-scheduling [reference] `test_constraints_scheduling_v2_accepts_upstream_substring_suffix_and_first_match#1`: accepted by **securebench_verdict** only
- terminal-bench/distribution-search [malicious] `test_malformed_ambiguous_and_forged_artifacts_fail[trailing_claim]#1`: accepted by **native_verdict** only
- terminal-bench/git-leak-recovery [malicious] `test_targeted_mutants_and_forged_claims_fail[False-None-secret_remains_in_git_objects]#1`: accepted by **native_verdict** only
- terminal-bench/git-leak-recovery [mutant] `test_pinned_targeted_mutants_fail[recover-without-cleaning]#1`: accepted by **native_verdict** only
- terminal-bench/git-leak-recovery [malicious] `test_alternates_are_rejected_as_candidate_evidence#1`: accepted by **native_verdict** only
- terminal-bench/gpt2-codegolf [mutant] `test_behavior_mutants_fail_real_pinned_evaluations#1`: accepted by **native_verdict** only
- terminal-bench/headless-terminal [malicious] `test_semantic_and_malicious_mutants_fail_real_evaluations#4`: accepted by **native_verdict** only

| candidate kind | agree | disagree | not comparable |
|---|---:|---:|---:|
| base | 61 | 0 | 2 |
| malicious | 254 | 4 | 19 |
| mutant | 295 | 9 | 19 |
| reference | 120 | 2 | 11 |

#### Phase 1, clean-f2p

Comparable pairs: 614 (of 662). Cohen's κ = 0.943.

| | securebench_verdict pass | securebench_verdict fail |
|---|---:|---:|
| native_verdict pass | 102 | 8 |
| native_verdict fail | 2 | 502 |

Disagreements (accepting side named):

- deep-swe/ink-grid-box-layout [mutant] `test_semantic_mutants_fail[fr-rounding]#1`: accepted by **native_verdict** only
- deep-swe/meriyah-explicit-resource-declarations [reference] `test_reference_passes_in_fresh_evaluations#1`: accepted by **securebench_verdict** only
- deep-swe/tomlkit-toml-table-converters [mutant] `test_targeted_real_code_mutant_fails[max-depth-ignored]#1`: accepted by **native_verdict** only
- terminal-bench/constraints-scheduling [reference] `test_constraints_scheduling_v2_accepts_upstream_substring_suffix_and_first_match#1`: accepted by **securebench_verdict** only
- terminal-bench/distribution-search [malicious] `test_malformed_ambiguous_and_forged_artifacts_fail[trailing_claim]#1`: accepted by **native_verdict** only
- terminal-bench/git-leak-recovery [malicious] `test_targeted_mutants_and_forged_claims_fail[False-None-secret_remains_in_git_objects]#1`: accepted by **native_verdict** only
- terminal-bench/git-leak-recovery [mutant] `test_pinned_targeted_mutants_fail[recover-without-cleaning]#1`: accepted by **native_verdict** only
- terminal-bench/git-leak-recovery [malicious] `test_alternates_are_rejected_as_candidate_evidence#1`: accepted by **native_verdict** only
- terminal-bench/gpt2-codegolf [mutant] `test_behavior_mutants_fail_real_pinned_evaluations#1`: accepted by **native_verdict** only
- terminal-bench/headless-terminal [malicious] `test_semantic_and_malicious_mutants_fail_real_evaluations#4`: accepted by **native_verdict** only

| candidate kind | agree | disagree | not comparable |
|---|---:|---:|---:|
| base | 42 | 0 | 2 |
| malicious | 250 | 4 | 19 |
| mutant | 210 | 4 | 17 |
| reference | 102 | 2 | 10 |

### Attacks: malicious fixed candidates accepted

all: 277 malicious candidates; accepted by native: 5; accepted by SecureBench: 0.

- terminal-bench/distribution-search `test_malformed_ambiguous_and_forged_artifacts_fail[trailing_claim]#1` accepted by native
- terminal-bench/financial-document-processor `test_targeted_state_and_summary_mutants_fail[path_traversal-unsafe_summary_filename]#1` accepted by native
- terminal-bench/git-leak-recovery `test_targeted_mutants_and_forged_claims_fail[False-None-secret_remains_in_git_objects]#1` accepted by native
- terminal-bench/git-leak-recovery `test_alternates_are_rejected_as_candidate_evidence#1` accepted by native
- terminal-bench/headless-terminal `test_semantic_and_malicious_mutants_fail_real_evaluations#4` accepted by native

clean-f2p: 273 malicious candidates; accepted by native: 5; accepted by SecureBench: 0.

- terminal-bench/distribution-search `test_malformed_ambiguous_and_forged_artifacts_fail[trailing_claim]#1` accepted by native
- terminal-bench/financial-document-processor `test_targeted_state_and_summary_mutants_fail[path_traversal-unsafe_summary_filename]#1` accepted by native
- terminal-bench/git-leak-recovery `test_targeted_mutants_and_forged_claims_fail[False-None-secret_remains_in_git_objects]#1` accepted by native
- terminal-bench/git-leak-recovery `test_alternates_are_rejected_as_candidate_evidence#1` accepted by native
- terminal-bench/headless-terminal `test_semantic_and_malicious_mutants_fail_real_evaluations#4` accepted by native

Rows excluded from cross-grading as not faithfully reconstructable (ISSUES I-34): `terminal-bench/kv-store-grpc` (upstream verifier needs a running gRPC server and system-wide grpcio); `terminal-bench/hf-model-inference` (upstream verifier needs a running Flask service on port 5000); `terminal-bench/headless-terminal` (native agent installs dependencies system-wide; not in the declared candidate). Phase 1 excludes only the two live-service rows.

### Phase 5: real agent outputs, cross-graded

#### all: native runs (own verdict) vs securebench verifier

Comparable pairs: 55 (of 60). Cohen's κ = 0.852.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 22 | 2 |
| original_verdict fail | 2 | 29 |

Disagreements (accepting side named):

- deep-swe/helm-array-merge-strategies `native rep1 committed`: accepted by **original_verdict** only
- deep-swe/meriyah-explicit-resource-declarations `native rep1 committed`: accepted by **cross_verdict** only
- deep-swe/task-task-graph-export `native rep1 committed`: accepted by **original_verdict** only
- terminal-bench/cancel-async-tasks `native rep1 final-state`: accepted by **cross_verdict** only

#### all: securebench runs (own verdict) vs native verifier

Comparable pairs: 50 (of 53). Cohen's κ = 0.879.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 26 | 2 |
| original_verdict fail | 1 | 21 |

Disagreements (accepting side named):

- deep-swe/dateutil-rfc5545-timezone-interop `securebench rep1 securebench-captured`: accepted by **original_verdict** only
- deep-swe/meriyah-explicit-resource-declarations `securebench rep1 securebench-captured`: accepted by **original_verdict** only
- deep-swe/task-task-graph-export `securebench rep1 securebench-captured`: accepted by **cross_verdict** only

Not cross-graded (n/a):

- no stored candidate: 7
- not reconstructable: native agent installs dependencies system-wide; not in the declared candidate: 2
- not reconstructable: upstream verifier needs a running Flask service on port 5000: 2
- not reconstructable: upstream verifier needs a running gRPC server and system-wide grpcio: 2

#### clean-f2p: native runs (own verdict) vs securebench verifier

Comparable pairs: 38 (of 41). Cohen's κ = 0.895.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 18 | 0 |
| original_verdict fail | 2 | 18 |

Disagreements (accepting side named):

- deep-swe/meriyah-explicit-resource-declarations `native rep1 committed`: accepted by **cross_verdict** only
- terminal-bench/cancel-async-tasks `native rep1 final-state`: accepted by **cross_verdict** only

#### clean-f2p: securebench runs (own verdict) vs native verifier

Comparable pairs: 32 (of 35). Cohen's κ = 0.929.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 21 | 1 |
| original_verdict fail | 0 | 10 |

Disagreements (accepting side named):

- deep-swe/meriyah-explicit-resource-declarations `securebench rep1 securebench-captured`: accepted by **original_verdict** only

Not cross-graded (n/a):

- no stored candidate: 6
- not reconstructable: native agent installs dependencies system-wide; not in the declared candidate: 2
- not reconstructable: upstream verifier needs a running Flask service on port 5000: 2
- not reconstructable: upstream verifier needs a running gRPC server and system-wide grpcio: 2

DeepSWE native runs whose working tree differed from the committed diff: 3; SecureBench passes the working tree in 0 of them.

## Retries of infrastructure errors

| condition | error class | retries |
|---|---|---:|
| native | usage_limit | 15 |
| securebench | usage_limit | 14 |
| securebench | None | 5 |

