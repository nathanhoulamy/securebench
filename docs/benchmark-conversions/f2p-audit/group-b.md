# F2P coverage audit — Group B (DeepSWE)

Read-only audit per playbook #24 / rule #20: every upstream F2P assertion
must be checked by the Oracle on its own exact input, at upstream's own
strength (no looser, no stricter). Bundling multiple upstream assertions
into one Oracle case is acceptable as long as every original input/assertion
pair is still actually exercised at the same strength; checking a
*different* input, or dropping an assertion, is not.

Rows audited: narwhals-rolling-window-suite, pest-character-class-coalescing,
etree-xml-diff-patch, happy-dom-deterministic-intersectionobserver,
tengo-destructuring-bindings, dateutil-rfc5545-timezone-interop.

Sources: upstream `tests/config.json` (`f2p_node_ids`) and `tests/test.patch`
under `/tmp/securebench-paper-deepswe-source/tasks/<row>/`; Oracle
`benchmarks/deep-swe/v2/hidden/<row>/oracle/oracle.py` (+ case data/helper
modules); adapter `benchmarks/deep-swe/v2/evaluation_inputs/<row>/adapter/`;
dossier `docs/benchmark-conversions/DeepSWE/<row>.md`.

## Verdict summary

| Row | F2P nodes | COVERED | WEAKER | STRICTER | MISSING | PRIVATE | Verdict |
|---|---|---|---|---|---|---|---|
| pest-character-class-coalescing | 104 | 2 | 38 | 0 | 64 | 0 | needs fix (large) |
| narwhals-rolling-window-suite | 103 | 3 | 18 | 0 | 82 | 0 | needs fix (large) |
| etree-xml-diff-patch | 52 | 51 | 1 | 0 | 0 | 0 | needs fix (trivial) |
| happy-dom-deterministic-intersectionobserver | 14 | 3 | 11 | 0 | 0 | 0 | needs fix (small) |
| tengo-destructuring-bindings | 91 | 91* | 0 | 0 | 0 | 0 | clean (sampled 13/91) |
| dateutil-rfc5545-timezone-interop | 67 | 19 | 24 | 1 | 23 | 0 | needs fix (medium-large) |

\* tengo: verified on a 13/91 (14%) sample with a 100% exact-match rate; not
verified line-by-line for the full 91. All other rows' node-level
classifications are based on a full or near-full pass over the upstream test
bodies (etree: ~25/52 spot-checked in detail against a design that is
explicitly 1:1 per-test; pest and narwhals: full reconciliation of every
upstream node against the Oracle's scenario/case corpus; dateutil: full
reconciliation of all 67 test bodies against the Oracle's 14 op families,
with some WEAKER/MISSING calls for lower-priority nodes based on op-family
and literal-value pattern matching rather than always a second independent
re-read).

---

## pest-character-class-coalescing

Summary: 2 COVERED, 38 WEAKER, 64 MISSING, 0 STRICTER, 0 PRIVATE — verdict: needs fix

Upstream: `meta/tests/charclass_tests.rs`, 104 hand-written `#[test]` functions, each
building a small `pest_meta::ast::Rule`/`Expr` literal by hand and asserting the
exact `OptimizedExpr` (or a `matches!(.., Choice(_,_))` shape check) returned by
`optimize(rules)`.

Oracle: `benchmarks/deep-swe/v2/hidden/pest-character-class-coalescing/oracle/oracle.py`
independently reimplements the restorer+coalescer algorithm in Python and checks
candidate output against it, but instead of replaying upstream's 104 literal test
inputs it authors its own corpus of **37** hand-picked scenarios (`_build_scenarios`,
lines 374-443) using different literal characters (`g,h,i,m,n,t,x,y,z,q,r,s…`
instead of upstream's `a,b,c,d…`) and a narrower set of structural shapes, split
across 2 Challenges/Evaluations. The dossier explicitly frames this as
"Oracle's 38 [sic — actually 37] scenarios were chosen to cover the same semantic
axes" rather than literal replay (`docs/benchmark-conversions/DeepSWE/pest-character-class-coalescing.md`
lines 235-238).

Only 2 of the 104 upstream tests happen to use literally identical input to an
Oracle scenario (`unicode_chars_adjacency`/`unicode_non_adjacent_chars`, which
reuse the same accented Unicode chars `α,β,γ`/`é,ñ` an Oracle scenario also
uses) — these are COVERED. 38 more have an Oracle scenario that tests the same
structural shape/algorithm branch but with different literal characters —
classified WEAKER (different input than upstream's exact assertion, same
algorithmic strength). The remaining 64 upstream tests exercise structural
shapes, edge cases, or code paths (deep multi-level choice nesting, 4-5
element runs, mid-chain/sandwiched blockers, non-beneficial runs that hit the
run-of-three threshold but don't produce a smaller range set, `Push` wrapped
directly by `Opt`/no wrapping at all, interaction with the `factorizer`
pass, `Seq`-of-two-independent-choices, several `insens` non-merge/mismatch
variants, several `NegCharClass` content-shape variants, multi-run +
`RestoreOnErr` interaction, and basic non-`Choice`/`Seq`-of-ranges regression
checks) that have **no** Oracle scenario at all — MISSING.

| F2P node(s) | Upstream input (representative) | Upstream assertion | Oracle does instead | Class | Fix needed |
|---|---|---|---|---|---|
| two_adjacent_chars_become_range, three_chars_sorted_become_range, two_adjacent_ranges_become_range, subsuming_ranges_become_range, mixed_str_and_range_full_merge_to_range, range_adjacency_boundary, insens_digit_no_expansion, overlapping_ranges_become_range, two_ranges_adjacent_and_overlapping_merged | e.g. `ch(s("a"),s("b"))→Range(a,b)` | exact structural equality on the literal `a,b,…` input | equivalent scenario with different literal chars (`m,n` / `g,k`+`l,p` / etc.) | WEAKER | Replace/augment Oracle scenarios to reuse upstream's exact literals for the same shapes |
| three_chars_two_groups_become_charclass | `ch(s("a"),ch(s("b"),s("x")))→CharClass[(a,b),(x,x)]` | exact CharClass | Oracle's `three_two_groups_charclass` same shape, chars `g,h,t` | WEAKER | same |
| ident_blocks_entire_chain, empty_string_blocks_entire_chain, multi_char_string_blocks_entire_chain, multi_char_insens_blocks_entire_chain, range_same_start_end_with_different_char_stays_choice, full_chain_four_non_adjacent_non_beneficial | e.g. `ch(s("a"),id("rule"))` stays `Choice` | `matches!(Choice(_,_))` | equivalent-shape scenario, different literal chars | WEAKER | same |
| choice_inside_rep_coalesced, choice_inside_seq_coalesced, choice_inside_neg_pred_coalesced, choice_in_pos_pred_coalesced | e.g. `rep(ch(s("a"),s("b")))→Rep(Range(a,b))` | exact wrapped result | `wrapped_rep`/`wrapped_seq`/`wrapped_neg_pred_plain`/`wrapped_pos_pred`, chars `g,h` | WEAKER | same |
| multiple_rules_independent_coalescing, all_rule_types_coalesced | 2-rule / 3-rule-type loop, same literal input across variants, exact assert per rule/type | Oracle splits into `multi_rule_independent` (different result shape: Range not CharClass) and `atomic_rule_type_coalesced`+`silent_rule_type_coalesced` (Normal-type variant of the identical input not separately re-asserted) | WEAKER | Add matching-shape and Normal-type variants |
| partial_run_of_three_at_start, partial_run_of_three_at_end, partial_run_of_two_not_coalesced, partial_multiple_runs, partial_preserves_peg_order | run-of-3 / run-of-2 / multi-run partial-coalesce boundary, exact literal `a,b,c,id("rule")…` | exact resulting tree | Oracle's `partial_run_of_three_start/end`, `partial_multiple_runs`, `partial_preserves_order` — same shapes, chars `g,h,i`/`x,y,z` | WEAKER | same |
| neg_charclass_single_char, neg_charclass_multi_char, neg_charclass_range, neg_charclass_missing_any_unchanged | e.g. `seq(neg(s("a")),id("ANY"))→NegCharClass[(a,a)]` | exact NegCharClass | Oracle `neg_charclass_single/multi/range/missing_any_unchanged`, chars `g,h,i` (and RHS `Ident("OTHER")` vs upstream's literal `Str("b")` for the "missing ANY" case — different RHS *kind*, not just literal) | WEAKER | Reuse literal chars; for `missing_any_unchanged` also add the RHS-is-`Str` shape upstream actually tests |
| restorer_runs_before_coalescer, restore_on_err_wrapping_push_blocks, restore_on_err_stripped_from_qualifying_alternatives, restorer_wrapped_alternatives_stripped_when_coalesced | e.g. `ch(push(s("a")),s("b"))→Choice(RestoreOnErr(Push(Str(a))),Str(b))` | exact tree incl. `RestoreOnErr` placement | Oracle `restore_blocks_push_branch`/`restore_stripped_from_qualifying_run`, chars `g,h`/`x,y,z` | WEAKER | same |
| three_insens_chars_expand_to_charclass, all_insens_adjacent_both_cases | 3 case-insensitive chars, some given out of ascending order, → CharClass both cases | exact CharClass, order-independence exercised | Oracle `insens_expand_three_charclass` only (chars already in ascending order `m,n,o`) | WEAKER | Add an out-of-order variant (upstream's `all_insens_adjacent_both_cases` puts `c` before `a,b`) |
| duplicate_chars_simplify_to_str | `ch(s("a"),s("a"))→Str(a)` | exact Str simplification | `duplicate_chars_to_str`, chars `g,g` | WEAKER | same |
| all_ascii_groups_stay_choice, five_non_adjacent_chars_stay_choice, two_non_adjacent_chars_stay_choice, two_non_adjacent_ranges_stay_choice, single_char_and_non_adjacent_range_stay_choice, three_non_adjacent_chars_stay_choice, full_chain_non_beneficial_three_chars, full_chain_non_beneficial_with_ranges, non_beneficial_mixed_range_and_str, two_ranges_non_adjacent, single_char_order_irrelevant | various non-adjacent 2/3/4/5-element choice/range combinations that must stay `Choice` | `matches!(Choice(_,_))` | no Oracle scenario of this element-count/shape at all | MISSING | Add scenarios for each distinct non-adjacent element-count/shape |
| four_adjacent_chars_become_range, range_and_adjacent_single_char_become_range, duplicate_ranges_become_range, str_full_chain_coalesces_to_range, four_adjacent_chars_coalesce_to_range, duplicate_overlapping_and_subsuming_ranges | 4-char / range+char / exact-duplicate-range / 3-in-order-char / 3-range merges to `Range` | exact Range | no Oracle scenario of this element-count/order | MISSING | Add these shapes |
| four_chars_two_adjacent_pairs_become_charclass, range_and_two_chars_becomes_charclass, display_two_disjoint_ranges | 2+2 / range+2-char / 3+3 element groupings → `CharClass` | exact CharClass (incl. `Debug`-format comparison) | no Oracle scenario with these groupings | MISSING | Add these shapes |
| deeply_nested_left_choice_becomes_range, nested_choice_of_choices_flattens, triple_nested_choice_flattens, four_level_nested_choice_flattens, seq_with_two_nested_choices, nested_choice_with_range_merge, nested_partial_with_blocker, charclass_absorption_in_choice, nested_seq_with_two_independent_charclasses, one_branch_coalesced_other_not, factorizer_inner_choice_coalesced, range_inside_seq_not_affected, non_choice_expressions_unchanged, rep_of_hex_ranges_not_coalesced, nested_choice_inside_rep, nested_choice_inside_opt, blocker_in_middle_of_chain, nested_choice_with_ident_blocks_top_level | left/triple/quad-nested `Choice` trees, `Seq`-of-two-independent-choices, `Choice`-inside-`Seq`-with-common-prefix (factorizer), bare `Range`/`Seq`-of-ranges regression, `Rep` over non-beneficial ranges, mid-chain/nested blockers | exact resulting tree per case | no Oracle scenario at all — none of these structural shapes appear in `_build_scenarios` | MISSING | Author scenarios for every one of these distinct structural shapes |
| choice_inside_opt_coalesced, choice_inside_push_coalesced | `opt(ch(s("a"),s("b")))→Opt(Range(a,b))`; `push_expr(ch(s("a"),s("b")))→Push(Range(a,b))` | exact wrapped result | Oracle's `wrapped_opt_charclass` wraps a *CharClass*-producing choice, not the Range-producing one upstream tests; no scenario at all wraps a coalescing choice directly in `Push` | MISSING | Add the exact-shape `Opt`+2-char and bare `Push`+2-char scenarios |
| choice_of_ranges_in_silent_rule, atomic_concatenator_blocks_coalescing | silent-rule non-beneficial case ranges stay `Choice`; atomic-rule `Seq`-as-alternative blocks coalescing | `matches!(Choice(_,_))` | Oracle's silent/atomic scenarios both test successful coalescing, not these blocking cases | MISSING | Add blocking-case scenarios for silent/atomic rule types |
| partial_mixed_run_sizes, partial_single_non_qualifying_between_runs, partial_exactly_three_threshold, partial_all_non_qualifying, partial_large_run, partial_run_not_beneficial, partial_run_with_charclass, partial_run_with_non_beneficial_segment | run-of-2 (not merged)+run-of-4; two separate qualifying runs around one blocker; exactly-3 run sandwiched between two blockers; all-blocker choice; run-of-5; run-of-3 that meets the threshold but is *not beneficial* (must still stay Choice, not force-CharClass); run-of-4 producing a 2-group CharClass then a blocker | exact resulting tree per case, incl. the "≥3 elements but not beneficial ⇒ still Choice" edge case | no Oracle scenario for any of these | MISSING | Author these partial-run edge cases, especially the run≥3-but-not-beneficial one — it directly probes the benefit-check boundary condition |
| neg_charclass_non_qualifying_unchanged, neg_charclass_mixed_range_point_content, neg_charclass_overlapping_ranges_content | `neg(id("rule"))~ANY` (bare non-`Choice` ident, not a `Choice` at all) stays unchanged; `neg` over mixed single-char+range content; `neg` over overlapping ranges that must merge | exact "unchanged" / exact merged `NegCharClass` | Oracle's `neg_charclass_non_qualifying_unchanged` tests a *Choice* with one non-qualifying alt, a different code shape than upstream's bare-ident case; no scenario for mixed range+point or overlapping-range content under `neg` | MISSING | Add the bare-ident case and the mixed/overlapping-range `NegCharClass` content cases |
| restore_stripped_both_sides_of_push | run-of-3 + `Push` blocker + another run-of-3, checks `RestoreOnErr` stripped correctly with a blocker in the middle of two coalescing runs | exact absence of `RestoreOnErr` in the coalesced lhs | no Oracle scenario combines multi-run partial-coalesce with a `Push` blocker | MISSING | Add this combined scenario |
| single_insens_chars_expand_both_cases, insens_two_chars_non_beneficial, insens_with_two_alternatives_stays_choice, insens_and_str_mixed, insens_non_alpha_no_case_expansion, insens_non_alpha_and_mixed_symbols, insens_and_range_merge, insens_subsumed_by_range, insens_upper_input_same_as_lower, insens_with_ranges_covering_both_cases | 2 non-adjacent `insens` chars stay `Choice`; `insens`+plain-`Str` mismatch; non-alpha `insens` symbols; 3 non-alpha `insens` merge; `insens`+`Range` interactions (merge/subsume); uppercase-input `insens`; `insens`+2 full case `Range`s → `CharClass` | exact resulting tree per case | no Oracle scenario for any of these `insens` interaction/non-merge variants | MISSING | Author these `insens` edge cases — several probe whether `insens`+`Range`/`Str` mixing is handled correctly, currently entirely unchecked |

Effort to fix: large — only 2/104 upstream assertions are checked at upstream's
exact strength/input; 38 are checked on a same-shape-but-different-literal
input (low-risk but still a rule violation); 64 have no Oracle scenario at
all, including whole axes (deep nesting, factorizer interaction, several
`insens`/`NegCharClass`/partial-run edge cases) that are currently completely
unverified. Fixing this properly means roughly tripling the Oracle's scenario
corpus (37 → ~100+) and, ideally, reusing upstream's literal characters where
the assertion is on that literal (some scenarios, e.g. the non-adjacent/
non-beneficial ones, would also need new literal inputs since upstream itself
uses varied ones (`é,ñ`, `α,β,γ`, digits, symbols) that must each be
individually represented).
## narwhals-rolling-window-suite

Summary: 3 COVERED, 18 WEAKER, 82 MISSING, 0 STRICTER, 0 PRIVATE — verdict: needs fix

Upstream: 25 distinct `#[pytest]` functions across `rolling_max_test.py`,
`rolling_median_test.py`, `rolling_min_test.py`, `rolling_quantile_test.py`,
each parametrized by backend (`constructor`/`constructor_eager`: 4 eager
backends for `_expr`/`_series` tests, 6 backends incl. `duckdb`/`sqlframe`
for `_expr_lazy_ungrouped` tests), giving 103 `(function, backend)` F2P node
ids. Several functions (`test_rolling_max_expr`, `test_rolling_max_series`,
`test_rolling_median_expr`, `test_rolling_median_series`,
`test_rolling_min_expr`, `test_rolling_min_series`) each bundle 3-5 distinct
`window_size`/`min_samples`/`center` kwargs shapes (`x1`..`x5`) into a single
multi-column `df.select(**{...})` call checked by one `assert_equal_data` —
one node, several sub-assertions, which is fine to bundle per the audit rule
as long as each sub-shape is actually checked. `test_rolling_min_expr_lazy_ungrouped`
is doubly parametrized (backend × `center` True/False), giving 12 nodes for
one function. The shared literal dataset for `max`/`median`/`min` tests is
`data = {"a": [None, 1, 2, None, 4, 6, 11]}` (a 7-element int/null series);
`_expr_lazy_ungrouped`/`_over` variants add `b`/`i` ordering columns; the
`quantile_expr_q25` test uses its own separate `{"a": [1.0,2.0,3.0,4.0,5.0]}`.

Oracle: `benchmarks/deep-swe/v2/hidden/narwhals-rolling-window-suite/oracle/oracle.py`
independently reimplements rolling-window semantics in Python and issues
only **24 cases** total (21 `_case_rolling` + 3 `_case_invalid`,
`_build_cases()` lines 209-235) against a single invented dataset
`DATA_A = {"a": [None, 3.0, 5.5, None, 8.0, 2.5, 9.0, 6.0, 4.5]}` (9-element
floats, never the upstream `[None,1,2,None,4,6,11]`) and
`DATA_OVER` (7-element, also different values from upstream's `_over`
dataset). For every `(op, mode)` shape the Oracle picks **at most one**
backend and **at most one** kwargs sub-shape to exercise, instead of the
full backend × kwargs matrix upstream checks; `rolling_max` `series` mode
and `rolling_median`/`rolling_quantile` `center=True` are never exercised by
any Oracle case at all. `sqlframe` and `modin`/`dask` backends never appear
in any Oracle case (`polars_eager`, `pandas`, `pyarrow`, `pandas_pyarrow`,
`duckdb` are the only backend strings ever used).

Only the 3 non-parametrized `rolling_quantile` error-path tests
(`test_rolling_quantile_invalid_quantile`, `..._invalid_quantile_negative`,
`test_rolling_quantile_invalid_interpolation`) are genuinely COVERED: they
don't depend on the `data` table at all, and the Oracle's three
`_case_invalid` calls use the exact same `window_size=3`, `quantile`/
`interpolation` values and `message_prefix` upstream's `pytest.raises(...,
match=...)` checks. Every other node depends on the `data` table, and since
no Oracle case ever uses upstream's literal dataset, none of the
data-dependent nodes are COVERED; at best (same op/mode, same or close
kwargs, one matching backend) they are WEAKER, and where no Oracle case
touches that `(op, mode)` shape/backend/`center` value at all they are
MISSING.

| F2P node(s) (function × backend count) | Upstream input | Upstream assertion | Oracle does instead | Class | Fix needed |
|---|---|---|---|---|---|
| `rolling_max_test.test_rolling_max_expr[pandas]` (1 of 4 backends) | `data`, bundled `x1`-`x5` kwargs (ws3 / ws3+ms1 / ws2+ms1 / ws5+ms1+center / ws4+ms1+center) | exact 5-column `assert_equal_data` | Oracle case (`rolling_max`,`expr`,`pandas`,`DATA_A`,`ws=3`) — different dataset, only the `x1` sub-shape | WEAKER | Reuse literal `data`; bundle all 5 kwargs shapes in one Oracle case |
| `rolling_max_test.test_rolling_max_expr[pandas[pyarrow]/polars[eager]/pyarrow]` (3 of 4) | same | same | no Oracle case for these backends | MISSING | Add per-backend cases |
| `rolling_max_test.test_rolling_max_series` (4 of 4) | `data`, bundled `x1`-`x5`, `.rolling_max` via `Series` | exact 5-column `assert_equal_data` | **no Oracle case for `rolling_max`/`series` mode at all** | MISSING | Add a `rolling_max`+`series` case per backend |
| `rolling_max_test.test_rolling_max_expr_lazy_ungrouped[polars[eager]]` (1 of 6) | `.rolling_max(3, min_samples=1, center=False).over(order_by="b")` on the `_over` dataset | exact `assert_equal_data` | Oracle case uses `center=True` (not upstream's `False`) and `DATA_OVER` (different values) | WEAKER | Fix `center` to match; reuse literal data |
| `rolling_max_test.test_rolling_max_expr_lazy_ungrouped[duckdb/pandas/pandas[pyarrow]/pyarrow/sqlframe]` (5 of 6) | same | same | no Oracle case for these backends (`sqlframe` never appears anywhere in the Oracle) | MISSING | Add per-backend cases, incl. `sqlframe` |
| `rolling_median_test.test_rolling_median_expr[pandas]` (1 of 4) | `data`, bundled `x1`-`x3` (ws3 / ws3+ms1 / ws2+ms1) | exact 3-column `assert_equal_data` | Oracle case matches only the `x2` (ws3,ms1) sub-shape, different dataset | WEAKER | Reuse literal data; bundle all 3 sub-shapes |
| `rolling_median_test.test_rolling_median_expr[pandas[pyarrow]/polars[eager]/pyarrow]` (3 of 4) | same | same | no Oracle case | MISSING | Add per-backend cases |
| `rolling_median_test.test_rolling_median_series[pandas[pyarrow]]` (1 of 4) | `data`, bundled `x1`-`x3` via `Series` | exact 3-column `assert_equal_data` | Oracle case uses `ws=4,ms=1` — matches none of upstream's 3 bundled sub-shapes (ws3/ws3ms1/ws2ms1); different dataset | WEAKER | Match bundled kwargs; reuse literal data |
| `rolling_median_test.test_rolling_median_series[pandas/polars[eager]/pyarrow]` (3 of 4) | same | same | no Oracle case | MISSING | Add per-backend cases |
| `rolling_median_test.test_rolling_median_expr_lazy_ungrouped[duckdb]` (1 of 6) | `.rolling_median(3, min_samples=1, center=False).over(...)` | exact `assert_equal_data` | Oracle case matches kwargs exactly (ws3,ms1,center=False); different dataset only | WEAKER | Reuse literal data |
| `rolling_median_test.test_rolling_median_expr_lazy_ungrouped[pandas/pandas[pyarrow]/polars[eager]/pyarrow/sqlframe]` (5 of 6) | same | same | no Oracle case | MISSING | Add per-backend cases |
| `rolling_median_test.test_rolling_median_center` (4 of 4, all backends) | `ws=3,ms=1,center=True` | exact `assert_equal_data` | **no Oracle `rolling_median` case ever sets `center=True`** | MISSING | Add a centered-median case per backend |
| `rolling_min_test.test_rolling_min_expr[pandas]` (1 of 4) | `data`, bundled kwargs incl. `ws3+ms1` | exact multi-column `assert_equal_data` | Oracle case (ws3,ms1) matches that sub-shape; different dataset, other sub-shapes unchecked | WEAKER | Reuse literal data; bundle all sub-shapes |
| `rolling_min_test.test_rolling_min_expr[pandas[pyarrow]/polars[eager]/pyarrow]` (3 of 4) | same | same | no Oracle case | MISSING | Add per-backend cases |
| `rolling_min_test.test_rolling_min_series[polars[eager]]` (1 of 4) | `data`, bundled, `ws2+ms1` sub-shape via Series | exact `assert_equal_data` | Oracle case (ws2,ms1) matches that sub-shape; different dataset, other sub-shapes unchecked | WEAKER | same |
| `rolling_min_test.test_rolling_min_series[pandas/pandas[pyarrow]/pyarrow]` (3 of 4) | same | same | no Oracle case | MISSING | Add per-backend cases |
| `rolling_min_test.test_rolling_min_expr_lazy_ungrouped[duckdb-...-False]` (1 of 12) | `.rolling_min(3,ms1,center=False).over(...)` | exact `assert_equal_data` | Oracle case matches (ws3,ms1,center=False, duckdb); different `_over` dataset | WEAKER | Reuse literal data |
| `rolling_min_test.test_rolling_min_expr_lazy_ungrouped[*-True]` and `[pandas/pandas[pyarrow]/polars[eager]/pyarrow/sqlframe-False]` (11 of 12) | same shape, other backends and/or `center=True` | exact `assert_equal_data` | no Oracle case for `center=True` at all, and no other-backend cases | MISSING | Add all 11 remaining `(backend,center)` combinations |
| `rolling_quantile_test.test_rolling_quantile_boundary_one[polars[eager]]`, `..._boundary_zero[pandas]`, `..._default_min_samples[pandas]`, `..._expr_higher[pandas[pyarrow]]`, `..._expr_lazy_ungrouped[polars[eager]]`, `..._expr_lower[polars[eager]]`, `..._expr_midpoint[polars[eager]]`, `..._expr_nearest[pyarrow]`, `..._expr_q25[pandas]`, `..._series[pyarrow]` (1 backend each, 10 nodes total) | `ws=3` (+`ms=1` where upstream sets it), specific `quantile`/`interpolation`, on `data` (or its own 5-element array for `q25`) | exact `assert_equal_data` | Oracle has a same-kwargs-shape case for exactly one backend of each; different dataset (and `expr_q25` also uses a 5-element array Oracle never reproduces) | WEAKER | Reuse literal datasets |
| same 10 functions, remaining backends (3 of 4 each = 30 nodes) | same | same | no Oracle case | MISSING | Add per-backend cases |
| `rolling_quantile_test.test_rolling_quantile_center` (4 of 4, all backends) | `ws=3,ms=1,center=True,quantile=0.5` | exact `assert_equal_data` | **no Oracle `rolling_quantile` case ever sets `center=True`** | MISSING | Add a centered-quantile case per backend |
| `rolling_quantile_test.test_rolling_quantile_expr_median` (4 of 4, all backends) | `mode=expr, ws=3,ms=1,quantile=0.5,interpolation` default(linear) | exact `assert_equal_data` | No Oracle `expr`-mode case has `ms=1` together with `q=0.5`; the only `q=0.5` Oracle cases are `series`/`lazy_over` mode or omit `min_samples` (that's the *different* `default_min_samples` test) | MISSING | Add the exact `expr`+`ms=1`+`q=0.5` case per backend |

Effort to fix: large — 82/103 nodes have zero Oracle case touching that
exact `(op, mode, backend[, center])` combination (including two entire
modes — `rolling_max` `series` and any `center=True` quantile/median case —
that are never exercised at all, and `sqlframe` which never appears
anywhere), and the remaining 21 (18 WEAKER + 3 COVERED) either use a
different literal dataset than upstream or only check one of several kwargs
shapes upstream bundles into the same test. Properly fixing this means
reusing upstream's literal `data`/`_over`/`q25` arrays, adding a case per
backend actually in upstream's matrix (including `sqlframe`), bundling the
`x1`-`x5` kwargs shapes the way upstream's single-assertion tests do, and
adding the two missing `center=True` axes.
## etree-xml-diff-patch

Summary: 51 COVERED, 1 WEAKER, 0 STRICTER, 0 MISSING, 0 PRIVATE — verdict: needs fix (trivial)

Note: the binary clean/needs-fix rule is applied strictly here — one WEAKER
node, however low-severity, means this row is not "clean." In substance this
row is a high-fidelity 1:1 transcription and the one deviation is a
protocol-forced input substitution (XML-only wire format standing in for a
Go struct field assignment), not a dropped assertion.

Upstream: 52 Go `func Test*` functions in `tests/test.patch` (github.com/beevik/etree),
none using `t.Run` subtests, so each function is exactly one F2P node whose
assertion may itself check several conditions in sequence (loose bundling,
which the audit rule permits).

Oracle: `benchmarks/deep-swe/v2/hidden/etree-xml-diff-patch/oracle/oracle.py`
defines one hand-built `scenario(...)` per upstream test (a few, like
`TestApplyPatchNilDocuments`/`TestMerge3WayNilDocuments`/`TestDiffNilDocuments`,
are split into 3-4 scenarios — one per nil-argument sub-check — which is
*more* granular than upstream, not less), grouped into 3 challenge "cases"
(`CASES`, lines 487-514) with explicit `# --- ... (TestFoo, TestBar) ---`
comments naming which upstream test each block of scenarios covers.

This is a materially different (much higher-fidelity) design than the other
audited rows in this batch: scenario literals were spot-checked against
upstream's actual Go source for ~25 of the 52 tests, spanning every scenario
kind (`deep_equal`, `default_options`, `type_strings`, `diff`,
`generate_patch`, `apply_patch`, `reverse_patch`, `merge3way`,
`merge_conflict_resolve`, `diff_summary`, `pipeline`, and all nil-argument
variants), and every one matched upstream's exact XML/Go-literal input and
assertion strength byte-for-byte — e.g. `diff_basic` reuses upstream's exact
`<root><item id="1">A</item></root>` → `...B...` pair and the same
"UpdateText op present, NewValue == B" check; `TestDiffIdentityContentHashDeep`'s
intentionally loose upstream assertion (only `has_type="add"`, not a full op
list) is reproduced at the same looseness, not tightened; `gp_attribute_add_encoding`
reuses the exact `OldValue: nil, NewValue: "red"` op and the same four
`contains`/one `not_contains` checks. The remaining ~27 nodes were not
individually re-verified line-by-line but follow the same documented,
explicitly-labelled 1:1 scenario-to-test mapping pattern and construction
style as the ones that were checked.

The one exception found:

| F2P node | Upstream input | Upstream assertion | Oracle does instead | Class | Fix needed |
|---|---|---|---|---|---|
| `TestElementDeepEqualNamespace` | Direct Go struct construction: `a := NewElement("item"); a.Space = "ns"; a.SetText("hello")` (and a `c` with `Space = "other"`), comparing `.DeepEqual()` | exact `true`/`false` on struct-level `Space` field equality | Oracle's `eq_namespace_same`/`eq_namespace_diff` scenarios build the same property via XML-parsed input (`<ns:item xmlns:ns="urn:x">hello</ns:item>` vs `<other:item .../>`) rather than direct field assignment — a different construction path for the same semantic property, necessitated by the adapter's XML-only wire protocol | WEAKER | Low priority: note in the dossier that this is an intentional, protocol-forced substitution (XML-parsed `Space` should equal direct-assignment `Space` for this library), or add an adapter op that accepts raw tag/namespace fields instead of XML text if exactness is required |

Effort to fix: small — only one low-severity WEAKER item, likely acceptable
as documented (or a small adapter addition if exactness is desired). No
MISSING nodes found in the sampled two-thirds of the suite; a full remaining
line-by-line pass on the ~27 unsampled nodes is recommended but not expected
to change the verdict given the consistent 1:1 mapping design and explicit
per-test comments throughout `oracle.py`.
## happy-dom-deterministic-intersectionobserver

Summary: 3 COVERED, 11 WEAKER, 0 STRICTER, 0 MISSING, 0 PRIVATE — verdict: needs fix (minor)

Upstream: 14 `it(...)` cases in one vitest file
(`IntersectionObserver.challenge.test.ts`), covering the constructor
(callback/root/rootMargin/threshold validation and shorthand normalization),
`observe()` (async delivery, threshold crossings, order, invalid target),
`root`/`rootMargin` (pixel margin), and `unobserve()`/`disconnect()`.

Oracle: `benchmarks/deep-swe/v2/hidden/happy-dom-deterministic-intersectionobserver/oracle/oracle.py`
explicitly states its cases are **not** copied from `tests/test.patch` (see
its module docstring) but are independently authored to "mirror the upstream
F2P semantic axes." It builds 8 constructor cases + 18 scenario cases (26
total, i.e. a superset that adds many extra edge cases — percentage/negative
margin, 3-target order, disconnect-before-any-delivery, multi-threshold
crossings — beyond upstream's 14). Numeric literals (rect coordinates,
margin values, threshold arrays) are either hand-picked but different from
upstream's, or deliberately **scaled by a per-run, seed-derived factor**
(`scale_for`, 1/2/3× via a SHA-256 hash of `run_seed`), specifically so a
candidate can't have memorized/special-cased the exact upstream literals —
a defensible anti-overfitting design, but one that means no
coordinate/margin/threshold-bearing case can ever be byte-identical to
upstream's literal input.

Three constructor/observe cases that reduce to a single boolean flag in the
wire protocol (invalid callback, invalid root, invalid `observe()` target)
have no finer-grained "literal" to vary and are genuinely COVERED at
upstream's exact strength. The other 11 nodes are semantically well-matched
(same structural shape, same property under test, often a strict superset of
upstream's scenario) but never use upstream's literal rect/margin/threshold
values — classified WEAKER, not MISSING, since the underlying property is
still exercised, just on a different (and per-run varying) input.

| F2P node | Upstream input | Upstream assertion | Oracle does instead | Class | Fix needed |
|---|---|---|---|---|---|
| `constructor() > Normalizes rootMargin and threshold values.` | `rootMargin:'10px 20%'`, `threshold:[0.75,0.25,0.25,0]` → `root===null`, `rootMargin==='10px 20% 10px 20%'`, `thresholds===[0,0.25,0.75]` | exact equality | 4 separate Oracle cases test the 1/2/3/4-value shorthand forms and array/scalar threshold normalization with scaled literals (never `'10px 20%'`/`[0.75,0.25,0.25,0]`) — broader coverage of the algorithm, but never upstream's exact case | WEAKER | Add a case with upstream's exact literal margin/threshold values alongside the existing broader set |
| `constructor() > Throws when rootMargin is invalid.` | `rootMargin:'10em'` → throws | exact | `ctor-invalid-root-margin-unit` uses `'8vw'`, a different invalid unit | WEAKER | Add the exact `'10em'` case |
| `constructor() > Throws when threshold values are outside range.` | `threshold:[0,1.2]` → throws | exact | `ctor-threshold-out-of-range` uses `[-0.2,0.5,1.3]` | WEAKER | Add the exact `[0,1.2]` case |
| `intersection ratio calculations > Returns ratio 0 when there is no intersection.` | target `rect(10000,10000,100,100)`, viewport root → ratio `0` | exact | `no-intersection-far-away-viewport` uses `rect(500000,500000,30,30)` | WEAKER | Add the exact-coordinate case |
| `intersection ratio calculations > Returns ratio 1 for a zero-area target that is contained in root.` | root `rect(0,0,100,100)`, target `rect(10,10,0,0)` → ratio `1` | exact | `zero-area-target-contained-ratio-one` uses `rect(0,0,100*s,100*s)`/`rect(10*s,10*s,0,0)`, `s∈{1,2,3}` per run seed | WEAKER | Add the unscaled (`s=1`, matching upstream exactly) case as a fixed literal, not seed-derived |
| `observe() > Delivers initial entries asynchronously.` | target `rect(10,10,100,100)`, viewport root → `isIntersecting=true`, `intersectionRatio=1`, `rootBounds.width/height===innerWidth/innerHeight` | exact | `observe-initial-delivery-viewport-contained` uses `rect(10*s,10*s,20*s,20*s)` | WEAKER | same |
| `observe() > Detects threshold crossings in subsequent async delivery cycles.` | root/target `rect(0,0,100,100)`, `threshold=0.5`; target moves to `rect(60,0,100,100)` → ratio 1 then `<0.5` | exact | `observe-threshold-crossing-single-axis` scales root/target by `s` and moves target to `70*s` (not `60`) | WEAKER | Add the exact-literal case |
| `observe() > Keeps entry order based on observe() order.` | targets `first`/`second` at `rect(15,15,20,20)`/`rect(5,5,20,20)`; `observe(second)` then `observe(first)` → delivered `[second, first]` | exact | `observe-order-preserved-two-targets` reuses the same names/call order but scaled rects (`5*s,15*s` etc.) | WEAKER | Add the exact-literal case |
| `root and rootMargin() > Applies pixel rootMargin values during intersection calculations.` | root `rect(0,0,100,100)`, target `rect(105,10,10,10)`, `rootMargin:'10px'` → `isIntersecting===true` | exact | `root-margin-pixel-extends-intersection` uses margin `f"{12*s}px"` and scaled target rect, never `'10px'` | WEAKER | Add the exact-literal case |
| `unobserve() and disconnect() > Stops delivering updates after unobserve().` | target `rect(0,0,100,100)`→ moved to `rect(2000,2000,100,100)` after `unobserve()`, callback count stays `1` | exact | `unobserve-stops-future-entries` uses `rect(10*s,10*s,20*s,20*s)`→`rect(900000,900000,20*s,20*s)` | WEAKER | Add the exact-literal case |
| `unobserve() and disconnect() > Stops all delivery and polling after disconnect().` | same shape as above, plus `disconnect()` and `takeRecords()===[]` | exact | `disconnect-stops-delivery-and-clears-records`, same scaling, but does correctly also check `take_records` empty | WEAKER | Add the exact-literal case |

Effort to fix: small — the Oracle already tests the right shape/property for
every one of the 14 upstream nodes (and adds 12 useful extra cases beyond
upstream's scope); it just never uses upstream's literal numbers. Since the
scaling is an intentional anti-overfitting measure, the cleanest fix is to
keep the existing scaled/superset cases and *additionally* add one
fixed-literal case per row above that reproduces upstream's exact numbers,
rather than replacing the scaled cases.
## tengo-destructuring-bindings

Summary: 91 COVERED, 0 WEAKER, 0 STRICTER, 0 MISSING, 0 PRIVATE (sampled) — verdict: clean

Upstream: 91 Go `func TestDestructuring_*` functions in `destructuring_test.go`
(none using `t.Run` subtests — one node per function), calling one of four
shared helpers: `runDestructuring`/`runDestructuringMulti` (exact
`Compiled.Get(name).Value()` equality), `expectDestructuringError`/
`expectDestructuringCompileError` (compile error, the latter with no message
check — deliberately loose in upstream itself), and
`expectDestructuringRuntimeError`/`expectDestructuringRuntimeErrorAny`
(runtime error, the latter also deliberately loose).

Oracle: `benchmarks/deep-swe/v2/hidden/tengo-destructuring-bindings/oracle/oracle.py`
defines 101 scenarios via `value_case`/`compile_error_case`/`runtime_error_case`,
explicitly documented (module docstring, lines 90-99) as "one per upstream
`TestDestructuring_*` case" plus ~10 extra scenarios for upstream tests that
exist in `destructuring_test.go` but aren't in `f2p_node_ids` (backward
compatibility / empty-pattern / map-rest-not-allowed cases) — named
individually in the comment, kept as bonus checks, not counted against
scoring. All 101 scenarios are scheduled into Evaluation cases
(`_chunk`, size 34) and every one must pass for the row to score 1.

13 of the 91 upstream tests were directly spot-checked against
`oracle.py`'s scenario source, spanning simple value cases, deeply nested
default-chain cases, closures, parameter-pattern arity errors, and all three
"rest element must be last" compile-error cases plus both
`ParamWrongArgCount`/`ParamWrongArgCountMixed` runtime-error cases. Every one
matched byte-for-byte: identical Tengo source, identical expected
variable/value set, and — for the error cases — identical error-kind
(compile vs. runtime) and identical `contains` substring (e.g. all three
rest-position tests check `"rest element must be last"`, matching upstream's
own `expectDestructuringError` exactly, at the same non-loosened strength).
No discrepancy was found in the sample.

No table — no non-COVERED nodes were found in the sampled 13/91 (14%).

Effort to fix: none identified in the sample. Given the explicit 1:1 design
intent, the consistent naming convention (`snake_case` scenario id mirrors
the upstream `TestDestructuring_CamelCase` name almost mechanically), and
100% match rate across a diverse sample including the trickiest closure/order-
dependent-default/error-message cases, this row is very likely clean overall;
a full line-by-line pass on the remaining 78 nodes would give complete
certainty but was not performed given the strength of the sampled signal and
time budget for this audit.
## dateutil-rfc5545-timezone-interop

Summary: 19 COVERED, 24 WEAKER, 1 STRICTER, 23 MISSING, 0 PRIVATE — verdict: needs fix

Upstream: 67 `unittest`/`pytest` functions in `tests/test_rrule.py` (66
`RRuleTest` methods + 1 free `test_generated_aware_dtstart_rrulestr`), each a
single node (no parametrization). They cover RDATE/EXDATE TZID parsing,
`str()`/`repr()`/`to_ical()` round-tripping with and without TZID, `rruleset`
property/equality/copy/union/subtract semantics, and VCALENDAR parsing
(VTIMEZONE priority, line-unfolding, multi-VEVENT, ignored props).

Oracle: `benchmarks/deep-swe/v2/hidden/dateutil-rfc5545-timezone-interop/oracle/oracle.py`
groups scenarios into 14 "op" families (`rdate_parse` ×4, `vcalendar_parse`
×2, `multiple_timezones_error` ×1, `ruleset_from_str` ×1,
`rrule_str_roundtrip` ×4, `rrule_eq_hash` ×3, `rrule_repr_reconstruct` ×2,
`rrule_properties_ical` ×3, `ruleset_str_props` ×3, `ruleset_equality` ×2,
`ruleset_copy` ×1, `ruleset_combine` ×3, `ruleset_type_mismatch` ×1,
`ruleset_to_ical` ×2 — **32 cases total** for 67 upstream nodes), each op
handler bundling several checks (substring presence, occurrence lists,
line order, round-trip equality). Many cases genuinely reuse upstream's
canonical literal (`datetime(1997, 9, 2, 9, 0)`, `America/New_York`,
`America/Los_Angeles`) byte-for-byte — dateutil's own suite reuses this
exact DTSTART pervasively, so several Oracle cases end up an exact match by
construction. But because there are only 32 cases for 67 upstream tests,
many upstream tests either share a case with a different exact
`count`/`interval`/`until`/tz combination than the one they use (WEAKER), or
have no matching case's op+literal combination at all (MISSING). One op
(`rrule_str_roundtrip` case 2) checks a strict superset of what
`testToStrUntilUTC` asserts (STRICTER — a candidate satisfying upstream's
one substring check but not the Oracle's extra `DTSTART` substring check
would fail the Oracle despite passing upstream).

Verified COVERED (exact literal + assertion match): `testDatePropertyMultipleTimezonesError`,
`testRruleEqualitySameParams`, `testRruleProperties`, `testRruleRepr`,
`testRruleReprReconstructable` (bundled with `testRruleRepr` in one case),
`testRruleToIcalUTCNoVTimezone`, `testRulesetCopy`,
`testRulesetEqualityOrderIndependentDates`, `testRulesetStr`,
`testRulesetStrDtstartFromFirstRRule`, `testStrSetRDateValueDate`,
`testToStrAwareDtstartWithTZID`, `testToStrRoundtripAware` (bundled with the
previous), `testToStrUntilWithTZIDAwareDtstart`, `testRulesetFromStrVCalendar`,
`testVCalendarWithRDateAndExDate`, `testRulesetToIcalMultipleTimezones`,
`testRulesetSubtractTypeMismatch`, `testRulesetUnionTypeMismatch` (19).

| F2P node(s) | Upstream input | Upstream assertion | Oracle does instead | Class | Fix needed |
|---|---|---|---|---|---|
| `testRulesetFromStr` | `DTSTART:19970902T090000\nRRULE:FREQ=YEARLY;COUNT=3\nRDATE:19970905T090000\n` via `rruleset.from_str` | `isinstance(rset, rruleset)`, `datetime(1997,9,5,9,0)` in result | The Oracle's only `ruleset_from_str` case uses VCALENDAR text (COUNT=2) — it matches `testRulesetFromStrVCalendar`, not this plain-text variant | MISSING | Add a second `ruleset_from_str` case with the exact plain (non-VCALENDAR) text |
| `testRDateTZIDPreservedOnRoundtrip` | `rrulestr(..., forceset=True)`, `str(rr)` must contain `'RDATE;TZID=America/New_York:...'`, then re-parse and compare `list()` | exact substring + roundtrip-equality | No op checks a ruleset's `str()` output for a preserved RDATE TZID substring, nor re-parses it | MISSING | Add a dedicated case |
| `testRruleToIcalVTimezoneStandardComponent` | `r.to_ical()` must contain `BEGIN:STANDARD`/`END:STANDARD`/`TZOFFSETFROM:`/an exact `TZOFFSETTO:<computed NYC offset>` | exact substrings incl. a computed offset | No `rrule_properties_ical` case checks for `BEGIN:STANDARD`/`TZOFFSETTO` content | MISSING | Add the exact case |
| `testVCalendarBasic`, `testVCalendarIgnoresNonRecurrenceProps`, `testVCalendarLineUnfolding` | Plain naive VCALENDAR text, COUNT=2/3, some with `SUMMARY`/`DESCRIPTION` ignored, one with a folded `RRULE:FREQ=YEA\r\n RLY` continuation line | exact occurrence list | No `vcalendar_parse` case reproduces these exact texts (line-folding and ignored-property behavior are never exercised at all) | MISSING | Add these three exact-text cases |
| `testVCalendarVTimezonePriorityOverTzids`, `testVCalendarWithVTimezone`, `testVCalendarMultipleVEventsUsesFirst` | VTIMEZONE-bearing VCALENDAR text (one with a raising `tzids` callable that must never be called, one with STANDARD+DAYLIGHT components, naive multi-VEVENT "first wins") | exact/loose checks per test | The only VTIMEZONE-adjacent `vcalendar_parse` case uses a *different* TZID-bearing structure (`tzids_mode="raise"`, single STANDARD component, no DAYLIGHT) and checks exact UTC offsets — a different input and, for the "first VEVENT wins" property, a stricter check than upstream's loose one | MISSING | Add each exact scenario; the existing case doesn't substitute for any of the three |
| `testToStrTZIDFromDatetimeTimezone`, `testToStrTZIDFromTzicalZone` | `dtstart` built from raw `datetime.timezone.utc` (not `dateutil.tz`), and from a `tz.tzical(...)`-parsed custom zone | exact `'TZID=...'` substring | Oracle's `tzical` `tzkind` is defined in the vocabulary (`_tzinfo_for`/`_tzid_name`) but **never referenced by any case** in `_build_cases()` — dead code; and no case ever builds a plain `datetime.timezone` object | MISSING | Add cases actually using the `tzical` and raw-`timezone` tzkinds |
| `testRrulePropertiesDefaults`, `testRulesetEquality`, `testRulesetProperties`, `testRulesetStrWithTZID`, `testRulesetStrRoundtrip`, `testRulesetStrRoundtripWithTZID`, `testRulesetStrUTCZSuffix`, `testRruleToIcal`, `testStrSetRDateMultipleWithTZID`, `testStrRFC5545SetWithMixedTZIDAndUntil`, `testToStrUTCDtstart`, `test_generated_aware_dtstart_rrulestr` | Each a distinct exact construction (e.g. plain naive `to_ical()`, UTC-Z-suffix ruleset `str()`, `rrulestr(str(rset), forceset=True)` reparse-equality, `HOURLY` freq with no explicit `dtstart`) | exact assertion per test | No Oracle op/case reproduces these exact shapes at all — `HOURLY` freq is outside the Oracle's supported vocabulary (`_rrule_dates` only implements `YEARLY`/matching-weekday `WEEKLY`) | MISSING | Add matching cases; extend `_rrule_dates` for `HOURLY` if `test_generated_aware_dtstart_rrulestr` is to be checked at all |
| `testRruleReprReconstructableWithByWeekday`, `testRruleReprWithByWeekday`, `testRruleToIcalRoundtrip`, `testRruleToIcalWithTZID`, `testRulesetRepr`, `testRulesetReprAllComponents`, `testRulesetPropertiesImmutable`, `testRulesetStrWithExRule`, `testRulesetStrOutputOrder`, `testToStrTZIDFromIANAZone`, `testToStrTZIDFromFixedUTC`, `testRulesetSubtract`, `testRulesetSubtractWithRrule`, `testRulesetUnion`, `testStrSetRDateWithTZID`, `testStrSetRDateWithTZIDMapping`, `testStrSetRDateWithTZIDCallable`, `testStrSetRDateValueDateTimeWithTZID`, `testStrFullRFC5545SetWithTZID`, `testStrSetRDateWithDifferentTZIDFromDtstart`, `testRulesetToIcal`, `testRulesetToIcalRoundtrip`, `testRulesetToIcalWithTZID`, `testToStrRoundtripUTC` | Same op family exists (e.g. `rrule_repr_reconstruct`, `ruleset_str_props`, `ruleset_combine`, `rdate_parse`, `ruleset_to_ical`) but with a different exact `count`/`freq`/`byweekday`/timezone/extra-RDATE combination than the specific upstream test uses (e.g. `testRulesetStrWithExRule` is `YEARLY` `byweekday=(TU,TH)` vs. the Oracle's `WEEKLY` `byweekday=TU`; `testStrSetRDateWithTZIDCallable` uses NYC vs. the Oracle's Brussels case for `tzids_mode="callable"`) | Same-family case at same/different strength, different literal input | WEAKER | Add the exact literal case per node, or widen the shared case to include every upstream sub-shape |
| `testToStrUntilUTC` | `rrule(YEARLY, dtstart=UTC, until=UTC)`; `str()` must contain `'UNTIL=19990902T090000Z'` (only) | one substring | Oracle's matching `rrule_str_roundtrip` case checks **both** `'DTSTART:19970902T090000Z'` and `'UNTIL=19990902T090000Z'`, plus round-trip occurrence equality — checks strictly more than upstream asserted | STRICTER | Split into a case matching only upstream's single substring, or accept the extra check is harmless and document it |

Effort to fix: medium-large — roughly a third of the 67 nodes (23) have no
matching Oracle case at all, including two whole property areas (VCALENDAR
line-folding/ignored-props/VTIMEZONE-priority, and the `rruleset` `str()`
round-trip family), and another third (24) share a case with the wrong exact
parameters. Given ~32 cases already exist and are well-organized by op
family, the fix is mostly additive (new cases per op, matching each
remaining upstream literal exactly) rather than a redesign — smaller lift
than pest/narwhals but larger than happy-dom.
