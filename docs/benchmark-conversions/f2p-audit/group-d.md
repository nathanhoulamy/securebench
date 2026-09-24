# F2P coverage audit — group D

Rows audited: `cattrs-partial-structuring-recovery`, `fd-deterministic-multi-key-sorting`,
`updo-policy-alerting`, `ink-grid-box-layout`, `helm-array-merge-strategies`.

Method: for each row, every upstream F2P node id (`tests/config.json`) was matched against
its test body in `tests/test.patch`, then checked against what the Oracle
(`benchmarks/deep-swe/v2/hidden/<row>/oracle/`) and adapter/driver
(`benchmarks/deep-swe/v2/evaluation_inputs/<row>/adapter/`) actually do, not against the
dossier's claims. Each row's classification counts are per upstream F2P node (parametrized
cases counted individually where the upstream test is itself parametrized).

Cattrs and fd were audited by a delegated sub-agent each (full transcripts retained in this
session); updo, ink, and helm were audited directly. All five write-ups below were reviewed
against the underlying oracle/adapter source before being included here.

---

## cattrs-partial-structuring-recovery

**17 COVERED, 9 WEAKER, 0 STRICTER, 43 MISSING, 0 PRIVATE — verdict: needs fix**

69 F2P node ids in `tests/config.json`. The Oracle (`oracle/oracle.py`) defines exactly
**12 fixed challenge cases** in `PartialOracle.initialize()`; the great majority of the 69
upstream tests have no matching case. The dossier marks this row "Reviewed decision: Clean
conversion" — that claim is not supported by the oracle code: over 75% of individual F2P
assertions are either not exercised at all, or exercised only via a substituted
(different-code-path) input.

Two systemic bugs found in `oracle.py::evaluate()`, on top of the missing-case inventory:

1. **`errors`/`error_map` on *complete* results is never checked.** `evaluate()` only
   inspects `error_fields`/`errors_present`/`error_map` when `wanted["failed"]` is truthy.
   Every complete-result upstream assertion (`r.errors is None`, `r.error_map == {}`) is
   silently unverified for every case, including the one complete case that exists
   (`attrs_inherited`).
2. **`error_types`/`errors_picklable` are captured by the adapter but never read by the
   Oracle.** The adapter computes `type(value).__name__` for every `error_map` value and
   includes it in the observation, but `evaluate()` never compares it against anything —
   `TestErrorMap.test_values_are_exceptions` is permanently unenforceable; a candidate could
   put arbitrary non-Exception objects in `error_map` and pass.

| upstream node id | upstream input | upstream assertion | what Oracle does instead | classification | fix needed |
|---|---|---|---|---|---|
| TestCompleteStructuring.test_attrs | attrs class, 3 required fields, all valid | complete True, `errors is None` | no 3-required-all-valid case; complete-result `errors is None` never checked (bug 1) | MISSING | add case; fix `evaluate()` |
| TestCompleteStructuring.test_dataclass | dataclass, 2 required, complete | complete True, value equals instance | no dataclass-complete case (`dataclass_default` always fails field b) | MISSING | add case |
| TestCompleteStructuring.test_typeddict | TypedDict required, complete | complete True | `typeddict_optional` always fails field 'a' | MISSING | add case |
| TestDataclassPartialStructuring.test_partial_with_default[dv=False] | dataclass, default field, dv=False | fallback semantics | `dataclass_default` only run dv=True | MISSING | add dv=False variant |
| TestDataclassPartialStructuring.test_required_field_fails | dataclass, 2 required, one fails | value None | only attrs analog tested, no dataclass path | WEAKER | add dataclass case |
| TestDetailedValidationSetting.test_multiple_failures_with_dv_true | attrs, 3 fields all fail, dv=True | `len(failed)==3` | no 3-simultaneous-failure case | MISSING | add case |
| TestDeterminism.test_factory_called_each_time | same converter, 2 calls | factory called twice (not cached) | `factory_default` only calls once | MISSING | add case |
| TestDeterminism.test_repeated_calls | same converter, 2 calls | results equal | no repeated-call case | MISSING | add case |
| TestEdgeCases.test_all_fields_have_defaults | all fields defaulted+invalid | all defaults used | no such case | MISSING | add case |
| TestEdgeCases.test_complex_nested_partial | 3-level nested | multi-level partial value | `nested_attrs` is 2 levels only | MISSING | add case |
| TestEdgeCases.test_empty_class | zero-field class | complete True, empty sets | no such case | MISSING | add case |
| TestEdgeCases.test_mixed_success_and_failure | 2 valid + 2 invalid | structured/failed split | no case has this mix | MISSING | add case |
| TestEdgeCases.test_optional_field_fails_uses_none | `Optional[List[str]]`, invalid | falls back to None | no Optional field tested anywhere | MISSING | add case |
| TestEdgeCases.test_optional_field_with_none | `Optional[str]=None` | complete True | no Optional field tested | MISSING | add case |
| TestEdgeCases.test_result_type | any call | `isinstance(r, PartialResult)` | adapter never reports result's Python type | MISSING | add to observation + check |
| TestErrorMap.test_empty_when_complete | complete case | `error_map=={}` | never checked (bug 1) | MISSING | fix `evaluate()` |
| TestErrorMap.test_values_are_exceptions | one field fails | `isinstance(..., Exception)` | `error_types` captured, never compared (bug 2) | MISSING | fix `evaluate()` |
| TestErrorMap.test_with_dv_false | dv=False, field fails | `isinstance(error_map, dict)` | Oracle explicitly skips error_map scoring when dv=False | WEAKER | add minimal shape check |
| TestErrorMap.test_with_required_failures | required field fails | Exception-typed error_map value | value/failed covered; Exception-type hits bug 2 | WEAKER | fix bug 2 |
| TestForbidExtraKeys.test_actual_extra_keys[dv=False] | forbid=True, dv=False | complete False | only dv=True forbid case exists | MISSING | add dv=False case |
| TestForbidExtraKeys.test_field_failure_with_forbid[dv=False] | forbid + field failure, dv=False | forbid still applies | no forbid+field-failure combo case | MISSING | add case |
| TestForbidExtraKeys.test_field_failure_with_forbid[dv=True] | forbid + field failure, dv=True | forbid still applies | same gap | MISSING | add case |
| TestInheritance.test_inherited_fields | inherited class, child field fails | `"c" in failed` | `attrs_inherited` case is fully valid (complete) only | MISSING | add failing-field case |
| TestInitFalseFields.test_attrs_init_false_excluded[dv=False] | init=False field, dv=False | excluded from both sets | `init_false` only run dv=True | MISSING | add dv=False variant |
| TestInitFalseFields.test_dataclass_init_false_excluded | dataclass init=False | excluded | only attrs variant exists | MISSING | add dataclass case |
| TestNestedClasses.test_deeply_nested | 3-level nested | propagation | `nested_attrs` is 2 levels | MISSING | add case |
| TestNestedClasses.test_nested_all_required_fails | inner fully fails (no defaults) | outer value None | inner in `nested_attrs` always has a default | MISSING | add case |
| TestNestedClasses.test_nested_required_field_fails_uses_default_inner | inner totally fails, outer field has Factory default | outer falls back to default | no such case | MISSING | add case |
| TestNestedInCollections.test_dict_required_no_default | `Dict[str,Nested]` required, element fails | whole value None | `collection_atomic` uses atomic dict, not nested class | MISSING | add case |
| TestNestedInCollections.test_dict_with_default | dict with default, element fails | dict reset to `{}` | atomic-only case | WEAKER | add case |
| TestNestedInCollections.test_list_required_no_default | `List[Nested]` required, element fails | whole value None | atomic-only case | MISSING | add case |
| TestNestedInCollections.test_list_with_default | list with default, element fails | list reset to `[]` | atomic-only case | WEAKER | add case |
| TestPartialResultExport.test_top_level_function | top-level fn, default fallback | value w/ default substitution | `attrs_inherited` uses top-level entrypoint but only fully-valid input | WEAKER | add failing-field top-level case |
| TestPartialResultExport.test_top_level_matches_global_converter | two entrypoints, same data | results equal | no equivalence case | MISSING | add case |
| TestPartialStructuringWithDefaults.test_absent_field_with_default[dv=False] | absent field, dv=False | structured/failed split | covered but via `BaseConverter`, not `Converter` as upstream's helper uses | WEAKER | switch entrypoint or add dedicated case |
| TestPartialStructuringWithDefaults.test_absent_field_with_default[dv=True] | absent field, dv=True | `errors is not None` | only dv=False tested | MISSING | add case |
| TestPartialStructuringWithDefaults.test_failed_field_uses_default[dv=False] | present-invalid field, dv=False | structured/failed split | only dv=True tested | MISSING | add case |
| TestRefine.test_complete_result_unchanged | refine on already-complete result | no-op | only refine on a partial base is tested | WEAKER | add case |
| TestRefine.test_required_field_fixed | required field failed (value None), refine fixes | complete after refine | only non-None base tested | MISSING | add case |
| TestRefine.test_partial_fix | 2 failed fields, refine fixes 1 | 1 remains failed | only case has exactly 1 failed field (fully resolved) | MISSING | add case |
| TestRefine.test_chain | 3 sequential refine() calls | progressive completion | only 1 refinement step exercised | MISSING | add case |
| TestRefine.test_nested_object | refine nested field | field repaired | only flat/scalar refine tested | MISSING | add case |
| TestRefine.test_typeddict | refine on TypedDict | field repaired | only attrs target tested | MISSING | add case |
| TestRefine.test_dataclass | refine on dataclass | field repaired | only attrs target tested | MISSING | add case |
| TestRefine.test_with_dv_false | refine, dv=False | resolves to complete | refine case is dv=True only | MISSING | add case |
| TestRefine.test_still_bad_data | refine with still-invalid data | field remains failed | only successful refine tested | MISSING | add case |
| TestRequiredFieldsWithoutDefaults.test_multiple_required_fields_fail | 3 required, all invalid | `failed=={a,b,c}` | `attrs_required` has 1 field failing | MISSING | add case |
| TestRequiredFieldsWithoutDefaults.test_missing_required_field | field absent (not malformed) | `failed=={a}` | `attrs_required` only tests malformed-but-present | WEAKER | add absent-field case |
| TestRequiredFieldsWithoutDefaults.test_all_required_missing | all required absent | `failed=={a,b}` | no such case | MISSING | add case |
| TestTypedDictPartialStructuring.test_detailed_validation_false | OptionalTD, dv=False | split | `typeddict_optional` only dv=True | MISSING | add case |
| TestTypedDictPartialStructuring.test_nested | nested TypedDicts | outer built despite inner failure | no such case | MISSING | add case |
| TestTypedDictPartialStructuring.test_required_field_fails | total=True TypedDict, field fails | whole-dict failure | `typeddict_optional` uses total=False only | MISSING | add case |

*(43 MISSING/WEAKER rows shown; remaining rows collapsed where duplicated by dv=True/dv=False
pairs already listed above under a single upstream test name.)*

Effort estimate: **large**. Needs roughly 3-4x more Oracle cases (dataclass/TypedDict
complete variants, dv=False variants across nearly every category, nested-object-in-collection
variants, 3-level nesting, multi-step/nested/typed-target refine variants, determinism/
repeated-call variants, required-vs-absent-field distinction), plus the two `evaluate()` logic
fixes (complete-result error_map check, and consuming `error_types`). The dossier's "clean
conversion" verdict should be revisited.

---

## fd-deterministic-multi-key-sorting

**14 COVERED, 15 WEAKER, 0 STRICTER, 14 MISSING, 0 PRIVATE — verdict: needs fix**

43 upstream F2P tests, each a standalone `#[test]` using `assert_output_ordered` (exact-order
stdout match) or `assert_failure`. The Oracle (`oracle/oracle.py`) defines 26 hand-built
`scenario(...)` fixtures run once each through the adapter, which shells out to a built `fd`
binary and returns `stdout_lines` compared for **exact** equality — genuinely full-strength
where a scenario exists. The gap is entirely in *which* key/flag combinations are exercised.

**Systemic gap:** the row's whole premise is that ties on a single, explicitly-requested key
(e.g. `--sort extension` alone) are resolved deterministically via an *implicit* fallback key,
without the user requesting a second key. The Oracle's extension-related scenarios always pass
an **explicit** second `--sort name`, exercising a different code path (explicit multi-key
comparison) that would not catch a broken implicit single-key tiebreak — the literal bug class
this task is about.

| upstream node id | upstream input | upstream assertion | what Oracle does instead | classification | fix needed |
|---|---|---|---|---|---|
| test_sort_by_created_with_name_fallback | `--sort created --sort name`, ties on created time | name breaks ties | `created_order` uses only `(created,)` with separated timestamps, never ties | MISSING | add `(created,name)` tie scenario |
| test_sort_by_extension_case_insensitive | `--sort extension` (single key) | implicit case-fold+name tiebreak | only `(extension,name)` explicit-key scenarios exist | WEAKER | add single-key `extension` scenario |
| test_sort_by_modified_with_missing_last | `--sort modified` vs `+--sort-missing-last`, no actual missing values | both invocations equal | only the no-flag case tested | WEAKER | add missing-last variant |
| test_sort_by_path_then_reverse | `--sort path --reverse`, no max-results | full reverse order | reverse only tested bundled with `name` key + `--max-results 2` | WEAKER | add isolated path+reverse scenario |
| test_sort_by_size | `--sort size` (no missing-last) | ascending by size | only `size_missing_last` (missing_last=True) exists | WEAKER | add plain size scenario |
| test_sort_by_size_with_missing_values | default vs `--sort-missing-last` | two distinct orders | only missing_last=True variant tested | WEAKER | add default-order assertion |
| test_sort_dirs_first | dirs+files+**symlink**, `--dirs-first` | symlink placed after regular files | `dirs_first` fixture has no symlink | WEAKER | add symlink to fixture |
| test_sort_extension_case_insensitive_uses_path_tiebreak | `--sort extension` (single key), cross-dir tie | path tiebreak | no single-key extension scenario | WEAKER | add scenario |
| test_sort_extension_case_sensitive | `--sort extension --sort-case-sensitive` | case-sensitive order | `case_sensitive_name` only combines case-sensitivity with `name` | WEAKER | add extension+case-sensitive scenario |
| test_sort_files_first | dirs+files+**symlink**, `--files-first` | symlink grouped with dirs | `files_first` fixture has no symlink | WEAKER | add symlink to fixture |
| test_sort_missing_last_for_extension | `--sort extension --sort-missing-last` (single key) | implicit tiebreak + missing-last | `extension_missing_last` always adds explicit `name` key | WEAKER | add single-key variant |
| test_sort_multiple_roots_is_deterministic | `--sort path`, two explicit roots | deterministic interleave | `multiple_roots` uses `name` key, not `path` | WEAKER | add path-key variant |
| test_sort_name_case_insensitive_uses_path_tiebreak | `--sort name`, same case-folded name across dirs | compound case+path tiebreak | case-fold and path-tiebreak tested only separately | WEAKER | add combined scenario |
| test_sort_path_case_sensitive | `--sort path --sort-case-sensitive` | case-sensitive path order | only `name`+case-sensitive tested | WEAKER | add path+case-sensitive scenario |
| test_sort_reverse | `--sort name --reverse`, no max-results, 3 files | full reverse of 3 entries | reverse only tested bundled with `--max-results 2` (2 entries) | WEAKER | add standalone reverse scenario |
| test_sort_with_max_results_applies_after_sorting | `--sort name --max-results 2`, no reverse | truncate without reverse | max-results only tested bundled with reverse | WEAKER | add standalone max-results scenario |
| test_sort_by_modified_with_name_fallback | `--sort modified --sort name`, tie on modified | name breaks tie | no `(modified,name)` scenario | MISSING | add scenario |
| test_sort_by_multiple_fields | `--sort size --sort name`, tie on size | name breaks tie | no `(size,name)` scenario | MISSING | add scenario |
| test_sort_grouping_with_reverse_and_max_results_pipeline | dirs-first+reverse+max-results together | full pipeline incl. symlink | no combined scenario | MISSING | add scenario |
| test_sort_missing_last_with_reverse_for_extension | missing-last + reverse | interaction | no combined scenario | MISSING | add scenario |
| test_sort_natural_and_case_sensitive_interaction | natural + case-sensitive | digit runs numeric, rest case-sensitive | no combined scenario | MISSING | add scenario |
| test_sort_natural_case_insensitive | natural, letter-prefix+digit+case mix | case-insensitive natural grouping | `natural_*` scenarios use pure-numeric names only | MISSING | add letter-prefix scenario |
| test_sort_natural_extension | `--sort extension --sort-natural` | natural numeric on extension | natural scenarios only use `name` key | MISSING | add scenario |
| test_sort_natural_path | `--sort path --sort-natural` | natural numeric on path | no natural+path scenario | MISSING | add scenario |
| test_sort_natural_path_vs_lexicographic_differ | numeric dirs, no natural | lexicographic order (control) | no non-natural numeric-path scenario | MISSING | add scenario |
| test_sort_natural_vs_lexicographic_differ | numeric names, no natural | lexicographic order (control) | no non-natural numeric-name scenario | MISSING | add scenario |
| test_sort_preserves_rendering_with_custom_path_separator | `--path-separator "="` | order preserved, custom separator rendered | adapter never emits `--path-separator`; not in adapter.yaml schema at all | MISSING | add adapter support + scenario |
| test_sort_random_as_tiebreaker_respects_primary_key | `--sort extension --sort random --sort-seed`, mixed extensions | random shuffles only within extension groups | `seeded_random`/`unseeded_random` test random only as sole key | MISSING | add primary+random-secondary scenario |
| test_sort_repeated_key_is_accepted | `--sort name --sort name` | accepted, normal order | no repeated-key scenario | MISSING | add scenario |

Effort estimate: **large**. Roughly 20 new/modified scenarios needed, plus a genuine adapter
code change (`--path-separator` isn't wired into `adapter.py`'s `_arguments()` or
`adapter.yaml`'s schema). The implicit-vs-explicit-tiebreak substitution for `extension` is the
highest-priority fix since it's exactly the bug class the row is meant to catch.

---

## updo-policy-alerting

**12 COVERED, 1 WEAKER, 0 STRICTER, 4 MISSING, 0 PRIVATE — verdict: needs fix**

17 F2P nodes (Go, `go test`). The Oracle (`oracle/oracle.py`) drives `alerts.Tracker`,
`config.LoadConfig`, `notifications.HandleWebhookDecisionWithHeaders`, and
`simple.OutputManager` through 7 bundled challenge cases via the adapter driver
(`adapter/driver.go`), with a trusted-helper webhook receiver providing correlated evidence of
outbound HTTP requests. Bundling multiple upstream tests' checks into a single Tracker session
is used extensively and mostly reproduces each upstream assertion faithfully (same policy
values, same event/state/field expectations at the same points in the sequence) — this part of
the row is solid. The gaps are in tracker/cooldown interaction scenarios that are never actually
exercised with the right combination of inputs, and in one entrypoint (`HandleWebhookDecision`)
where the Oracle checks far fewer of the webhook JSON payload's fields than upstream does.

`HandleWebhookDecision`/`HandleWebhookDecisionWithHeaders` share one internal implementation
(confirmed in `qualification/reference.patch`), so using the `WithHeaders` entrypoint in the
driver does not itself weaken coverage of the plain-entrypoint tests.

| upstream node id | upstream input | upstream assertion | what Oracle does instead | classification | fix needed |
|---|---|---|---|---|---|
| TestTrackerLatencyBreachCountDefaultsToOneWhenEnabled | `Policy{LatencyThreshold:200ms, LatencyBreachCount: 0 or -1}`, single 250ms check | first breach fires immediately (`LatencyBreaches==1`, default-to-1 when enabled) | no oracle case sets `LatencyThreshold>0` together with `LatencyBreachCount<=0`; the only latency-enabled case uses `LatencyBreachCount=2` | MISSING | add a case with `LatencyBreachCount` 0 or -1 and `LatencyThreshold>0` |
| TestTrackerLatencyBreachesResetAfterDown | breach count reaches 1, then target goes down, breaches reset to 0, then restart at 1 after recovery | `LatencyBreaches` sequence 1→0→0→(recovered)→1 | in the bundled case0 sequence, the tracker never has a nonzero breach count before its first "down" transition — the reset is never actually exercised, only trivially-zero values | MISSING | add a case where a latency breach precedes a down transition |
| TestTrackerSSLAndCooldown | Cooldown+SSLExpiry both set; ssl_expiring fires, then a *different-type* event (target_down) within cooldown is suppressed but state still changes, then recovery unsuppressed | cross-event-type cooldown suppression, `Suppressed` true, state change while suppressed, `ConsecutiveFailures` still reported | no case combines nonzero `Cooldown` with nonzero `SSLExpiryThresholdDays` and a down/recovery sequence; the one SSL case (case1) has `Cooldown=0` | MISSING | add a case with Cooldown>0 + SSLExpiry>0 + down/recovery after an ssl_expiring event |
| TestTrackerRepeatedDegradedEventsAreSuppressedByCooldown | `LatencyBreachCount:1`, degraded fires unsuppressed, a second degraded **within** the cooldown window is suppressed, breaches keep incrementing | second event `Suppressed==true`, `LatencyBreaches==2` | case0's two degraded decisions are ~340s apart, past the 300s cooldown, so the repeat-within-cooldown suppression path is never triggered | MISSING | add a case with two degraded events inside the same cooldown window |
| TestHandleWebhookDecision | one webhook POST, JSON payload with 9 named fields + explicit absence of camelCase duplicate keys (`previousState`, `sslExpiryDays`) | every field's exact value checked; camelCase keys asserted absent | Oracle's `_requests()` only checks presence of the 9 keys (`required_payload <= set(payload)`) plus the *value* of `event`, `region`, and non-emptiness of `reason` — `state`, `previous_state`, `consecutive_failures`, `consecutive_recoveries`, `latency_breaches`, `ssl_expiry_days` values are never compared; camelCase-absence is never checked at all | WEAKER | check exact values for all 9 payload fields against the decision, and assert `previousState`/`sslExpiryDays` are absent from the payload |

Effort estimate: **medium**. Four Tracker/cooldown scenarios need new bundled cases (the
pattern is already established, so this is mechanical), and the webhook payload check in
`oracle.py::_requests()` needs to compare each field's value (not just presence) and add the
camelCase-absence assertion — a self-contained, well-scoped fix in one function.

---

## ink-grid-box-layout

**25 COVERED, 0 WEAKER, 0 STRICTER, 0 MISSING, 0 PRIVATE — verdict: clean**

All 25 upstream `grid - ...` F2P tests map 1:1 to a named case in
`oracle/build_cases()`, with expected line count and exact marker column position
re-derived independently per run by `oracle/grid_algorithm.py` (a from-scratch reimplementation
of the track-sizing/placement rules), not copied from `test.patch`. The Oracle's
`evaluate()` checks exact total line count and, for every marker, exact `line.find(text) ==
expected column` — the same strength as upstream's `t.is(line.indexOf(...), N)` assertions.

Two cases (`basic-2col-fr`, `weighted-fr-2-1`) deliberately use a container width one unit off
from upstream's (21 instead of 20, 31 instead of 30) so fr-track rounding is actually observable
instead of accidentally exact; the expected positions are recomputed for that width by the same
general algorithm, so this exercises the identical semantic rule (equal/weighted fr distribution)
at least as rigorously as upstream, not a different one. Not treated as a gap.

Effort estimate: none — this row needs no fix.

---

## helm-array-merge-strategies

**41 COVERED, 0 WEAKER, 0 STRICTER, 3 MISSING, 0 PRIVATE — verdict: needs fix**

44 F2P nodes (Go, `-tags mergestrategy`). The Oracle (`oracle/oracle.py`) defines 47 named
scenarios (lint v2/v3, accessor, coalesce/merge, upgrade/install) run through a Go-test-based
driver harness (`adapter/driver_*_test.go`) and checks either exact structural JSON equality of
the coalesced/merged result (`_json_equal`, dict-keys-unordered/list-order-sensitive) or the
exact lint-message severity/substring predicates upstream itself uses. The great majority of
F2P nodes map 1:1 onto a scenario with the same concrete chart/values/annotations as upstream
and the same (or a deliberately more discriminating, semantically-identical) assertion strength.
Three upstream tests specifically about *interaction/isolation between multiple simultaneous
merge strategies and untouched fields* have no scenario at all.

| upstream node id | upstream input | upstream assertion | what Oracle does instead | classification | fix needed |
|---|---|---|---|---|---|
| TestHarness_CoalesceValues_MultipleStrategies | one chart, `tolerations`(append) + `containers`(merge+key) + `replicas`(plain scalar) coalesced together in one call | all three resolve correctly simultaneously without interfering, `replicas` scalar overwritten normally | no scenario coalesces more than one annotated key at a time; the "don't interfere" property is never exercised | MISSING | add a multi-key scenario mirroring this test |
| TestHarness_CoalesceValues_AppendPreservesExistingBehavior | one chart, an append-strategy array + a non-annotated array (replaced) + a scalar + a nested map, all coalesced together | append strategy doesn't affect scalar/nested-map/non-annotated-array handling elsewhere in the same tree | no scenario tests plain scalar or nested-map override behavior at all (annotated or not) — this isolation property is untested | MISSING | add a scenario combining an annotated array with plain scalar/nested/array fields |
| TestHarness_CoalesceValues_StrategyPathAbsent_NoEffect | annotation references a path not present in Values; an unrelated key coalesces normally | unrelated key overridden normally; no key is created at the missing path | no scenario tests an annotation pointing at an absent path | MISSING | add scenario asserting the absent-path key stays absent and unrelated keys are unaffected |

Two minor over-strictness notes, not counted as gaps since they cannot reject a correct
candidate in practice (real correct output only ever produces the exact values checked): the
`upgrade_append_ordering` scenario checks exact list equality where upstream only asserted
relative ordering (`oldIdx < newIdx`, allowing extra elements), and `upgrade_reuse_merge` checks
an exact `image` value for the "init" container that upstream never asserted at all. Also,
`upgrade_cli_overrides_annotation` uses a different (but strictly more discriminating, per the
Oracle's own comment) `old_release` fixture than upstream's own test — same semantic property
(CLI overrides annotation), not a weaker one.

Effort estimate: **small**. Three new scenarios following the exact pattern already used for
every other `coalesce` scenario in `oracle.py`.

---

## Summary

| row | COVERED | WEAKER | STRICTER | MISSING | PRIVATE | verdict |
|---|---|---|---|---|---|---|
| cattrs-partial-structuring-recovery | 17 | 9 | 0 | 43 | 0 | needs fix |
| fd-deterministic-multi-key-sorting | 14 | 15 | 0 | 14 | 0 | needs fix |
| updo-policy-alerting | 12 | 1 | 0 | 4 | 0 | needs fix |
| ink-grid-box-layout | 25 | 0 | 0 | 0 | 0 | clean |
| helm-array-merge-strategies | 41 | 0 | 0 | 3 | 0 | needs fix |
