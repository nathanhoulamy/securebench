# F2P coverage audit — group A

Rows audited: `returns-validated-error-accumulation`, `ts-pattern-match-each`,
`sqlfmt-create-table-ddl-formatting`, `skrub-duration-encoding`,
`python-statemachine-state-data-scoping`, `bandit-structured-nosec-directives`.

Method: for each row, every upstream `f2p_node_ids` entry (config.json) was
matched by hand against its literal `tests/test.patch` assertion(s), then
checked against the actual Oracle case bank
(`benchmarks/deep-swe/v2/hidden/<row>/oracle/oracle.py`) and adapter
(`benchmarks/deep-swe/v2/evaluation_inputs/<row>/adapter/`). Classification is
against the code, not the dossiers. "Same shape, different label/token/value"
substitutions (e.g. a canonical function swapped in for the specific upstream
one, or a token-suffixed string in place of a literal) were treated as
COVERED when the assertion strength and construction shape are unchanged;
a different arity, element count, branch, backend, or nesting order was
treated as WEAKER/MISSING since a targeted mutant could exploit exactly that
gap.

---

## returns-validated-error-accumulation

**159 F2P nodes. COVERED 91, WEAKER 18, MISSING 50, STRICTER 0, PRIVATE 0. Verdict: needs fix.**

Root-cause groups (see per-node detail folded into groups; full per-node list
available on request — this table lists representative nodes per group):

| Group / node(s) | Upstream input & assertion | Oracle does instead | Class | Fix |
|---|---|---|---|---|
| `Validated.from_value`/`from_failure`/`from_validated`/`from_result` never invoked | `test_apply_with_from_value`, `test_from_value`, `test_from_failure`, `test_from_validated`, `test_from_result_classmethod`, `test_left_identity`, `test_right_identity`, `test_validated_from_result_then_accumulate` (8 nodes) | Adapter always builds containers via `_from_spec` (`Valid(...)`/`Invalid(...)` constructors), never calls the classmethods; `_op_converters`'s `from_result` branch exists but no case selects it | MISSING | Add ops/cases that call `from_value`, `from_failure`, `from_validated`, and select `direction="from_result"` |
| Dead adapter branches never selected by any case | `test_roundtrip_success`, `test_roundtrip_failure`, `test_pointfree_bind`, `test_pointfree_alt`, `test_swap_roundtrip_valid` (5 nodes) | `adapter.py` has `roundtrip_success`/`roundtrip_failure` converters directions and `pointfree` `bind`/`alt` names and `swap` `double` param, but oracle never emits a case using them | MISSING | Add one case per dead branch |
| Fold.collect parametrize table: 8/12 params untested | `test_fold_collect_validated[iterable0..11]` — only index 3,8,9 reproduced | Oracle's `fold` op has 6 cases; untested: empty list, 1 valid, 2 valid, 1 invalid, invalid-then-valids, valids-then-invalid, 2-elem-tuple invalids, 5-item interleave | MISSING (8 nodes) | Add ~8 fold cases matching the missing parametrize rows |
| Fold.collect "key test" (2 pure invalids) + order robustness | `test_fold_collect_validated[iterable7]` (upstream's own docstring: "THIS IS THE KEY TEST... a naive implementation returns Invalid(('a',)), losing 'b'"); `test_fold_collect_validated_preserves_order` (non-monotonic labels to rule out an accidental sort) | Only 3-invalid and 500-invalid variants tested; order case uses sequential e0/e1/e2 labels | WEAKER | Add the literal 2-invalid-only case and an order case with non-monotonic labels |
| Binary apply/combine single/1-elem-tuple, empty-tuple shapes | `test_apply_invalid_invalid_accumulates`, `test_apply_preserves_order`, `test_apply_empty_error_tuple`, `test_combine_first_invalid`, `test_combine_second_invalid`, `test_combine_both_invalid_multi_errors`, `test_combine_n_all_invalid`, `test_combine_n_single_valid` (8 nodes) | Oracle's binary-apply invalid+invalid case only uses 2-element tuples; binary-combine only tests valid+valid and invalid+invalid, never exactly-one-side-invalid; combine_n never tests all-invalid or arity-1 | WEAKER/MISSING | Add binary 1-elem-tuple apply case, empty-tuple apply case, one-side-invalid combine cases, combine_n all-invalid and arity-1 cases |
| `.map()`/`.alt()` on Invalid/Valid + hand-written alt laws | `test_map_invalid`, `test_map_chain`, `test_map_invalid_chain`, `test_alt_valid`, `test_alt_identity`, `test_alt_composition` (6 nodes) | No dedicated `map` op (only tested indirectly via `pointfree.map_`, and only on Valid); `alt` op only tested on Invalid, never on Valid; no case for the identity/composition laws | MISSING | Add a `map` op with Invalid + chained cases; add an `alt`-on-Valid case; add identity/composition law cases |
| `Validated.do`: 3 of 5 branches | `test_do_second_invalid`, `test_do_both_invalid_short_circuits`, `test_do_three_valid` | Only "first invalid" and "both valid" (2-arg) tested | MISSING | Add valid-then-invalid, both-invalid, and 3-arg `do` cases |
| Equality/repr/inequality edge cases | `test_valid_inequality`, `test_invalid_inequality`, `test_repr_invalid` (1-tuple repr `('e',)` trailing-comma), `test_valid_equality` (string sub-case) | No case checks two differently-valued same-kind containers are `!=`; no 1-element Invalid repr case | MISSING (3) / WEAKER (1) | Add inequality and 1-elem-repr cases |
| `decorator` "successfully catches configured exception" branch | `test_validated_decorator_with_exceptions` | Cases test bare-decorator failure and uncaught-exception-passes-through, never the catch-succeeds-with-parse_int path | MISSING | Add a `with_exceptions`+`parse_int` case |
| `None`-as-value edge cases | `test_invalid_with_none_errors`, `test_valid_with_none` | No case ever uses `None` as a payload (all string/int) | MISSING | Add two `None`-payload cases |
| `collect_all`/`partition` degenerate branches | `test_fold_collect_all_validated_all_invalid`, `test_fold_collect_all_vs_collect`, `test_partition_all_valid`, `test_partition_all_invalid` | No all-invalid `collect_all` case; no all-valid/all-invalid `partition` case | MISSING | Add 4 cases |
| pointfree partial-branch coverage | `test_pointfree_bind_validated`, `test_pointfree_apply`, `test_pointfree_lash` | Each upstream test asserts 2-3 branches; oracle exercises only 1 branch of each | WEAKER (3) | Add the missing branch per op |
| Stress-size mismatch | `test_deeply_nested_apply_does_not_stack_overflow` (upstream: `min(sys.getrecursionlimit(), 2000)`) | Oracle's fold-collect stress case uses fixed 500 | WEAKER | Raise to match `sys.getrecursionlimit()`-based sizing |
| Raw 5-level nested apply | `test_accumulate_five_way` | Only tested via `Fold.collect` (different code path), not raw chained `.apply()` at 5 levels | WEAKER | Add a 5-level `apply` chain case |
| `swap` single-elem, double-swap, repr | `test_swap_invalid` (1-elem), `test_swap_roundtrip_valid`, `test_swap_repr` | Only 2-elem swap tested; `double` param dead; no repr/str check on swap output | WEAKER/MISSING (3) | Add cases |

**Effort to fix: large** (~60-70 new oracle cases needed; mostly mechanical
additions following existing patterns, a few need new adapter surface for
`map` / classmethod invocation).

---

## ts-pattern-match-each

**85 F2P nodes. COVERED 66, WEAKER 7, MISSING 12, STRICTER 0, PRIVATE 0. Verdict: needs fix.**

| Node(s) | Upstream input & assertion | Oracle does instead | Class | Fix |
|---|---|---|---|---|
| `.exhaustive() without fallback should throw NonExhaustiveError` | `matchEach(42).with(P.number.lt(0),...).exhaustive()` throws when nothing matches, no fallback | No case uses `op:"exhaustive"` (plain, no fallback) with a non-matching input; only matched-`exhaustive` and `exhaustive_with_fallback` throwing cases exist | MISSING | Add an `exhaustive`, no-fallback, no-match case |
| `.returnType()` behavior (runtime + type) | `test_..returnType() should constrain all handler return types` | No case/op ever exercises `.returnType()` at all | MISSING | Add a runtime case and note in `type-return-types-are-arrays` |
| `P.select()` type in mixed literal+select pattern | `test_..P.select() type should match pattern context` | No type probe; no runtime case uses the exact `{status:'ok', code:P.select()}` mixed pattern | MISSING | Add case |
| `.with()` 3+ patterns | `test_..should work with three or more patterns` | `multi-pattern-with` case only uses 2-pattern `.with()` | MISSING | Add 3-pattern case |
| `.narrow()` runtime behavior | `test_..narrow() should narrow the input type...` (checks `results==['a:42']`) | Only the type-probe half exists (`type-narrow-narrows-subsequent-with`); no runtime case ever calls `.narrow()` | MISSING (runtime half) | Add a runtime `narrow()` case |
| `.otherwise()` return-type **union of distinct types** | `test_..otherwise() return type should be array with union of output types` (`(1\|2)[]`) | Bundled type probe's otherwise handlers both return `number`, never distinct literal types to union | MISSING | Add a dedicated union-of-literals probe |
| toFunction: throw / independent-selection / narrow-typing | `test_..toFunction() should throw NonExhaustiveError`, `..independent selection results`, `..compiled function accepts narrowed input type after narrow` | Only toExhaustiveFunction's throw+selection-independence tested; no toFunction-specific throw or select case; no narrow+toFunction type probe | MISSING (3) | Add toFunction-specific cases |
| toExhaustiveFunction return type | `test_..toExhaustiveFunction() should have correct return type` | Not in the `type-return-types-are-arrays` bundle (only toFunction/toPartialFunction are) | MISSING | Add to bundle or new probe |
| toPartialFunction independent selection | `test_..toPartialFunction() should produce independent selection results across calls` | `compiled-to-partial-function-never-throws` case uses no `P.select()` | MISSING | Add select-based toPartialFunction case |
| `match` + `.exhaustive()` / `match` + selections | `test_..match exhaustive works unchanged`, `test_..match with selections works unchanged` | Only one `api:"match"` case exists (`op:"run"`, no select) | MISSING (2) | Add two `match`-api cases |
| Systemic: "return type should be X" family use positive-compile probes, not `Equal<>` | `.run()`/`.otherwise()`/`.exhaustive()` array-type, toFunction/toPartialFunction exact-signature checks (7 nodes) | `type_case`'s "positive" probes only require the code to *compile* (e.g. `.map(n=>n*2)`), which a too-wide type (`any[]`) would also satisfy — doesn't test exact type identity the way upstream's `Expect<Equal<...>>` does | WEAKER (7, cross-cutting) | Needs a design change: a companion check that a *wrong-but-compiling* wider type is rejected (e.g. assign to a precisely-typed variable) without leaking the expected type into the probe |
| Discriminated-union "matches correct variant" tested with only 1 of 2 variants, wrong terminal op | `test_..should match the correct variant of a discriminated union` (uses `.run()`, tests rect AND circle) | Oracle's only discriminated-union case uses `.exhaustive()` and only the `rect` variant | WEAKER (lenient — property well-covered elsewhere) | Optional: add the `.run()` two-variant case for full fidelity |

**Effort to fix: medium** (~12 explicit gaps are mostly a case each; the
systemic type-check weakness is the one non-mechanical piece, needing a
genuinely different type-probe pattern for "exact return type" nodes).

---

## sqlfmt-create-table-ddl-formatting

**32 F2P nodes. COVERED 31, WEAKER 1, MISSING 0, STRICTER 0, PRIVATE 0 (one node has an unobservable isinstance-check subtlety, noted below but not counted as PRIVATE since a strong functional proxy exists). Verdict: needs fix (near-clean).**

| Node | Upstream input & assertion | Oracle does instead | Class | Fix |
|---|---|---|---|---|
| `TestDdlUtilities.test_parse_ddl_table_unconstrained_columns` | Same `_parsed_lines` fixture; asserts `"customer_id" in unconstrained_names` **and** `len(unconstrained) + len(constrained) == column_count` (complement invariant) | `_check_ddl_basic_orders` only checks `"customer_id" in unconstrained` — never checks the complement/count invariant | WEAKER | Add `len(unconstrained_columns)+len(constrained_columns)==column_count` to `_check_ddl_basic_orders` |

Minor observability note (not counted as a defect): `test_parse_ddl_table_returns_ddl_table`'s literal `isinstance(result, DdlTable)` can't be observed through the JSON-only adapter transport; the Oracle's "not None + correct serialized shape" check is the strongest available proxy and is reasonable, but this equivalence isn't documented as a PRIVATE accommodation anywhere in the Oracle's comments.

**Effort to fix: small** (one assertion line).

---

## skrub-duration-encoding

**130 F2P nodes (43 backend-parametrized functions × 3 backends + 1 non-parametrized `test_resolution_auto_all_nulls`). COVERED 44, WEAKER 0, MISSING 86, STRICTER 0, PRIVATE 0. Verdict: needs fix — large, systemic.**

Every one of the 43 parametrized upstream test functions is instantiated by
`pytest` three times — once per `df_module` backend
(`pandas-nullable-dtypes`, `pandas-numpy-dtypes`, `polars`) — and each
instantiation is its own F2P node (per the audit's parametrize rule). The
Oracle's `_case_encode`/`_case_reject_column`/etc. helpers bake exactly **one**
fixed `backend` into each case (defaulting to `"pandas-numpy"`, sometimes
overridden to `"polars"` or `"pandas-nullable"` — but never more than one per
underlying assertion). No case is ever replayed against the other two
backends for the same assertion.

| Representative node(s) | Upstream input & assertion | Oracle does instead | Class | Fix |
|---|---|---|---|---|
| Every `test_*[pandas-nullable-dtypes]` / `[pandas-numpy-dtypes]` / `[polars]` triple (129 nodes total across 43 functions) | Same assertion, run once per backend via the `df_module` fixture | Oracle case hardcodes one `backend` value per assertion (e.g. `auto_day`→`pandas-numpy` only; `auto_hour`→`polars` only; `scaling_standard_mean`→`pandas-numpy` only) | MISSING for the other 2 backends per function (86 nodes); COVERED for the 1 tested backend (43 nodes) | Loop each case over all 3 backends (mechanical: wrap `_build_cases()`'s `_case_encode`/`_case_reject_column`/`_case_selector_duration`/`_case_to_float_rejects`/`_case_to_str_rejects`/`_case_table_vectorizer_routes` calls in a backend loop) |
| `test_resolution_auto_all_nulls` (not backend-parametrized upstream) | `pd.Series([pd.NaT,pd.NaT], dtype="timedelta64[ns]")`, `encoder.resolution_=="minute"` | `resolution_auto_all_nulls` case, exact match | COVERED | — |

A backend-specific bug (e.g. correct dtype handling on pandas but broken on
polars `Duration`, or vice versa) would currently only be caught if it
happens to land on the one backend each case fixed — a candidate could
target the untested 2/3 of the backend×behavior matrix with impunity. The
per-assertion numeric bounds/exactness/sign/membership *strength* that IS
tested is faithfully matched to upstream (verified: exact `==` for
small-integer literals, identical `< bound` tolerances, sign-only where
upstream is sign-only, aggregate-mean-only and single-index-only checks
matching upstream's own narrower assertions) — the backend gap is the only
real defect, but it is very large in node count.

**Effort to fix: small-to-medium** (conceptually a few lines — parametrize the
existing case-builder over the 3 backends — but triples the number of
Evaluation-environment invocations per run, which has a runtime-cost
implication worth flagging alongside the fix).

---

## python-statemachine-state-data-scoping

**72 F2P nodes. COVERED 67, WEAKER 3, MISSING 1, STRICTER 1, PRIVATE 0. Verdict: needs fix (minor).**

| Node(s) | Upstream input & assertion | Oracle does instead | Class | Fix |
|---|---|---|---|---|
| `test_datavar_with_default_and_type[async]`/`[sync]` | `DataVar(default=0, type=int)`; asserts `result=={"count":0}` **and** `isinstance(result["count"], int)` | `_check_datavar_full` only checks dict-value equality (`data=={"count":0,"items":[]}`); a float `0.0` would pass the equality check (`0==0.0` in Python) but fail upstream's `isinstance` check | WEAKER (2) | Have the adapter report the Python type name of `count` explicitly; assert it's `int` |
| `test_state_without_data_backward_compat` | `State(initial=True)` (no `data=`); `sm = SM()` (never started/activated); `sm.get_state_data(sm.s1) is None` | Oracle's closest case (`edge_transition_to_no_data_state`) checks `get_state_data` on a data-less state only *after* the machine is started and has transitioned through it — never the "constructed but never started" scenario upstream tests | WEAKER | Add a construct-only (no `send`, arguably no `start`) case if the harness protocol supports it |
| `test_scxml_datamodel_parsed_and_applied_to_state` | A **different**, simpler SCXML document (`<data id="x" expr="0"/>`, one var); `result["x"]==0` | The single `scxml_combined` case only reproduces the *other* SCXML test's document (`counter=10, label='hello'`, two vars) | MISSING | Add a second SCXML case using the single-var document |
| `TestStateDataPersistence.test_pickle_round_trip_preserves_state_data` (verified directly: `oracle.py:311-319`, case `pickle_roundtrip_and_continue` at `oracle.py:792-813`, upstream body at `test.patch:472-480`) | `sm.get_state_data(sm.s1)["count"]==0` before pickling; `pickle.loads(pickle.dumps(sm))`; `restored.get_state_data(restored.s1)["count"]==7`. **Only these two data assertions** — upstream never sends another event to the restored instance. | `_check_pickle_roundtrip_and_continue` reproduces both upstream assertions (`before_pickle`, `restored_value`) but *additionally* requires `pickle_roundtrip_ok` (the unpickle itself must succeed) and, crucially, `send_after_restore_ok` — the case sends a `go` event to the restored machine and asserts it succeeds, a behavior upstream's own test never exercises or asserts | STRICTER | Drop (or move to a separate, non-F2P-labeled robustness case) the post-restore `send`/`send_after_restore_ok` requirement so this node's pass/fail tracks exactly upstream's two assertions |

**Effort to fix: small** (4 targeted additions/adjustments; this row's Oracle is
otherwise unusually thorough — 14 case-groups explicitly duplicated
sync/async via `add_both` specifically to avoid dropping half of upstream's
`[async]`/`[sync]` parametrization, and several multi-assertion upstream
tests are legitimately bundled into single richer cases without losing any
individual assertion, e.g. `lifecycle_full` faithfully reproduces
`test_reenter_state_reinitializes_data` + `test_self_transition_reinitializes_data`
+ `test_multiple_entry_exit_cycles` together).

---

## bandit-structured-nosec-directives

**69 F2P nodes. COVERED 36, WEAKER 3, MISSING 30, STRICTER 0, PRIVATE 0. Verdict: needs fix — large.**

The Oracle's case bank (`CASES` in oracle.py) has only **33 total cases** for
69 required F2P nodes; even accounting for legitimate bundling (metrics are
checked on every case alongside findings, so several `test_0NN_metrics_*`
nodes are validly covered by their findings-twin case), roughly 30 nodes have
no corresponding case at all.

| Node(s) | Upstream input & assertion | Oracle does instead | Class | Fix |
|---|---|---|---|---|
| `test_014_region_specific_name_and_id_suppresses` | `# nosec-begin B602, subprocess_popen_with_shell_equals_true` (id **and** name together in one list) | Cases test id-only and name-only separately, never combined | MISSING | Add case |
| `test_028_next_line_name_suppresses` | `# nosec-next-line subprocess_popen_with_shell_equals_true` | Only next-line-by-**id** tested | MISSING | Add case |
| `test_036_next_line_inside_region_blanket`, `test_039_end_is_not_regular_nosec`, `test_040/041_whitespace_variants`, `test_042_list_separators`, `test_043/044_empty_tests_means_blanket` | Various directive-grammar edge cases (nested next-line-in-region, `# nosec-end B602` not treated as its own directive, tab/space whitespace, mixed `,`/` ` separators, trailing-space-only tests list) | No case reproduces any of these 7 specific grammar edge cases | MISSING (7) | Add 7 cases |
| `test_050_region_applies_to_multiline_call`, `test_051_next_line_applies_to_multiline_call`, `test_052_next_line_targets_first_code_token_line` | Region/next-line directive placed **before** a multiline call, suppressing the whole call; next-line skipping to the first real token inside a paren-continuation | No case has begin/end or next-line surrounding an entire multiline call from outside it (the one multiline case in the bank, `multiline_statement_wide_suppression`, has `begin` appearing *inside* the call, a different scenario matching a non-F2P test) | MISSING (3) | Add 3 cases |
| `test_061/062/063/064_*_union`/`*_does_not_unsuppress` | Next-line-blanket-then-region-specific union; two-stacked next-line-blankets; specific-directive-then-different-id-inline-doesn't-unsuppress (region and next-line variants) | No case reproduces any of these 4 union/non-interference scenarios | MISSING (4) | Add 4 cases |
| `test_074_metrics_blanket_elsewhere_in_statement_overrides_specific`, `test_123_selector_all_and_B602_counts_as_specific` | Metrics-specific edge cases (inline blanket elsewhere in a multiline statement overriding a specific inline; `all & B602` counts as specific not blanket) | No case | MISSING (2) | Add 2 cases |
| `test_077_region_does_not_leak_out_of_file` | Specific-id unterminated region, 1 statement, runs to EOF | `region_unterminated_runs_to_eof` case uses **blanket** + 2 statements — different shape (id-specificity + count) | WEAKER | Add the exact specific-id/1-statement variant |
| `test_079/080_midline_directive_targets_next_statement` (region and next-line) | `x = 1  # nosec-begin B602` / `# nosec-next-line B602` — directive placed after other code on the same line | No case | MISSING (2) | Add 2 cases |
| `test_082_region_begin_on_closing_line_is_not_retroactive`, `test_082_two_regions_union_specific_sets`, `test_085_region_blanket_overrides_unknown_specific` | Begin-on-a-multiline's-closing-paren-line not retroactive; two nested **specific** (non-blanket) regions union their sets; outer-unknown-specific + inner-blanket still blankets | No case | MISSING (3) | Add 3 cases |
| `test_098_next_line_case_insensitive`, `test_105_next_line_applies_across_windows_newlines` | `# NOSEC-NEXT-LINE` case-insensitivity; next-line directive across CRLF | Case-insensitivity and CRLF are both tested only for the **region** form (`case_insensitive_directives`, `crlf_newlines`), never for next-line | MISSING (2) | Add next-line variants of both |
| `test_100/101_comment_trailer_still_parses` (region and next-line) | `# nosec-begin B602 # trailing` / `# nosec-next-line B602 # trailing` | No case | MISSING (2) | Add 2 cases |
| `test_113_selector_union_implicit_whitespace` | `# nosec-begin B602 B603` (implicit whitespace union, no `|`) | Only the explicit-`|` union form is tested | MISSING | Add case |
| `test_120_selector_nested_negation_double_negation_suppresses_this` | `!(!B602)` | No case | MISSING | Add case |
| `test_nosec_end_ends_region_before_line_with_directive` | `# nosec-end` on a line that would itself also trigger a finding — end takes effect before that line's own check | No case | MISSING | Add case |
| `test_ignore_nosec_disables_region_directives`, `test_ignore_nosec_disables_next_line_directives` | Each upstream test asserts **both** `ignore_nosec=False` (suppressed) and `=True` (not suppressed) on the *same, single-directive-type* code | Oracle's one combined case mixes both directive types into one snippet and only exercises `ignore_nosec=True` | WEAKER (2) | Split into two per-directive-type cases, each testing both flag values |

**Effort to fix: large** (~30 new cases needed — mechanical given the
existing `_case(...)` pattern, but a substantial volume of missing grammar/
edge-case coverage for a security-suppression-directive parser, which is
exactly the kind of feature where grammar edge cases are where real bugs
hide).

---

## Summary table

| Row | F2P nodes | COVERED | WEAKER | STRICTER | MISSING | Verdict | Est. effort |
|---|---:|---:|---:|---:|---:|---|---|
| returns-validated-error-accumulation | 159 | 91 | 18 | 0 | 50 | needs fix | large |
| ts-pattern-match-each | 85 | 66 | 7 | 0 | 12 | needs fix | medium |
| sqlfmt-create-table-ddl-formatting | 32 | 31 | 1 | 0 | 0 | needs fix (near-clean) | small |
| skrub-duration-encoding | 130 | 44 | 0 | 0 | 86 | needs fix | small-medium (mechanical, systemic) |
| python-statemachine-state-data-scoping | 72 | 67 | 3 | 1 | 1 | needs fix (minor) | small |
| bandit-structured-nosec-directives | 69 | 36 | 3 | 0 | 30 | needs fix | large |

Note: a direct spot-check during final QA found one additional STRICTER
finding in `python-statemachine-state-data-scoping` (the pickle round-trip
case requires the restored instance to also process a `send` successfully,
which upstream's test never asserts) that the per-row audit pass had missed;
it has been folded into that row's table and counts above. The skrub
single-backend-per-case pattern, the bandit case-bank/node-count gap, and the
returns-validated dead classmethod-dispatch branches were independently
re-verified directly against `oracle.py` during final QA and confirmed
accurate.
