# F2P coverage audit — group C

Read-only audit of Oracle F2P coverage against upstream `tests/test.patch` /
`tests/config.json` `f2p_node_ids`, per playbook #24 (every upstream F2P
assertion must be checked by the Oracle on its own input, at upstream's own
strength — playbook #20, no looser, no stricter). Bundling several upstream
assertions into one Oracle case is fine; dropping one, or subsuming it under
a check on a *different* input/config, is not, except for assertions on
private state that cannot be observed from outside (which must be recorded
as such).

Rows audited (all Go/DeepSWE): go-critic-doc-link-checker,
task-task-graph-export, prometheus-typed-label-sorting,
termenv-preserve-ansi-resets, helm-unified-manifest-stream.

---

## helm-unified-manifest-stream

Summary: 4 F2P subtest nodes (+1 aggregate parent, not scored independently):
COVERED=0, WEAKER=4, STRICTER=0, MISSING=0, PRIVATE=0 — verdict: **needs fix**

`tests/config.json`'s `f2p_node_ids` are the parent
`TestDeterministicRenderOrdering` plus 4 `cmdTestCase` subtests
(`deterministic_ordering_in_template`, `..._install_dry-run`,
`..._upgrade_dry-run`, `..._get_manifest`). Each subtest's upstream assertion
is a single **exact byte-for-byte golden-file match**
(`pkg/cmd/testdata/output/*.txt`), and all four golden files share identical
manifest content (same `deterministic-order` chart), so upstream re-asserts,
at full strength and on the exact same input, two structural properties for
*every one* of the 4 commands: (a) in-file/same-source multi-document order
is preserved (`01-resources.yaml`: `sa-a` then `cm-a`), and (b) same-`Source`
hook-before-non-hook precedence (`02-mixed.yaml`: `hook-b` before `cm-b`).

The Oracle (`benchmarks/deep-swe/v2/hidden/helm-unified-manifest-stream/oracle/oracle.py`)
uses its own host-authored fixtures (legitimate — fixtures are never shipped
upstream) but tests property (a) only once, via `template_order` (kind=
`template`), and property (b) only once, via `get_manifest_precedence`
(kind=`get_manifest`). Neither property is re-verified for `install_dry_run`
or `upgrade_dry_run` (`HOOK_CHART_FILES` has no multi-doc file and no
same-file hook+non-hook mixing), nor is property (b) verified for plain
`template`. A candidate that fixes the shared ordering/precedence logic for
only some of the 4 command paths would still pass. The dossier
(`docs/benchmark-conversions/DeepSWE/helm-unified-manifest-stream.md`,
~L187-192) confirms this is a deliberate design choice, not an oversight.

| F2P node | Upstream input / assertion | Oracle instead | Fix needed |
|---|---|---|---|
| `deterministic_ordering_in_template` | `deterministic-order` chart via `template`; golden requires full-path order + in-file multi-doc order + same-source hook-before-nonhook (`02-mixed.yaml`) | `template_order` (no hooks) + `template_hooks` (hooks in a separate file, no mixing) — same-source hook precedence never exercised for `template` | Add a `template`-kind fixture with a same-file hook+non-hook mix |
| `deterministic_ordering_in_install_dry-run` | same chart via `install --dry-run`; same 3 properties + single `MANIFEST:` | `install_dry_run_hooks` — full-path order + single_manifest only, no multi-doc file, no same-file mix | Extend fixture with a multi-doc file and a mixed hook/non-hook file |
| `deterministic_ordering_in_upgrade_dry-run` | same as install, via `upgrade --dry-run` | `upgrade_dry_run_no_happy` — same gaps as install | Same fix as install |
| `deterministic_ordering_in_get_manifest` | hand-built release with `01-resources.yaml` holding 2 entries (`sa-a`,`cm-a`) in file order, plus hooks | `get_manifest_precedence` — full-path order + hook precedence (02-mixed) correct, but no other source has 2 entries, so same-source multi-entry stability for non-hook entries is untested | Add a second `manifest_entries` pair sharing one `source` |

Files read: `/tmp/securebench-paper-deepswe-source/tasks/helm-unified-manifest-stream/tests/{config.json,test.patch}`;
`benchmarks/deep-swe/v2/hidden/helm-unified-manifest-stream/oracle/oracle.py`;
`benchmarks/deep-swe/v2/evaluation_inputs/helm-unified-manifest-stream/adapter/{adapter.py,driver_test.go}`;
`docs/benchmark-conversions/DeepSWE/helm-unified-manifest-stream.md`.

Effort to fix: **small**. No new check logic needed —
`_check_markers_in_order` already enforces arbitrary sequential marker order
both within and across `# Source:` blocks. Purely additive: extend/add 3-4
fixtures across the `template`/`install_dry_run`/`upgrade_dry_run`/
`get_manifest` scenarios and wire into the existing `CASES` groups (scenario
count headroom exists: adapter allows up to 6/challenge, current cases use
2-3).

---

## go-critic-doc-link-checker

Summary: 3 F2P nodes: COVERED=1, WEAKER=0, STRICTER=0, MISSING=1, PRIVATE=1
(vacuous, see below) — verdict: **needs fix** (narrow)

Upstream adds one new checker, `brokenDocLink`, with 3 F2P node ids:
`TestCheckers/brokenDocLink` (main content test), `.../debug`, `.../sanity`
— go-critic's own generic per-checker test harness
(`checkers/internal/linttest/linttest.go`).

1. **`TestCheckers/brokenDocLink`** — COVERED. This is the real content
   assertion: scans `testdata/brokenDocLink/{positive,negative}_tests.go`
   and requires an exact match between the checker's diagnostics and the
   `/*! ... */` annotations (19 distinct broken-link diagnostics in
   `positive_tests.go`, 0 in `negative_tests.go`, i.e. ~24 non-triggering
   cases bundled in one file-level assertion). The Oracle's
   `benchmarks/deep-swe/v2/hidden/go-critic-doc-link-checker/oracle/cases.json`
   embeds the exact upstream source text and all 20 `(line, message)` pairs
   (verified directly: `cases.json`'s `brokenDocLink/positive_tests.go`
   entry has `len(expected) == 20`; `original_sha256`-pinned); `oracle.py`
   applies an identity-preserving
   per-run rename + line-shift mutation (documented, reversible, preserves
   the exact set of (file, line, message) assertions) and compares
   `sorted(actual) == sorted(expected)` exactly, matching upstream's
   exact-match/unmatched-diagnostics semantics at the same strength.
2. **`TestCheckers/brokenDocLink/debug`** — vacuous upstream: no
   `testdata/brokenDocLink/debug.go` file was added by `test.patch`, so this
   subtest (which loads `testdata/<checker>/debug.go` if present) has no
   real content to assert; it passes identically for any checker
   implementation as soon as the checker is registered. Recorded as a
   legitimate no-op, nothing to cover.
3. **`TestCheckers/brokenDocLink/sanity`** — **MISSING**. Upstream's
   `saneCheckersList` (`checkers/internal/linttest/linttest.go` L22-58) runs
   *every* checker, including the new `brokenDocLink`, over a shared,
   generic 213-line corpus of unusual Go constructs
   (`checkers/internal/linttest/testdata/sanity/tests.go`: dot imports,
   `unsafe`, empty `const()`/`var()`/`type()` blocks, `for range` edge
   cases, etc.) and requires it not panic. The Oracle's driver
   (`benchmarks/deep-swe/v2/evaluation_inputs/go-critic-doc-link-checker/adapter/driver.go`)
   only ever feeds the checker `positive_tests.go`/`negative_tests.go`
   content — never this distinct generic corpus. A candidate whose
   `brokenDocLink` implementation panics on constructs absent from its own
   testdata (but present in the shared sanity corpus) would not be caught.
   The dossier (L108-109) calls this "not independently observable" and
   groups it with the genuinely-vacuous `/debug` node, but a checker panic
   vs. no-panic *is* externally observable (process crash / non-`observed`
   status) — it is not private state, so this does not qualify for the
   playbook's private-state exception.

Effort to fix: **small**. Add one more Oracle case that runs `brokenDocLink`
over the (non-secret, generic go-critic framework) sanity corpus content via
the existing driver, and a *new* evaluation mode that only requires
`status=="observed"` (no crash) without comparing diagnostics — reusing the
current diagnostics-equality check with `expected=[]` would be **stricter**
than upstream (which discards diagnostics entirely in `saneCheckersList`),
so this needs a small, distinct code path, not just a fixture addition.

Files read: `/tmp/securebench-paper-deepswe-source/tasks/go-critic-doc-link-checker/tests/{config.json,test.patch}`;
`/tmp/securebench-paper-go-critic-baseline/checkers/checkers_test.go` and
`checkers/internal/linttest/linttest.go` (to determine what `/debug` and
`/sanity` actually assert upstream);
`checkers/internal/linttest/testdata/sanity/tests.go`;
`benchmarks/deep-swe/v2/hidden/go-critic-doc-link-checker/oracle/{oracle.py,cases.json}`;
`benchmarks/deep-swe/v2/evaluation_inputs/go-critic-doc-link-checker/adapter/{adapter.py,driver.go}`;
`docs/benchmark-conversions/DeepSWE/go-critic-doc-link-checker.md`.

---

## prometheus-typed-label-sorting

Summary: 17 F2P nodes: COVERED=15, WEAKER=2, STRICTER=0, MISSING=0, PRIVATE=0
— verdict: **needs fix** (narrow, 1 real gap + 1 low-risk documented
substitution)

Every F2P node is a standalone Go test function with exactly one
`require.Equal(t, []string{...}, multiTypeLabelOrder(out, label))` — an exact
expected-order assertion over a fixed input vector. The Oracle
(`benchmarks/deep-swe/v2/hidden/prometheus-typed-label-sorting/oracle/oracle.py`)
does not replay upstream's literal per-test vectors; instead it owns an
independent Python re-derivation of the typed-sort comparator and unions
upstream's per-axis input values into larger shuffled pools (`_GLOBAL`,
`_DURATION`, `_BYTES`, `_SEMVER`, `_IP_CIDR`, `_TIMESTAMP`, `_HUGE_NUMERIC`,
`_MALFORMED`, `_EQUAL_TIE`, `_EMPTY_ONLY`), bundled into 5 cases, computing
the correct order for the merged pool and comparing it exactly against the
candidate's actual output. Because a valid total order is transitive, a
merged-pool check at least as strong as testing the original smaller vectors
separately, **provided every original test's value set is a subset of the
pool it's merged into**. Checked all 17 F2P node value sets against the
pools; 15 are clean supersets. Two exceptions:

| F2P node | Upstream input | Oracle instead | Class | Fix needed |
|---|---|---|---|---|
| `TestSortByLabelMultiTypeHugeNumericMagnitude` | `{"+Inf","1e+24","999999999999999999999999","1000000000000000000000001","1e+23"}` — asserts `+Inf` (pos_inf class) still ranks above huge-magnitude finite numbers | `_HUGE_NUMERIC` pool = `["1e+24","999999999999999999999999","1000000000000000000000001","1e+23"]` only, merged into the "magnitude_and_class_ordering" axis which never includes `+Inf`/`-Inf`/`NaN` (those only appear in the separate `_GLOBAL`-based axis, never combined with `_HUGE_NUMERIC`) | WEAKER | Add `+Inf` (or an equivalent pos_inf value) into the `magnitude_and_class_ordering` pool, or a value shared between `_GLOBAL` and `_HUGE_NUMERIC` |
| `TestSortByLabelMultiTypeMalformedFallbackNatural` | `{"1e+","1.2.3.4","v1.02.3","2","1"}` — finite values `1`,`2` sort before malformed-fallback strings | `_MALFORMED` pool substitutes `"3"`,`"4"` for `"1"`,`"2"` (documented in-code, L580-591: avoids a real upstream comparator non-antisymmetry bug when `"1"` would collide with `"01"` from `_EQUAL_TIE` once pools merge) | WEAKER (documented, low-risk) | Semantically equivalent substitution already explained in comments; no action required beyond noting it explicitly as a recorded exception in the dossier, since it is not literally the exact upstream input |

Files read: `/tmp/securebench-paper-deepswe-source/tasks/prometheus-typed-label-sorting/tests/{config.json,test.patch}`;
`benchmarks/deep-swe/v2/hidden/prometheus-typed-label-sorting/oracle/oracle.py`;
`benchmarks/deep-swe/v2/evaluation_inputs/prometheus-typed-label-sorting/adapter/{adapter.py,driver.go}`.

Effort to fix: **small**. Add one value to one pool
(`_HUGE_NUMERIC` ∪ pos_inf) for the genuine gap; the documented substitution
needs at most a one-line note in the dossier, not a code change.

---

## termenv-preserve-ansi-resets

Summary: 35 F2P nodes (19 `_mars` package + 16 `ansi_new` package):
COVERED=24 (19 `_mars` + 5 `ansi_new`), WEAKER=0, STRICTER=5, MISSING=6,
PRIVATE=0 — verdict: **needs fix**

The task adds two parallel test suites: `_mars` (19 tests, exercising the
higher-level `termenv` package wrapper: `Style`/`Output`/template helpers)
and `ansi_new` (16 tests, exercising the low-level `ansi` package directly:
`Tokenize`/`TruncateANSI`/`StripANSI`/`ANSIWidth`/`HasANSI`). The Oracle
(`benchmarks/deep-swe/v2/hidden/termenv-preserve-ansi-resets/oracle/oracle.py`)
transliterates each upstream test near-1:1 into a scenario, keyed by an
explicit `scope` field (`"termenv"` routes through the `_mars`-equivalent
wrapper, `"ansi"` calls the low-level package directly — confirmed in
`adapter/driver.go` L25/102-129). All 19 `_mars`-package tests map cleanly
(spot-checked `TestMarsAscii_TruncateDoesNotEmitANSI`'s two sub-assertions
against `sc_style_truncate_ascii_noop` + `sc_output_truncate_ascii_no_ansi`,
and the `PreserveResets_ReappliesAfterReset` test's 3 sub-cases against
`sc_style_styled_reapply_{full_reset,short_reset,nonreset}`). The `ansi_new`
package has real gaps: 6 of its 16 F2P tests exercise `ansi.TruncateANSI`
combined with a second operation (`StripANSI`, `HasANSI`) on the *truncated*
output, or a distinct scope="ansi" input (missing-close hyperlink, tail
budget across multiple assertions) that no scenario in `oracle.py`'s
33-scenario list reproduces. A further 5 `ansi_new` scenarios are
**STRICTER**: verified directly against `oracle.py`'s `check == "tokens"`
handling (L625-628, compares the full `{"type","raw","text"}` dict list via
`actual != expected`) and two `check == "text"` scenarios that pin an exact
output string. In each case upstream's own assertion (in `test.patch`) is
looser — either a per-index `Type` check only, or a `strings.Contains`
substring/width check, never a full raw-token or exact-string match:

| F2P node | Upstream input / assertion | Oracle instead | Class | Fix needed |
|---|---|---|---|---|
| `TestTruncate_HyperlinkCloseInsertedWhenMissingClose` | `open+"Click here for more"`, width=5, no close tag in input; want `open+"Click"+close` (close auto-inserted) | no scenario | MISSING | Add a scope=ansi truncate scenario with an open-but-unclosed hyperlink |
| `TestTruncate_TailFitsWithinWidthBudget_AndIsStyled` | `"\x1b[31mHello World\x1b[0m"`, width=8, tail="."; checks no-split + `ANSIWidth==8` + prefix SGR preserved + suffix reset | no scenario | MISSING | Add scope=ansi scenario combining width-budget + style-prefix + reset-suffix checks |
| `TestTruncate_TailInheritsActiveStyle` (ansi_new/scope=ansi variant) | `sgrOpen+"Hello World"+reset`, width=6, tail="."; checks suffix reset + tail inherits style | Only the `_mars`/scope=termenv sibling (`TestMarsTruncateANSI_TailInheritsActiveStyle`) is covered via `sc_truncate_tail_inherits_style` (scope="termenv") | MISSING | Add a second, scope="ansi" scenario exercising the low-level `ansi.TruncateANSI` path directly |
| `TestTruncate_StripANSI_RemovesOSCAndCSI_FromTruncatedOutput` | truncate a CSI+OSC+wide-unicode string to width 4, then `StripANSI` the *truncated* output, require exact `"日."` and no `\x1b` left | `sc_strip_ansi_removes_csi_osc` strips raw (non-truncated) input directly | MISSING | Add a scenario chaining truncate→strip on the truncated output |
| `TestTruncate_HasANSI_DetectsOSC_InTruncatedOutput` | truncate an OSC-hyperlink string to width 2, require exact output, then `HasANSI` on the *truncated* output must be true | `sc_has_ansi_{true,false}` call `HasANSI` on raw, non-truncated input | MISSING | Add a scenario chaining truncate→has_ansi on the truncated output |
| `TestTruncate_DoesNotSplitOSCSequence_WhenWidthZero` | input is OSC-open only (no CSI at all) + `"Z"`, width=0; exact want = `open+close` | Only `sc_truncate_zero_width_when_width_zero_ansi`, which always includes a CSI (`long_csi + open_ + char`) — no CSI-less OSC-only scenario | MISSING | Add a width=0 scenario with an OSC token and no CSI |
| `TestTruncate_DoesNotSplitCSIOrOSC_WhenWidthZero` | `longCSI+open+"Z"`, width=0; upstream only checks (via substrings) that the CSI/OSC tokens are preserved whole and `"Z"` is gone — does **not** pin the full output string | `sc_truncate_zero_width_when_width_zero_ansi` requires an **exact** string match (`long_csi+open_+close+RESET_SEQ`), which is stricter than upstream's loose substring checks and could reject a correct candidate that (e.g.) doesn't append a trailing reset in this exact corner case | STRICTER | Relax to a substring/no-split check matching upstream's actual assertion strength (or split into a separate `check:"no_split"` scenario like `sc_truncate_does_not_split_no_visible_char` already does elsewhere) |
| `TestTokenize_ClassifiesTokenKinds` | 5-token SGR+hyperlink+text+reset+hyperlink-close sequence; upstream (`test.patch` L394-419) checks only `tokens[i].Type` for each of the 5 indices, plus `tokens[2].Text=="hello"` — never inspects any token's `Raw` field, nor `Text` on the other 4 tokens | `sc_tokenize_classify_kinds` uses `check:"tokens"`, comparing the **full** `{"type","raw","text"}` dict for all 5 tokens exactly (`oracle.py` L625-628, `token_dicts()` at L129-130) | STRICTER | Change the check to compare only `type` per index plus `text` on the one text-token index, matching upstream's actual per-field assertion |
| `TestTokenize_CompoundResetClassifiedAsReset` | `"\x1b[1;0;31m"` → upstream (`test.patch` L425-434) checks only `len(tokens)==1` and `tokens[0].Type==TokenReset` — never checks `Raw` or `Text` | `sc_tokenize_compound_reset` uses the same `check:"tokens"` full-dict exact match as above | STRICTER | Same fix: compare `type` (and count) only for this scenario |
| `TestTruncate_ZeroWidthUnicodeAndControlSequences_DoNotCount` | `CSI+code+"m"+a+RESET_SEQ+b+ZWSP+c`, width=3; upstream (`test.patch` L634-643) checks only `ANSIWidth(out)==3` and `strings.Contains(out, CSI+code+"m")` — does not pin the exact reconstructed output string | `sc_truncate_zero_width_unicode_and_control_dont_count_ansi` uses `check:"text"` with `expected == text` (the literal, unmodified input) — an exact-string requirement upstream never made | STRICTER | Change the check to verify `ANSIWidth(out)==3` and the SGR substring is present, not full-string equality |
| `TestTruncate_OSC8InsideSGRStyling` | `CSI+"1m"+open+word+close+RESET_SEQ`, width=2; upstream (`test.patch` L617-626) checks only two `strings.Contains`: hyperlink-close present, bold SGR preserved — no exact string, no requirement of a trailing reset | `sc_truncate_osc8_inside_sgr_ansi` uses `check:"text"` with an **exact** expected string that additionally appends a trailing `RESET_SEQ` upstream never requires | STRICTER | Change the check to the same two substring checks upstream performs |

Files read: `/tmp/securebench-paper-deepswe-source/tasks/termenv-preserve-ansi-resets/tests/{config.json,test.patch}`;
`benchmarks/deep-swe/v2/hidden/termenv-preserve-ansi-resets/oracle/oracle.py`
(all 688 lines); `benchmarks/deep-swe/v2/evaluation_inputs/termenv-preserve-ansi-resets/adapter/{adapter.py,driver.go}`.

Effort to fix: **medium**. The 4 "chain truncate with a second op" gaps and
the missing-close/tail-budget gaps each need a new scenario plus (for the
truncate→strip and truncate→has_ansi cases) either a new `op` value the
driver doesn't currently expose in one round trip, or two sequential
challenge scenarios feeding the truncated output of one into the input of a
follow-up `strip_ansi`/`has_ansi` scenario — check whether `driver.go`'s
existing ops can already be composed this way before deciding. The 5
STRICTER items are each a small, local loosening of one scenario's `check`
type or `expected` value (2 tokenize scenarios: compare `type` per index
instead of the full token dict; 3 truncate scenarios: substring/width checks
instead of exact-string equality) — mechanically simple, but there are 5 of
them, not 1.

---

## task-task-graph-export

Summary: 20 F2P nodes: COVERED=17, WEAKER=1, STRICTER=1, MISSING=1,
PRIVATE=0 — verdict: **needs fix** (narrow)

Every F2P node is a standalone Go test function; `test.patch` adds a JSON
graph-export contract (`roots`/`nodes`/`edges`/`depth_groups`/`longest_path`)
plus DOT/text renderers. The Oracle
(`benchmarks/deep-swe/v2/hidden/task-task-graph-export/oracle/oracle.py`,
832 lines) uses host-authored Taskfile fixtures (never shipped upstream,
consistent with the architecture) with a 1:1 scenario per upstream test
(19 scenarios covering 20 nodes — `wildcard` maps to 2 scenarios matching
its 2 sub-assertions), bundled into 3 cases. Verified field-by-field against
each test's assertions (roots, deps, edge from/to/type, edge vars,
depth_groups exact-or-loose per upstream's own looseness, longest_path
exact-or-loose, node shape incl. `up_to_date` presence/absence gated on
`no_status`, which correctly subsumes `TestGraphNoStatus` and
`TestGraphUpToDatePresence` generically across all scenarios). Three issues:

| F2P node | Upstream input / assertion | Oracle instead | Class | Fix needed |
|---|---|---|---|---|
| `TestGraphDefaultFormat` | Constructs the `Executor` **without ever calling** `task.WithGraphFormat(...)` at all, to test the format's true zero-value/default when the option is never applied; only checks `roots==["root"]` | Adapter's driver.go (L54) **always** calls `task.WithGraphFormat(req.Format)` explicitly, including for the `simple_chain` scenario's `fmt=""`; explicit empty-string vs. option-never-applied can be different code paths in the candidate's own option-handling logic | MISSING | Give the driver a way to skip the `WithGraphFormat` call entirely for one scenario (distinct from passing `""`) |
| `TestGraphAliases` | Two sub-assertions in one function: (1) task `"deploy"` normally resolves, deps=["build"], 2 nodes; (2) alias `"b"` resolves to `"build"` alone, 1 node | Oracle's `aliases` scenario only exercises tasks=`["b"]` (sub-assertion 2); sub-assertion 1 (`"deploy"` resolving normally under `ALIASES_YAML`) is never checked | WEAKER | Add a second `aliases`-fixture scenario with tasks=`["deploy"]` |
| `TestGraphWildcard` (wildcard-as-root half) | `rootResult := runGraphJSON(..., ["build-darwin"], ...)`; upstream only checks `len(Roots)==1` and `len(Nodes)==1` — deliberately does **not** pin the resolved root/node name | Oracle's `wildcard_root` scenario asserts an **exact** `roots=["build-*"]` and node name `"build-*"`, rejecting a correct implementation that reports the resolved concrete name (e.g. `"build-darwin"`) instead of the wildcard pattern, which upstream never required | STRICTER | Relax `wildcard_root` to a count-only check (1 root, 1 node), matching upstream's own looseness |

Files read: `/tmp/securebench-paper-deepswe-source/tasks/task-task-graph-export/tests/{config.json,test.patch}`;
`benchmarks/deep-swe/v2/hidden/task-task-graph-export/oracle/oracle.py` (all
832 lines); `benchmarks/deep-swe/v2/evaluation_inputs/task-task-graph-export/adapter/driver.go`.

Effort to fix: **small**. All three are narrow, local edits: one new
alias-scenario, one relaxed assertion, and one driver code path (or a
documented, disclosed exception if the option-omission distinction is judged
not to matter for this implementation).
