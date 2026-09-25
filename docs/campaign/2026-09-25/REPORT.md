# Campaign report

Native (A: upstream harness + verifier) vs SecureBench (B: split verification), Codex CLI 0.156.1, gpt-6-luna, reasoning effort max. See FREEZE.md for pins and ISSUES.md for known differences.

Scope: the current admitted set (30 DeepSWE + 30 Terminal-Bench). returns-validated-error-accumulation was removed from the admitted set after the main campaign (guest-computed law verdict) and replaced by obsidian-linter-auto-table-of-contents, which was run separately on 2026-09-25 with the same pins and configs (ISSUES I-36); returns' runs stay on disk, excluded.

Phase 4 records (reps 1, 2, 3; 60 tasks × 2 conditions × 3 reps planned = 360): 360. DeepSWE rows flagged by the F2P audit (Weaker or Missing > 0): 20; the `clean-f2p` scope drops them.

## Phase 4: pass rates

### Pass rates (all)

| benchmark | condition | tasks | runs | mean pass rate (task-averaged) | 95% bootstrap CI over tasks |
|---|---|---:|---:|---:|---|
| deep-swe | native | 30 | 90 | 0.456 | [0.311, 0.600] |
| deep-swe | securebench | 30 | 89 | 0.467 | [0.344, 0.589] |
| terminal-bench | native | 30 | 89 | 0.711 | [0.578, 0.844] |
| terminal-bench | securebench | 30 | 90 | 0.633 | [0.478, 0.789] |

### Paired difference B − A per task (all)

| benchmark | paired tasks | mean diff | 95% bootstrap CI | sign-flip p | Wilcoxon W (n≠0) p |
|---|---:|---:|---|---:|---|
| deep-swe | 30 | 0.011 | [-0.133, 0.144] | 1.0000 | 78.5 (19) 0.5135 |
| terminal-bench | 30 | -0.078 | [-0.189, 0.022] | 0.2412 | 20.0 (11) 0.2607 |

Per-task means, SDs and differences: `aggregate/per_task_all.csv`.

### Infrastructure errors (all; excluded from pass rates)

| condition | benchmark | runs with infrastructure_error |
|---|---|---:|
| native | terminal-bench | 1 |
| securebench | deep-swe | 1 |

### Runtime, tokens and cost per run (all)

| benchmark | condition | runs | wall s (median) | agent s (median) | verify s (median) | capture s (median) | input tok (mean) | output tok (mean) | reasoning tok (mean) | cost USD (mean) | cost USD (total) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deep-swe | native | 90 | 1031 | 770 | 51 | n/a | 5713943 | 83070 | 67800 | 0.1141 | 10.27 |
| deep-swe | securebench | 90 | 922 | 808 | 72 | 2 | 4837735 | 81036 | 66365 | 0.1033 | 8.78 |
| terminal-bench | native | 90 | 466 | 156 | 9 | n/a | 577728 | 18313 | 14674 | 0.0189 | 1.63 |
| terminal-bench | securebench | 90 | 192 | 176 | 0 | 0 | 781344 | 22776 | 18245 | 0.0234 | 1.94 |

Token and cost columns use only runs whose Codex session completed a turn (usage is reported only on `turn.completed`); runs without it (timeouts, and SecureBench runs whose bounded stdout dropped the final event, ISSUES I-28) are excluded, so totals are lower bounds. Runs with unknown usage: deep-swe/native 0, deep-swe/securebench 5, terminal-bench/native 4, terminal-bench/securebench 7.

SecureBench overhead = capture + evaluation (verify) time in B against native verification time in A; both are host wall-clock. Native verify time includes Pier/Harbor verifier container start.

### Pass rates (clean-f2p)

| benchmark | condition | tasks | runs | mean pass rate (task-averaged) | 95% bootstrap CI over tasks |
|---|---|---:|---:|---:|---|
| deep-swe | native | 11 | 33 | 0.455 | [0.273, 0.636] |
| deep-swe | securebench | 11 | 32 | 0.606 | [0.394, 0.788] |
| terminal-bench | native | 30 | 89 | 0.711 | [0.578, 0.844] |
| terminal-bench | securebench | 30 | 90 | 0.633 | [0.478, 0.789] |

### Paired difference B − A per task (clean-f2p)

| benchmark | paired tasks | mean diff | 95% bootstrap CI | sign-flip p | Wilcoxon W (n≠0) p |
|---|---:|---:|---|---:|---|
| deep-swe | 11 | 0.152 | [0.061, 0.242] | 0.0625 | 15.0 (5) 0.0533 |
| terminal-bench | 30 | -0.078 | [-0.189, 0.022] | 0.2412 | 20.0 (11) 0.2607 |

Per-task means, SDs and differences: `aggregate/per_task_clean-f2p.csv`.

### Infrastructure errors (clean-f2p; excluded from pass rates)

| condition | benchmark | runs with infrastructure_error |
|---|---|---:|
| native | terminal-bench | 1 |
| securebench | deep-swe | 1 |

### Runtime, tokens and cost per run (clean-f2p)

| benchmark | condition | runs | wall s (median) | agent s (median) | verify s (median) | capture s (median) | input tok (mean) | output tok (mean) | reasoning tok (mean) | cost USD (mean) | cost USD (total) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deep-swe | native | 33 | 1081 | 877 | 42 | n/a | 5659871 | 92537 | 77881 | 0.1197 | 3.95 |
| deep-swe | securebench | 33 | 938 | 870 | 33 | 2 | 5359039 | 90523 | 75768 | 0.1152 | 3.69 |
| terminal-bench | native | 90 | 466 | 156 | 9 | n/a | 577728 | 18313 | 14674 | 0.0189 | 1.63 |
| terminal-bench | securebench | 90 | 192 | 176 | 0 | 0 | 781344 | 22776 | 18245 | 0.0234 | 1.94 |

Token and cost columns use only runs whose Codex session completed a turn (usage is reported only on `turn.completed`); runs without it (timeouts, and SecureBench runs whose bounded stdout dropped the final event, ISSUES I-28) are excluded, so totals are lower bounds. Runs with unknown usage: deep-swe/native 0, deep-swe/securebench 1, terminal-bench/native 4, terminal-bench/securebench 7.

SecureBench overhead = capture + evaluation (verify) time in B against native verification time in A; both are host wall-clock. Native verify time includes Pier/Harbor verifier container start.

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

Comparable pairs: 168 (of 179). Cohen's κ = 0.844.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 85 | 11 |
| original_verdict fail | 2 | 70 |

Disagreements (accepting side named):

- deep-swe/prometheus-typed-label-sorting `native rep1 committed`: accepted by **original_verdict** only
- deep-swe/task-task-graph-export `native rep1 committed`: accepted by **original_verdict** only
- deep-swe/updo-policy-alerting `native rep1 committed`: accepted by **original_verdict** only
- deep-swe/anko-default-function-arguments `native rep2 committed`: accepted by **cross_verdict** only
- deep-swe/prometheus-typed-label-sorting `native rep2 committed`: accepted by **original_verdict** only
- deep-swe/skrub-duration-encoding `native rep2 committed`: accepted by **original_verdict** only
- deep-swe/tengo-callable-instance-isolation `native rep2 committed`: accepted by **cross_verdict** only
- deep-swe/prometheus-typed-label-sorting `native rep3 committed`: accepted by **original_verdict** only
- deep-swe/skrub-duration-encoding `native rep3 committed`: accepted by **original_verdict** only
- deep-swe/task-task-graph-export `native rep3 committed`: accepted by **original_verdict** only
- deep-swe/updo-policy-alerting `native rep3 committed`: accepted by **original_verdict** only
- terminal-bench/cancel-async-tasks `native rep3 final-state`: accepted by **original_verdict** only
- terminal-bench/gpt2-codegolf `native rep3 final-state`: accepted by **original_verdict** only

#### all: securebench runs (own verdict) vs native verifier

Comparable pairs: 162 (of 169). Cohen's κ = 0.799.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 84 | 8 |
| original_verdict fail | 8 | 62 |

Disagreements (accepting side named):

- deep-swe/meriyah-explicit-resource-declarations `securebench rep1 securebench-captured`: accepted by **original_verdict** only
- deep-swe/pest-character-class-coalescing `securebench rep1 securebench-captured`: accepted by **original_verdict** only
- deep-swe/skrub-duration-encoding `securebench rep1 securebench-captured`: accepted by **cross_verdict** only
- deep-swe/task-task-graph-export `securebench rep1 securebench-captured`: accepted by **cross_verdict** only
- deep-swe/anko-default-function-arguments `securebench rep2 securebench-captured`: accepted by **original_verdict** only
- deep-swe/bandit-structured-nosec-directives `securebench rep2 securebench-captured`: accepted by **original_verdict** only
- deep-swe/skrub-duration-encoding `securebench rep2 securebench-captured`: accepted by **cross_verdict** only
- deep-swe/tengo-callable-instance-isolation `securebench rep2 securebench-captured`: accepted by **original_verdict** only
- deep-swe/termenv-preserve-ansi-resets `securebench rep2 securebench-captured`: accepted by **cross_verdict** only
- deep-swe/updo-policy-alerting `securebench rep2 securebench-captured`: accepted by **cross_verdict** only
- deep-swe/anko-default-function-arguments `securebench rep3 securebench-captured`: accepted by **original_verdict** only
- deep-swe/meriyah-explicit-resource-declarations `securebench rep3 securebench-captured`: accepted by **original_verdict** only
- deep-swe/skrub-duration-encoding `securebench rep3 securebench-captured`: accepted by **cross_verdict** only
- deep-swe/task-task-graph-export `securebench rep3 securebench-captured`: accepted by **cross_verdict** only
- terminal-bench/cancel-async-tasks `securebench rep1 securebench-captured`: accepted by **original_verdict** only
- terminal-bench/gpt2-codegolf `securebench rep1 securebench-captured`: accepted by **cross_verdict** only

Not cross-graded (n/a):

- no stored candidate: 8
- not reconstructable: native agent installs dependencies system-wide; not in the declared candidate: 6
- not reconstructable: upstream verifier needs a running Flask service on port 5000: 6
- not reconstructable: upstream verifier needs a running gRPC server and system-wide grpcio: 6
- original run was an infrastructure error: 2

#### clean-f2p: native runs (own verdict) vs securebench verifier

Comparable pairs: 111 (of 122). Cohen's κ = 0.923.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 68 | 2 |
| original_verdict fail | 2 | 39 |

Disagreements (accepting side named):

- deep-swe/anko-default-function-arguments `native rep2 committed`: accepted by **cross_verdict** only
- deep-swe/tengo-callable-instance-isolation `native rep2 committed`: accepted by **cross_verdict** only
- terminal-bench/cancel-async-tasks `native rep3 final-state`: accepted by **original_verdict** only
- terminal-bench/gpt2-codegolf `native rep3 final-state`: accepted by **original_verdict** only

#### clean-f2p: securebench runs (own verdict) vs native verifier

Comparable pairs: 109 (of 116). Cohen's κ = 0.864.

| | cross_verdict pass | cross_verdict fail |
|---|---:|---:|
| original_verdict pass | 64 | 6 |
| original_verdict fail | 1 | 38 |

Disagreements (accepting side named):

- deep-swe/meriyah-explicit-resource-declarations `securebench rep1 securebench-captured`: accepted by **original_verdict** only
- deep-swe/anko-default-function-arguments `securebench rep2 securebench-captured`: accepted by **original_verdict** only
- deep-swe/tengo-callable-instance-isolation `securebench rep2 securebench-captured`: accepted by **original_verdict** only
- deep-swe/anko-default-function-arguments `securebench rep3 securebench-captured`: accepted by **original_verdict** only
- deep-swe/meriyah-explicit-resource-declarations `securebench rep3 securebench-captured`: accepted by **original_verdict** only
- terminal-bench/cancel-async-tasks `securebench rep1 securebench-captured`: accepted by **original_verdict** only
- terminal-bench/gpt2-codegolf `securebench rep1 securebench-captured`: accepted by **cross_verdict** only

Not cross-graded (n/a):

- not reconstructable: native agent installs dependencies system-wide; not in the declared candidate: 6
- not reconstructable: upstream verifier needs a running Flask service on port 5000: 6
- not reconstructable: upstream verifier needs a running gRPC server and system-wide grpcio: 6
- no stored candidate: 4
- original run was an infrastructure error: 2

DeepSWE native runs whose working tree differed from the committed diff: 5; SecureBench passes the working tree in 4 of them.

## Retries of infrastructure errors

| condition | error class | retries |
|---|---|---:|
| native | harness | 4 |
| native | native:AgentSetupTimeoutError | 8 |
| native | native:RuntimeError | 9 |
| securebench | model_api | 2 |
| securebench | repair:restored | 1 |
| securebench | None | 17 |

