# DeepSWE qualification record

Admission record for DeepSWE v2 rows. Companion to the
[TerminalBench record](terminal-bench-qualification-record.md); procedure in the
[DeepSWE conversion playbook](deepswe-conversion-playbook.md).

Source: `github.com/datacurve-ai/deep-swe` at `e016041a6ccf8da29906afc9a3f5a8df940a1f78`.
Host: Linux 7.0.0-29-generic x86_64, Docker 29.7.2, 12 CPUs, 30 GB RAM.

## How a DeepSWE row is qualified

Every DeepSWE task ships an upstream gold solution. That makes gate 2 decisive:
each row is accepted only if, through the production capture path under real
Docker, **the unmodified base commit fails and the gold solution passes**,
across at least two fresh Evaluations with distinct Evaluation IDs, and
targeted mutants fail. The gold patch is installed as host-only qualification
material by [`tools/deepswe_reference.py`](../../tools/deepswe_reference.py) and
is never a row resource.

Each staged row is then re-verified independently before integration — the
focused test is re-run, the adapter is checked for leaked expectations with
[`tools/deepswe_review.py`](../../tools/deepswe_review.py), and
[`tools/deepswe_integrate.py`](../../tools/deepswe_integrate.py) re-checks
preflight and visibility before the row enters `tasks-v2.jsonl`.

## First wave: defects found by replaying the gold solution

The four rows implemented before this record existed had never been run against
their gold solution. Doing so showed that **all three of the non-`go-critic`
rows rejected the correct upstream implementation**, for five distinct reasons:

| Row | Defect | Class |
|---|---|---|
| `fd-deterministic-multi-key-sorting` | built into `/tmp`, which Evaluation mounts `noexec`; cargo could not run build scripts | adapter environment |
| `fd-deterministic-multi-key-sorting` | passed a positional path together with `--strip-cwd-prefix`, which `fd` rejects; upstream's `TestEnv` passes no path | adapter invocation |
| `updo-policy-alerting` | `GOTMPDIR=/tmp`; `go run` could not execute the binary it linked | adapter environment |
| `cattrs-partial-structuring-recovery` | passed `forbid_extra_keys` to `BaseConverter`, which does not accept it at the base commit | adapter API |
| `cattrs-partial-structuring-recovery` | postponed annotations on locally defined classes became unresolvable strings | adapter types |
| `cattrs-partial-structuring-recovery` | Oracle required new partial errors to be picklable — in neither the instruction nor any upstream test | **invented requirement** |
| `cattrs-partial-structuring-recovery` | Oracle required a populated `error_map` with detailed validation off; upstream only asserts it is a dict | **invented requirement** |

The two invented requirements matter most: they made the benchmark stricter
than the task, so a correct submission would have scored zero. Both were
removed, and the corrected rules are pinned by tests that also confirm
`error_map` is still enforced where upstream enforces it.

| Row | Base | Gold | Partial mutant | Result |
|---|---|---|---|---|
| `go-critic-doc-link-checker` | fails | passes | fails (+ 7 semantic, forgery) | **Approved** — 168 passed |
| `cattrs-partial-structuring-recovery` | fails | passes | fails | **Approved** |
| `fd-deterministic-multi-key-sorting` | fails | passes | fails | **Approved** |
| `updo-policy-alerting` | fails | passes | fails | **Approved** |

## Conversions

Rows converted from design-only are recorded here as they are integrated.

| Row | Lang | Cases | Base | Gold | Targeted mutants | Re-verified | Verdict |
|---|---|---:|---|---|---|---|---|
| `bandit-structured-nosec-directives` | Python | 34 | fails | passes | 4 real-code + generic | 16 passed | semantic change, low |
| `dateutil-rfc5545-timezone-interop` | Python | 32 | fails | passes | generic real-code; 5 Oracle-level | 14 passed | semantic change, low |
| `ink-grid-box-layout` | TypeScript | 25 | fails | passes | 5 real-code + generic | 24 passed | clean, none |
| `narwhals-rolling-window-suite` | Python | 24 | fails | passes | 3 real-code + generic | 13 passed | clean, none |
| `task-task-graph-export` | Go | 19 scenarios / 3 cases | fails | passes | 3 real-code + generic | 16 passed | clean, none |
| `prometheus-typed-label-sorting` | Go | 26 | fails | passes | 4 real-code + generic | 17 passed | clean, none |
| `termenv-preserve-ansi-resets` | Go | 34 | fails | passes | 5 real-code + generic | 17 passed | clean, none |
| `pest-character-class-coalescing` | Rust | 38 scenarios / 2 cases | fails | passes | 3 real-code + generic | 17 passed | clean, none |
| `etree-xml-diff-patch` | Go | 63 scenarios / 3 cases | fails | passes | 4 real-code + generic | 17 passed | clean, none |
| `meriyah-explicit-resource-declarations` | TypeScript | 33 | fails | passes | 4 real-code + generic | 24 passed | clean, none |
| `happy-dom-deterministic-intersectionobserver` | TypeScript | 26 | fails | passes | 6 real-code + generic | 26 passed | clean, none |
| `tengo-destructuring-bindings` | Go | 101 scenarios / 3 cases | fails | passes | 3 real-code + generic | 16 passed | semantic change, low |
| `returns-validated-error-accumulation` | Python | 57 | fails | passes | 3 real-code + generic | 15 passed (14 + review test) | semantic change, low |
| `mashumaro-flattened-dataclass-fields` | Python | 43 units / 9 cases | fails | passes | 3 real-code + generic | 13 passed | semantic change, low |
| `ts-pattern-match-each` | TypeScript | 47 (38 runtime + 9 type) | fails | passes | 5 real-code (2 type-only) + generic | 23 passed (gates 1, 2, 4) | semantic change, low |
| `python-statemachine-state-data-scoping` | Python | 33 | fails | passes | 3 real-code + generic | 14 passed | semantic change, low |
| `true-myth-iterable-collection-combinators` | TypeScript | 49 | fails | passes | 4 real-code + generic | 21 passed (gates 1, 2, 4) | semantic change, low |
| `helm-unified-manifest-stream` | Go | 2 replays | fails | passes | 3 real-code + generic | 11 passed (gates 1, 2, 4) | clean, none |
| `skrub-duration-encoding` | Python | 44 | fails | passes | 3 real-code + generic | 9 passed (gates 1, 2, 4) | semantic change, low |
| `sqlfmt-create-table-ddl-formatting` | Python | 50 | fails | passes | 3 real-code + generic | 10 passed (gates 1, 2, 4) | semantic change, low |
| `anko-default-function-arguments` | Go | 18 scenarios / 3 cases | fails | passes | 3 real-code + generic | 19 passed | semantic change, low |
| `csstree-shorthand-expansion-compression` | JavaScript | 79 items / 18 cases | fails | passes | 3 real-code + generic | 23 passed | semantic change, low |
| `tengo-callable-instance-isolation` | Go | 23 scenarios / 6 cases | fails | passes | 3 real-code + generic | 16 passed | semantic change, low |
| `tomlkit-toml-table-converters` | Python | 51 | fails | passes | 3 real-code + generic | 10 passed (gates 1, 2, 4) | semantic change, low |
| `obsidian-linter-scoped-ignore-markers` | TypeScript | 49 items / 4 cases | fails | passes | 3 real-code + generic | 23 passed | semantic change, low |
| `helm-array-merge-strategies` | Go | scenario batches, 2 replays | fails | passes | 3 real-code + generic | 21 (gates 1, 2, all mutants re-run under Docker) | clean, none |

Review notes:

- **`bandit`** recorded its expected outputs by running the gold solution. That
  is only safe when the compared fields are narrow, so it was checked: the
  adapter reports only finding `(test_id, line)` and the `nosec` /
  `skipped_tests` counts, which are exactly what the instruction specifies and
  upstream tests 068–072 assert. Its agent also found that its first
  statement-span case passed under the very bug it targeted, and redesigned it
  (playbook defect #8). Upstream `test_078` is syntactically invalid Python and
  passes vacuously upstream; the instruction's two valid variants are tested
  instead.
- **`dateutil`**'s targeted mutants are Oracle-level; only the generic mutant
  runs as real code under Docker. It computes UTC offsets with the host's
  `zoneinfo`. Every date falls in 1997–2000, where major zones' offsets are
  settled in tzdata, so host/image tzdata drift is not a practical risk here.
  The `tzical` custom-zone name path is plumbed but not exercised by any
  generated case — a disclosed coverage gap on one fallback branch.

From `task-task-graph-export` onward, conversions are required to use at least
three **real-code** mutants run under Docker, not Oracle-level ones.

- **`ink-grid`** is the first TypeScript conversion and set the pattern: run TS
  with `node --import=tsx` from a driver copied into `/app`, because ESM bare
  imports resolve from the importing file's path (playbook defect #10). Its
  first `fr` cases used evenly divisible widths, so a `floor`→`ceil` mutant
  passed; the widths were changed so the near-miss diverges (defect #11). The
  Oracle carries an independent Python implementation of the grid algorithm.
- **`narwhals`** mirrors upstream's `assert_equal_data` exactly —
  `math.isclose(rel_tol=0, abs_tol=1e-6)` with the same NaN/None equivalence —
  checked against the helper in the pinned image. Backends absent from the image
  (dask, modin, cudf, ibis, pyspark) are skipped exactly as upstream's
  `importorskip` does; `sqlframe` is installed but consolidated into the duckdb
  and polars paths it shares.
- **`task-graph`** checks three tie-ambiguous fields only as far as upstream
  asserts them: the diamond's longest-path middle element, the three-way
  `for_deps` tie (not asserted upstream), and `reverse` beyond index 0.
- **`prometheus`** replaces upstream's `util/teststorage` with a small hand-rolled
  `Queryable`. That is harness plumbing, not the code under test, and it stops
  the build being OOM-killed inside the 1 GB Evaluation limit. Upstream's
  `natsort` fallback is not a total order (`"1"` vs `"01"`, and `""` ties with
  everything), so the empty-label case keeps upstream's own small ascending-only
  shape. `require.Nil(t, anns)` is enforced as a zero annotation count.
- **`termenv`** stalled after its agent had verified every gate; the final run
  and dossier section were completed during review.
- **`pest`** is the first Rust conversion. The driver pins `serde_json` to the
  exact version already in the image's warm cargo registry and copies both
  caches into `/app`, so each fresh Evaluation builds offline in 7–22 s.
  Challenge grammars are restricted to shapes the other optimizer passes leave
  unchanged, so the coalescer is the only transformation observed; this
  matches upstream's own `charclass_tests.rs` shapes. P2P regressions in other
  crates are not replayed.
- **`etree`** batches one case's steps into a single driver run. It classifies
  returned `OpType`/`ConflictType` values against the candidate's exported
  constants rather than its `String()` output, so a broken `String()` cannot
  mask a broken `Diff`. Four document-method tests are folded into flags on
  their function-form scenarios. The review tool flags four XPath literals
  shared with the Oracle; they are fixed driver inputs for `String()`
  formatting, not expected outputs.
- **`meriyah`** runs TypeScript through `vite-node`, the image's only TS
  runner, which it also needs because `const enum` defeats Node's type
  stripping. Its agent found that a callable in Oracle `case_context` kills the
  Oracle process with no traceback (playbook defect #16). Near-duplicate
  contexts are consolidated to representatives; every consolidation is listed
  in the dossier.
- **`happy-dom`** has no TS runner at all, so its driver runs as a vitest test
  file inside the project (playbook defect #17). No scored property depends on
  wall-clock timing: the adapter waits for actual delivery progress, and a
  short settle window is used only as upstream's own
  `NO_EXTRA_DELIVERY_WAIT_MS` uses it. Three dossier notes are deliberately
  not scored: EventTarget P2P regressions, duplicate `observe()` semantics
  (unspecified upstream), and non-empty `takeRecords()` draining (would need a
  timing race). Re-verified gates 1, 2 and 4 independently (19 passed).
- **`tengo`** scores destructuring only through compiled-and-run output. The
  upstream parser tests on internal AST shapes and the new opcode are dropped
  as private representation (impact low/none, per the dossier). Ten upstream
  destructuring tests absent from `f2p_node_ids` are kept, since they assert
  instruction behaviour. The solution adds no new file, so the generic mutant
  drops the largest non-test hunk (`compiler.go`) instead.
- **`returns`** as delivered accepted any 14 or more passing laws, looser than
  upstream, whose F2P set names 16 generated law tests. Review tightened it:
  the adapter now reports the generated law names, and the Oracle requires all
  16 upstream names to be generated and pass. Extra laws are allowed but must
  also pass. A forged 15-law observation is now rejected (new test). Base and
  gold were re-run under Docker after the change. Accumulation order is
  checked exactly wherever upstream pins it, and by membership and count
  elsewhere, as upstream does.
- **`mashumaro`** computes expectations with an independent reimplementation
  of pack/unpack in the Oracle, cross-checked against the gold solution on 37
  sub-cases. Validation failures are checked only as "raised at class
  construction", because upstream asserts only `pytest.raises(Exception)`.
  The adapter builds classes from generated `class` source, not
  `make_dataclass`, because CPython 3.14's lazy annotations would silently
  yield zero fields (invisible on the image's 3.12).
- **`ts-pattern`** checks type-level behaviour with 9 `tsc --strict` cases.
  As delivered, the probes embedded `Expect<Equal<…>>` and `@ts-expect-error`,
  which put the expected answer inside the Evaluation. Review sent it back
  (playbook #21). Probes are now assertion-free:
  - Negative probes contain the plain offending code. The adapter reports
    `(code, line)` diagnostics, and the Oracle requires a diagnostic on
    exactly the lines it holds privately.
  - Positive probes are usage that compiles only if the property holds.

  One distinction checkable only by naming the type is dropped: the literal
  union element type of `.otherwise()`. Both type-only mutants are still
  caught. The mutant runs were done by the agent; review re-ran gates 1, 2
  and 4.
- **`python-statemachine`** as delivered ran each case under one engine, where
  upstream runs almost every test under both sync and async. Review sent it
  back. Every case whose upstream test uses `sm_runner` now runs on both
  engines (14 × 2). The five single-engine cases are single-engine upstream
  too. The diagram-annotation sentence of the instruction has no upstream
  assertion and is not scored.
- **`true-myth`** drives genuinely scrambled task-settlement order. Without
  that, a mutant that pushes values in completion order would pass. Upstream
  has no type-level assertions, so no type probes are needed.
- **`helm`** was blocked until the capture fix for unchanged baseline
  symlinks (conversion-blockers §4). Its adapter builds a driver inside
  `pkg/cmd`, where eight unrelated test files pull in a full OCI registry
  server and OOM the 1 GB link step. The adapter moves them aside for the
  build only and sets `CGO_ENABLED=0`. Those files are baseline-only:
  `**/*_test.go` is excluded from the candidate.
- **`skrub`** as delivered used blanket 1e-3/1e-6 tolerances, looser than
  upstream's exact `==` in places and stricter than its `< 0.6`/`< 0.01`
  bounds in others. Review sent it back. Every check now carries upstream's
  own operator and bound: exact, bound, sign, aggregate or membership. The
  dossier maps each check to its upstream assertion. All mutants are still
  caught. `import skrub` writes to `$HOME`, so the adapter redirects
  `SKB_DATA_DIRECTORY` (playbook #22).
- **`sqlfmt`**'s first fourth mutant flipped no case, because
  `maybe_split_after` already splits after every comma. It was replaced by a
  table-level `UNIQUE` mutant plus a case that exercises it (playbook #8). The
  DML/SELECT regression cases mirror upstream's own idempotency and
  token-presence tests, not gold output.
- **`anko`** maps all 16 upstream F2P table rows 1:1, with no consolidation.
  The two arity-violation scenarios check only that an error occurs, exactly
  as upstream's `RunErrorFunc` does. One candidate mutant axis, the gold
  patch's variadic-default check, is dead code in the gold solution itself, so
  it was replaced by the too-many-arguments check.
- **`csstree`** first dropped 25 F2P assertions as "same mechanism" duplicates.
  Review sent it back (playbook #24). All 79 are now scored as independent
  items, bundled 18 cases to a batch, with the returned item-id set checked
  exactly. Values are transcribed from `test.patch`. The driver is a bare
  `node` ESM script, because the image ships only mocha and esbuild.
- **`tengo-callable`** maps all 23 upstream `TestCompiledFunctionCall_*`
  functions to one scenario each, 4 per case. Composite return values are
  checked, as upstream does, by calling their nested callables. It was first
  integrated with only two targeted mutants and backed out. A third,
  runtime-error-formatting mutant was added before re-integration.
- **`tomlkit`** as delivered folded some upstream tests into cases with a
  different source. Review sent it back (playbook #24). Every F2P test now
  runs on its own exact source at its own strength (36 → 51 cases). Only
  byte-identical merges remain. The audit also removed a byte-exact check
  that upstream makes only as data equality (#20). One Oracle-added 3-level
  `max_depth` case discriminates a bug that upstream's 2-level case cannot.
  Raw `result is doc` identity is dropped as unobservable.
- **`obsidian-linter`** captured its 49 `(before, after)` pairs by
  instrumenting upstream's own `ruleTest` helper inside the image, not by
  retyping them or running gold. The base commit fails exactly the 33 F2P
  items and passes the 16 P2P items. Private-helper offset tests are dropped:
  they are in neither node list. The project uses pnpm, so plain
  `node`/`ts-node` cannot resolve non-hoisted dependencies, and the driver
  runs under jest. Literals shared with the Oracle are rule names, which are
  inputs.
- **`helm-array-merge`** as delivered checked exact element order for
  `merge_nonmap_appended` and `merge_missing_key_appended`. The instruction
  says only that such elements are "preserved", and upstream asserts only
  count and the merged element. Review changed both to an order-insensitive
  multiset comparison. New Oracle tests show a reordered correct result
  passes and a dropped element fails. `nested_merge_key` keeps exact order
  because upstream pins it. Building `pkg/action`'s internal test binary
  OOMs at 1 GB, so the action driver is an external-package consumer built
  with a batched pre-warm, `-p=1`, `GOMEMLIMIT=450MiB`.

## Held for review

| Row | State | Reason |
|---|---|---|
| `expr-try-catch-errors` | qualification-pending (gates pass: 16 passed, re-verified) | gold solution edits `vm/vm_test.go`; capture rejects any excluded-path edit — see [conversion blockers §5](conversion-blockers.md) |
