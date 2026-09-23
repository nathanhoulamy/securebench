# Workaround audit of approved v2 conversions

Date: 2026-09-23. Read-only audit of the working tree on `split-verification-v2` (uncommitted
changes included). No Docker was run.

**Scope.** Every row with `qualification_status = approved` in `inventory.csv`: 28 DeepSWE rows
(including `obsidian-linter-auto-table-of-contents`) and 30 Terminal-Bench rows. Three rows are
excluded because they are being reworked separately: `prometheus-typed-label-sorting`,
`helm-unified-manifest-stream` and `helm-array-merge-strategies`.

**Method.** For each row the audit read:

- the row JSON in `tasks-v2.jsonl`
- the adapter and the Oracle
- the focused test
- the dossier

Each row was then compared with its upstream tests:

- **DeepSWE:** `/tmp/securebench-paper-deepswe-source/tasks/<row>/`, specifically `instruction.md`,
  `tests/test.patch` and `tests/config.json`.
- **Terminal-Bench:** the source verifiers kept at `benchmarks/terminal-bench/hidden/<row>/tests/`
  (`test.sh` and `test_outputs.py`). Where a row has no such copy, the dossier's list of tests was
  used.

The high-impact claims were re-checked directly against the code. Items marked *verified* were
confirmed by reading the cited lines.

**Categories**

- **A: environment workaround.** Examples: memory or CPU flags, timeouts, substitute tools or
  helpers, network narrowing, cache or HOME redirects.
- **B: scope or meaning change.** Examples: a dropped assertion, a looser or stricter check, an
  invented requirement, an expected value copied from the gold solution, missing mutants.
- **C: architecture deviation.** Examples: the adapter judging correctness, expectations visible to
  the Evaluation, a trusted verdict derived from state the candidate controls.

Harmless plumbing is not reported as a finding. This covers:

- building under `/app` because `/tmp` is noexec
- copying read-only build caches
- `TMPDIR` or `SKB_DATA_DIRECTORY` redirects that the scored code never reads
- strict parsers and byte bounds

## Summary table

| Row | Worst category | Changes measurement? | Recommended action |
|---|---|---|---|
| **Pack-wide: DeepSWE memory policy** | A | possibly | Decide whether 8g is the admitted policy; record it in the qualification record |
| **Pack-wide: Terminal-Bench network** | A | possibly | Record the allowlist narrowing in every dossier; qualify under the tester actually used |
| cancel-async-tasks | C | **yes** | Make cleanup candidate-side; stop the adapter writing `task.cleaned` |
| headless-terminal | A | **yes** | Restore the vim case (derived image), probe HTTP while the terminal object is alive, restore upstream waits |
| kv-store-grpc | B | **yes** | Stop pinning field numbers and package path, or disclose them in the prompt; revert int→int32 |
| hf-model-inference | A | **yes** | Stop making the agent delete files to fit the bundle cap; restore a model-identity check |
| sqlite-db-truncate | B | **yes** | Tolerate rows with non-matching types as upstream does; restore the 900 s timeout |
| happy-dom-deterministic-intersectionobserver | C | possibly | Pin the viewport size host-side instead of trusting the guest-reported `innerWidth/innerHeight` |
| cattrs-partial-structuring-recovery | B | possibly | Add ≥3 targeted real-code mutants under Docker; fix dossier status |
| fd-deterministic-multi-key-sorting | B | possibly | Same as cattrs |
| updo-policy-alerting | B | possibly | Same as cattrs |
| updo-policy-alerting (2nd finding) | C | no today, latent | `exclude_paths` omits `alerts/policy_test.go`, `config/config_test.go`, `notifications/webhook_test.go`, `simple/simple_test.go` — add `**/*_test.go` |
| dateutil-rfc5545-timezone-interop | B | possibly | Same Gate-3 gap as cattrs/fd/updo: only the generic mutant runs under real Docker, 5 targeted mutants are Oracle-level only |
| go-critic-doc-link-checker, task-task-graph-export, termenv-preserve-ansi-resets, etree-xml-diff-patch, tengo-callable-instance-isolation, tengo-destructuring-bindings, ink-grid-box-layout, meriyah-explicit-resource-declarations, happy-dom-deterministic-intersectionobserver | B/C | **yes**, for a candidate that also edits a test file | Known, disclosed, unresolved framework defect (`conversion-blockers.md` §5): capture rejects the whole candidate instead of dropping the excluded hunk |
| meriyah-explicit-resource-declarations, mashumaro-flattened-dataclass-fields, true-myth-iterable-collection-combinators | B | possibly | Known, disclosed, unresolved (`conversion-blockers.md` §6): consolidations may drop F2P nodes rather than bundle them — audit still outstanding |
| obsidian-linter-auto-table-of-contents (governance) | process | no | Row's adapter/oracle/`tasks-v2.jsonl` entry and its `approved` status exist only in the uncommitted working tree, unlike every other admitted row — confirm central-integration review actually happened before relying on `Approved` |
| anko-default-function-arguments | A | possibly (unlikely) | Remove `GOMAXPROCS=2` and re-qualify, or justify it in the dossier |
| etree-xml-diff-patch | A | possibly (unlikely) | Same |
| go-critic-doc-link-checker | A | possibly (unlikely) | Same |
| task-task-graph-export | A | possibly (unlikely) | Same |
| tengo-callable-instance-isolation | A | possibly (unlikely) | Same |
| tengo-destructuring-bindings | A | possibly (unlikely) | Same |
| termenv-preserve-ansi-resets | A | possibly (unlikely) | Same |
| write-compressor | A | possibly | Differential-test the Python decoder against gcc-built `decomp.c`; disclose the network change |
| dna-assembly | A | possibly (edge only) | Widen the `oligotm` conformance corpus near Tm thresholds |
| dna-insert | A | possibly (edge only) | Same |
| ink-grid-box-layout | B | possibly | Replay a sample of the 49 flex/text-width P2P tests |
| happy-dom (P2P) | B | possibly | Replay the 8 `EventTarget` P2P tests (see row) |
| git-leak-recovery | B | yes (stricter, disclosed) | Accept it and relabel as `semantic_change`, or scope it to upstream |
| fix-git | B | yes (disclosed) | Relabel as `semantic_change` |
| rstan-to-pystan | B | yes (disclosed) | Complete the dossier; drop `r-project.org` from the codex tester for this row |
| constraints-scheduling | B | possibly (edge only) | Use substring SUMMARY, the attendee regex and the first matching event |
| gpt2-codegolf | B | possibly (low) | Show the provenance and logit margin of the gold-derived second case |
| vulnerable-secret | A | possibly (low) | Restore the 900 s timeout; update the dossier status |
| mteb-leaderboard, mteb-retrieve, protein-assembly, raman-fitting | A | possibly | Justify the domain lists; pin upstream images if they exist |
| count-dataset-tokens, extract-moves-from-video | A | possibly | Correct the "internet retained" wording; show that the download works under the allowlist |
| log-summary-date-ranges | A | no in practice | Disclose the network setting `none` and the image rebuild |
| mashumaro-flattened-dataclass-fields | B | yes (disclosed, labelled) | None; already `semantic_change` |
| returns-validated-error-accumulation | doc only | no | Delete the stale ">=14 laws" prose in the Fidelity section |
| distribution-search | note | no in practice | Optional float32-accumulation parity cases |

## Pack-wide findings

### P1. DeepSWE runs and qualification use 8 GiB, not the 1 GiB framework default (A)

- **What was done:**
  - The framework default memory is 1 GiB (`securebench/sandboxes/docker.py:288`,
    `mem_limit = "1g"`).
  - The uncommitted working tree adds a `docker.memory_limit` tester field
    (`securebench/tester_config.py`, `securebench/tester_run.py`).
  - It sets `memory_limit: 8g` in `benchmarks/deep-swe/tester-linux.yaml`.
  - It changes `tests/deepswe_qualification.py` to qualify under that same value
    (`PACK_MEMORY_LIMIT`).
  - It rewrites playbook item 14. The old text said "Evaluation containers have 1 GB ... build the
    smallest harness". The new text says "Memory is tester policy; never work around it ...
    currently 8g".
  - This applies to **both** the Agent and the Evaluation containers of every DeepSWE row.
- **Assessment:** This is an explicit, tested, documented policy knob, and it replaces the
  per-row workarounds. That is the right direction. However:
  - The qualification record does not say that gates are now run at 8 GiB.
  - Rows qualified earlier at 1 GiB, and rows re-qualified at 8 GiB, are not distinguished.
  - The Agent also gets 8× the memory, which can change task difficulty. For example, an agent can
    build and run the full upstream test suite where 1 GiB would OOM.
- **Changes what's measured:** possibly. It relaxes the resource envelope for every DeepSWE row. A
  memory-hungry or leaky candidate that would OOM at 1 GiB now passes.
- **Recommended fix:**
  - Decide explicitly whether 8g is the admitted policy for the pack.
  - Record that decision, and the gate memory, in `deepswe-qualification-record.md`.
  - Commit the change as its own reviewed decision.

### P2. Terminal-Bench "internet" is an allowlist, and differs by tester (A)

- **What was done:**
  - Upstream records `Internet allowed: True` for every audited Terminal-Bench row.
  - In v2, `internet` and `restricted` both mean "declared domains only"
    (`docs/split-verification/schema.md:~291`).
  - The effective access depends on the tester's `network_policy`:
    - `terminal-bench/tester-linux.yaml` extends a fixed list of domains.
    - Other testers extend different lists, or none (`securebench/network_policy.py:101-121`).
  - `log-summary-date-ranges` and `write-compressor` are declared `none`.
- **Dossiers contradict this.** For example, `count-dataset-tokens.md:125` says it "retains the
  source row's internet access", and `extract-moves-from-video.md:121` says the same.
- **Changes what's measured:** possibly. This matters most for research or download-heavy rows:
  protein-assembly, mteb-*, extract-moves-from-video, rstan-to-pystan and count-dataset-tokens.
- **Recommended fix:**
  - Record the narrowing in each dossier.
  - Either declare each row's required domains, or add a genuinely unrestricted mode.
  - Qualify under the tester that admitted runs use.

### P3. Undisclosed `GOMAXPROCS=2` in seven in-scope Go adapters (A)

- **Rows:**

  | Row | Location |
  |---|---|
  | anko-default-function-arguments | `adapter.py:149` |
  | etree-xml-diff-patch | `:135` |
  | go-critic-doc-link-checker | `:93` |
  | task-task-graph-export | `:191` |
  | tengo-callable-instance-isolation | `:189` |
  | tengo-destructuring-bindings | `:127` |
  | termenv-preserve-ansi-resets | `:158` |

- **What was done:** In every one of these adapters, the same `env` dict is used for `go build`
  **and** for running the compiled driver, which links the candidate's code. So the candidate's
  runtime is capped at 2 Ps, not only the build.
- **Undisclosed:** No dossier mentions it.
- **Forbidden by current rules:** Playbook item 14 now forbids "memory-tuning flags". The helm
  adapter's own comment (`helm-array-merge-strategies/adapter/adapter.py:315-320`) names
  "no GOMAXPROCS/-p serialisation" as forbidden, and helm removed it.
- **Changes what's measured:** possibly, but unlikely.
  - None of these rows' scored behaviour is concurrency-dependent. The drivers are sequential, and
    upstream's `TestScriptConcurrency` for tengo is not in f2p/p2p.
  - The main effect is timing: less build parallelism, and fewer CPUs for the candidate binary.
  - It is still a silent deviation from upstream's unconstrained run.
- **Recommended fix:**
  - Remove it now that memory is tester policy, or apply it only to `go build` and not the driver
    run.
  - Re-run Gate 2 and Gate 3.

### P4. Admission paperwork contradicts status (process)

These dossiers still end with "Admission status: qualification pending", yet `inventory.csv` marks
the rows Approved:

- cattrs-partial-structuring-recovery (`:261-263`)
- fd-deterministic-multi-key-sorting (`:133-135`)
- updo-policy-alerting
- sqlite-db-truncate (`:86`)
- vulnerable-secret

The dossiers for rstan-to-pystan, log-summary-date-ranges, write-compressor, mteb-leaderboard,
mteb-retrieve, raman-fitting, protein-assembly, and **constraints-scheduling** have no
"Implemented v2 conversion" section (mechanically checked: `grep -L "Implemented v2 conversion"`
across all 30 Terminal-Bench dossiers returns exactly these 8; all 28 DeepSWE dossiers and the other
22 Terminal-Bench dossiers have the section). All 8 are from the "Wave B" batch added 2026-09-22/23
per `terminal-bench-qualification-record.md`; that record's own "Wave B" table documents real
Docker gate-case counts for all 8, and this audit independently spot-checked `write-compressor`'s
and `rstan-to-pystan`'s actual Oracle code and found it sound — so this looks like a documentation
gap left behind by the fast Wave-B push, not evidence of a hidden defect in these 8 rows
specifically. It still means a reviewer cannot audit these rows' fidelity claims from the dossier
alone, which is the whole point of the section.

AGENTS.md forbids presenting qualification-pending work as approved. Either the dossiers are stale,
or the admissions are premature.

### P5. Known, disclosed, unresolved framework defect: editing a test file rejects the whole candidate (affects 9 Approved rows)

- **What was done:** this is not a per-row choice; it is a project-wide capture-layer defect
  recorded in the project's own backlog, `docs/benchmark-conversions/conversion-blockers.md` §5
  ("Editing a test file rejects the whole candidate (affects Approved rows)"). `_validate_patch_path`
  raises `CandidateCaptureError` and rejects the **entire** candidate patch the moment it touches any
  `exclude_paths` pattern, rather than dropping just that hunk. DeepSWE Go/TypeScript rows exclude
  `**/*_test.go`/`**/*.test.ts` so a candidate cannot ship its own copy of a hidden test — but a
  correct submission that also adds or fixes a test file (which coding agents do routinely, and
  which upstream graders never penalize) therefore scores zero.
- **Rows named as affected in `conversion-blockers.md`:** `go-critic-doc-link-checker`,
  `task-task-graph-export`, `prometheus-typed-label-sorting` (excluded from this audit's scope),
  `termenv-preserve-ansi-resets`, `etree-xml-diff-patch`, both `tengo-callable-instance-isolation`
  and `tengo-destructuring-bindings` (confirmed via their `exclude_paths`), `ink-grid-box-layout`,
  `meriyah-explicit-resource-declarations`, `happy-dom-deterministic-intersectionobserver` — 9 rows
  in this audit's scope. `expr-try-catch-errors` is held (not registered) for the identical root
  cause, per the same document.
- **Evidence:** `docs/benchmark-conversions/conversion-blockers.md` lines 66–96, which also records
  three candidate fixes and recommends one (drop excluded-path hunks from the captured patch instead
  of rejecting the whole candidate, recording the drop in candidate metadata) — not yet shipped as of
  this audit.
- **Changes what's measured:** **yes**, for the specific (common) class of otherwise-correct
  candidate that also touches a test file — it is scored as a failure when upstream would not have
  penalized it. This is exactly the kind of measurement change this audit was asked to find; it just
  happens to already be self-identified by the project rather than hidden, and it is still live on 9
  Approved rows.
- **Recommended fix:** ship the recommended option 1 from `conversion-blockers.md` §5. This is a
  framework-level fix, not a per-row one.

### P6. Known, disclosed, unresolved: three rows' F2P consolidations may silently drop nodes instead of bundling them

- **Rows:** `meriyah-explicit-resource-declarations`, `mashumaro-flattened-dataclass-fields`,
  `true-myth-iterable-collection-combinators`.
- **What was done:** `conversion-blockers.md` §6 records that the "bundle F2P assertions, never drop
  them" rule (playbook defect #24) was only adopted after `csstree-shorthand-expansion-compression`
  was sent back for dropping F2P assertions as "same-mechanism" duplicates. Rows admitted before
  that rule was enforced may have genuine drops rather than bundles: `meriyah` reduced nested-block
  contexts to 3 representatives and dropped a non-`await` `for-of` variant; `mashumaro` exercises
  some collision checks in only one flatten mode (see also this file's own `mashumaro` finding
  above, which covers a related but distinct P2P-scope decision); `true-myth` tests the empty-input
  edge once (collapsing 10 upstream nodes) and collapses the zip first/second-operand pair.
- **Evidence:** `docs/benchmark-conversions/conversion-blockers.md` lines 99–120: "Each needs an
  audit mapping F2P node to Oracle check. Any genuine drop gets added back as a bundled step and
  re-qualified... They stay Approved meanwhile... Flagging for your call on whether to demote them
  until audited." This audit did not perform that node-by-node mapping itself (it requires walking
  every named upstream test against every Oracle scenario for all three rows) — it is reporting the
  project's own outstanding item, which is unresolved as of this pass.
- **Changes what's measured:** possibly — per the document's own position, "none of the drops
  loosens a check that is made, they only omit some," so no existing check is wrong, but an omitted
  F2P node is untested coverage until the audit happens.
- **Recommended fix:** perform the F2P-node-to-Oracle-check mapping `conversion-blockers.md` calls
  for on these three rows.

## Per-row findings (DeepSWE)

### cattrs-partial-structuring-recovery, fd-deterministic-multi-key-sorting, updo-policy-alerting

- **Category:** B (Gate 3 not met), plus the P4 paperwork issue.
- **What was done:**
  - These are the "first wave" rows. Their Docker coverage is
    `tests/test_deepswe_first_wave_replay_v2.py`:
    - base fails
    - gold passes in fresh Evaluations
    - one generic "incomplete implementation" mutant: the largest non-test file dropped
  - Their targeted mutants are Oracle-level only. `tests/test_pilot_conversions_v2.py:160-229` feeds
    hand-built observations into the Oracle.
  - The first-wave table of `deepswe-qualification-record.md` lists only "Partial mutant: fails"
    for these three rows. Compare go-critic, which has real semantic mutants in
    `tests/test_go_critic_conversion_v2.py`.
- **Evidence:** as above. The dossiers still say "Linux image qualification remains to be recorded
  ... collection/refinement/factory mutants", with a similar sentence for fd and updo.
- **Changes what's measured:** possibly. The code itself looks sound:
  - cattrs' invented picklability and `error_map` requirements are removed (`oracle.py:112-117`).
  - fd builds in `/app` and does not combine `--strip-cwd-prefix` with a path (`adapter.py:67-72`).
  - updo's recorder evidence is host-side and correlated (`oracle.py:184-192`).

  But the playbook's acceptance criterion ("≥3 targeted real-code mutants under Docker;
  Oracle-level mutants do not count") is unmet.
- **Recommended fix:** Add three targeted real-code mutants each under Docker, then update the
  dossiers.

**A fourth row shares this exact defect, and is worse-hidden: `dateutil-rfc5545-timezone-interop`.**
Verified directly by decorator inspection of
`tests/test_deepswe_dateutil_rfc5545_timezone_interop_v2.py`: `@DOCKER_INTEGRATION` appears only
above `test_base_fails_through_the_real_capture_path`, `test_reference_passes_in_fresh_evaluations`,
and `test_dropping_the_largest_source_change_fails` (lines 82, 91, 124) — i.e. Gates 1, 2, and the
generic mutant only. The five targeted-axis mutant tests
(`test_mutant_wrong_rdate_tzid_offset_fails` and four siblings, lines 321-390) carry no
`@DOCKER_INTEGRATION` decorator and only mutate an in-memory observation dict via
`OracleProcessSession` (no container, no candidate code) — the file's own header comment says so
plainly: *"(real-capture Docker replay for Gates 1/2 and the generic file-drop mutant)... distinct-axis
mutants required by Gate 3..."* Unlike `cattrs`/`fd`/`updo`, this row's dossier does **not** disclose
the gap — it states **"Status: QUALIFIED."** (`dateutil-rfc5545-timezone-interop.md:301`) with no
caveat, which is a stronger, uncaveated claim than the three "first wave" rows make for themselves
despite resting on the identical unmet Gate‑3 requirement. Recommended fix: same as above (add ≥2
real-Docker targeted mutants), plus correct the dossier's "QUALIFIED" claim until that's done.

**Second finding on `updo-policy-alerting` only (Category C, verified).** Its `exclude_paths` is
`["tests/**", "test.sh", "securebench/**", "**/test-results/**", ".gocache/**"]` — every other
in-scope Go DeepSWE row (`anko`, `etree`, `go-critic`, `task-task-graph-export`, both `tengo`
rows, `termenv`) carries a `**/*_test.go` glob; this one does not. Upstream `tests/test.patch`
touches `alerts/policy_test.go`, `simple/simple_test.go`, `config/config_test.go`,
`notifications/webhook_test.go` (Go convention co-locates `_test.go` with source, not under
`tests/`), none of which match any current pattern. **Changes what's measured:** no today —
`adapter.py:33` runs `go run ./<tmpdir>` against a synthesized `main.go` that imports only the
candidate's production packages, and Go's toolchain never compiles `_test.go` files under
`go build`/`go run`, so a candidate editing these four files currently has no effect on the
observed behavior. But it is a real gap against the framework's own stated invariant ("a candidate
can never ship its own copy of a hidden test") and a latent risk if the adapter's build mechanism
ever changes. **Recommended fix:** add `**/*_test.go` (or the four exact paths) to `exclude_paths`.

(See "A fourth row shares this exact defect..." immediately above for `dateutil-rfc5545-timezone-interop`'s
full writeup — cross-confirmed independently by this audit against `deepswe-qualification-record.md`'s
own footnote: "**dateutil**'s targeted mutants are Oracle-level; only the generic mutant runs as real
code under Docker," and by the fact its dossier says "Status: QUALIFIED" with no caveat, unlike the
three "first wave" rows' own more candid "remains to be recorded" language.)

### happy-dom-deterministic-intersectionobserver

- **Finding 1 (C, verified).**
  - **What was done:** For viewport-root cases, the Oracle builds its expected root rectangle from
    the guest-reported `window_inner_width` and `window_inner_height`
    (`oracle/oracle.py:483-491`). Upstream also asserts
    `rootBounds.width == window.innerWidth` (`test.patch:86-87`), so the relative check is faithful.
  - **The problem:** The dimension is candidate-controlled (`src/window/Window.ts` is patchable),
    and in adversarial terms it is a guest observation used as ground truth. A candidate that
    inflates `innerWidth/innerHeight` and fakes "always intersecting" could satisfy the
    far-away-viewport case, which exists to catch exactly that.
  - **Changes what's measured:** possibly (an adversarial candidate only).
  - **Recommended fix:** Have the Oracle pin the default Happy DOM viewport (as it already does for
    element roots), or report a mismatch when the observed viewport differs from the default.
- **Finding 2 (B, disclosed).**
  - **What was done:** The 8 P2P `EventTarget` regression tests are not replayed.
  - **Changes what's measured:** possibly. A patch that breaks `addEventListener` or
    `dispatchEvent` would pass.
  - **Recommended fix:** Add a small `EventTarget` regression case.

### ink-grid-box-layout

- **Category:** B.
- **What was done:** All 49 upstream P2P tests (`test/flex*.tsx`, `test/text-width.tsx`) are
  dropped. Only the 25 F2P grid scenarios are scored (dossier `:242-247`).
- **Changes what's measured:** possibly. A candidate that regresses flex layout while adding grid
  support passes v2 and fails upstream.
- **Recommended fix:** Replay a stratified sample of flex/text-width cases through the existing
  renderer.

### mashumaro-flattened-dataclass-fields

- **Category:** B (disclosed).
- **What was done:** About 29.8k P2P nodes are not exercised. Exact exception class/message and the
  timing of validation are dropped (dossier `:356-368`).
- **Changes what's measured:** yes. The row is already labelled `semantic_change`/`low`.
- **Recommended fix:** No change needed.

### task-task-graph-export, anko-default-function-arguments, etree-xml-diff-patch, go-critic-doc-link-checker, tengo-callable-instance-isolation, tengo-destructuring-bindings, termenv-preserve-ansi-resets

Only P3 (`GOMAXPROCS=2`). The Oracles and adapters are otherwise faithful:

- tengo scenarios were checked byte-for-byte against `test.patch`.
- termenv's absence check uses a disjoint alphabet (uppercase vs lowercase, `oracle.py:358-367`),
  so playbook defect 7 is genuinely fixed.
- go-critic has real Docker semantic mutants.

etree's dossier claims "Fidelity limitations: none identified", which is not strictly true once P3
is counted.

**go-critic-doc-link-checker's own admitted metadata literally says it is unqualified, independent
of P3.** Verified directly:
`grep '"deep-swe/go-critic-doc-link-checker"' benchmarks/deep-swe/tasks-v2.jsonl | python3 -m json.tool`
shows `"metadata": {"conversion": {"verdict": "qualification_pending", "dossier": "..."}}` — the row's
own machine-readable admission record disagrees with its `Approved` status in `inventory.csv`, and
with the dossier's own closing line ("Status: qualification-pending, not a final Approved admission...
a pending record must not be included in admitted benchmark results"). The real gate evidence this
row has (168 passed, 7 semantic mutants, via `test_go_critic_conversion_v2.py`, predating the later
`test_deepswe_<row>_v2.py` convention) suggests this is a bookkeeping gap rather than missing work —
but it is a literal, checked-in contradiction inside the admitted artifact set and should be fixed by
updating `metadata.conversion.verdict` to match the real verdict, not by reverting the row.

### returns-validated-error-accumulation

- **Category:** documentation only.
- **What was done:** The shipped Oracle pins exactly the 16 `test_validated_laws` names from
  `config.json` (`oracle.py:50-65`) and requires `laws_failed == []`, so playbook defect 20 is
  fixed. But the dossier's Fidelity section still describes the old ">=14" acceptance, contradicted
  only by a trailing correction note.
- **Changes what's measured:** no.
- **Recommended fix:** Rewrite the stale bullet.

### Notes: not workarounds, recorded for completeness

- **Fixed corpora.** meriyah, narwhals and obsidian-linter-auto-table-of-contents use fixed
  challenge corpora rather than per-`run_seed` randomisation. obsidian uses upstream's own
  `before`/`after` fixtures verbatim.
  - This matches upstream exactly, so it is not a fidelity change.
  - narwhals' dossier (`:483-492`) admits the shipped Oracle departs from its own validation plan,
    which called for randomisation.
  - Randomisation would harden these rows against memorisation of public upstream fixtures. This
    is an optional improvement, not a regression.
- **obsidian-linter-auto-table-of-contents.**
  - The row JSON and the qualification record say `clean/none`, but `inventory.csv` still says
    "Conversion with semantic change / Low".
  - The `clean` verdict is correct: all 41 F2P triples are kept, and `test.patch` has no P2P tail.
  - Update `inventory.csv`.
  - **Separate, more consequential governance point (verified):** the row's `approved` status in
    `inventory.csv` is itself an **uncommitted** working-tree edit — `git diff HEAD --
    docs/benchmark-conversions/inventory.csv` shows exactly this one line flipping
    `design_only`/`not_implemented` to `implemented`/`approved` among the DeepSWE rows, with no
    corresponding commit. `benchmarks/deep-swe/v2/evaluation_inputs/obsidian-linter-auto-table-of-contents/`
    and `benchmarks/deep-swe/v2/hidden/obsidian-linter-auto-table-of-contents/` are both untracked
    (`git log --oneline -- <path>` returns nothing for either), and `git show
    HEAD:benchmarks/deep-swe/tasks-v2.jsonl | grep -c obsidian-linter-auto-table-of-contents`
    returns `0` — the row only exists in the current uncommitted working copy of that file. Every
    other DeepSWE row's `approved` status and supporting adapter/oracle files were committed
    together in `69f5314` ("Admit 30 DeepSWE and 30 TerminalBench v2 conversions"). The playbook
    reserves `inventory.csv`/`tasks-v2.jsonl` edits for central integration "after they qualify" —
    as the repository stands, this row's `Approved` label is indistinguishable from a conversion
    agent having marked its own row approved, whether or not that is what happened. The technical
    qualification itself looks sound (Gates 1–4 all written up with real Docker evidence in the
    dossier), so this is a process/governance gap, not a fidelity one: confirm central-integration
    review actually occurred before relying on this row's `Approved` status, and commit the row and
    its status together as every other row was.
- **true-myth-iterable-collection-combinators.** `--typecheck.enabled=false` is harmless, because
  `test.patch` contains no type-level assertions.

## Per-row findings (Terminal-Bench)

### cancel-async-tasks

- **Category:** C/B (verified).
- **What was done:**
  - **Upstream:** cleanup is the candidate coroutine's own `finally: await asyncio.sleep(1);
    print("Cleaned up.")`.
  - **v2:** tasks are RPC stubs. The trusted adapter thread records `task.cancelled`, sleeps for
    `cleanup_ms`, and then **itself** records `task.cleaned` whenever the socket closes
    (`v2/evaluation_inputs/cancel-async-tasks/adapter/adapter.py:175-199`).
  - A candidate that does not let cleanup run is scored the same as one that does. Examples:
    - it double-cancels
    - it returns without awaiting, so `asyncio.run` re-cancels mid-`finally`
    - it calls `os._exit` on SIGINT
  - The adapter also waits for `min(task_count, max_concurrent)` starts before sending SIGINT.
    Upstream sends it at a fixed 500 ms. This is a documented load-timing workaround (dossier
    `:194-200`), but it encodes expected behaviour in the adapter.
  - Durations were shortened: work 2 s → 0.6 s, cleanup 1 s → 0.2 s.
  - No mutant targets interrupted cleanup.
- **Changes what's measured:** yes. The task's central requirement, "cleanup code still runs", is
  decided by trusted code rather than candidate behaviour.
- **Recommended fix:**
  - Have the candidate stub's `finally` perform an awaited cleanup RPC with a server-side delay.
  - Record `cleaned` only when that RPC completes, and record EOF only as `cancelled`.
  - Add double-cancel, no-await and `os._exit` mutants.

### headless-terminal

- **Category:** A/B (verified).
- **What was done:**
  1. The upstream vim case was replaced with a Python REPL.
     - The dossier calls vim's absence "a source-row defect", but upstream `tests/test.sh:4-5` runs
       `apt-get install -y vim`, so the case was passable upstream.
     - This is an offline-Evaluation workaround, and it makes the interactive case easier (no
       full-screen TUI, ESC or `:wq`).
  2. The driver now exits, and the adapter SIGKILLs its process group, **before** the HTTP probe
     (`adapter.py:200-219, 284-287`). Upstream probes while the terminal object is alive.
     - pexpect or ptyprocess-style implementations send SIGHUP to the background server and fail
       v2, even though they pass upstream.
     - The dossier's own model smoke failed on this case.
  3. Waits are tighter than upstream: 5 s → 1.2 s, 1 s → 0.7 s and 2 s → 0.5 s.
  4. HOME is a fresh directory. This is plumbing.
- **Changes what's measured:** yes, in both directions:
  - valid implementations are rejected
  - the interactive case is easier
- **Recommended fix:**
  - Use a pinned derived image with vim and restore the vim sequence.
  - Probe HTTP while the terminal is alive.
  - Restore upstream waits.
  - Add a pexpect-based positive control.
  - Correct the dossier.

### kv-store-grpc

- **Category:** B (verified), plus A.
- **What was done:**
  - The upstream grpcio client, built from the candidate's generated stubs, was replaced with a
    hand-written HTTP/2+protobuf client. It hard-codes:
    - the method path `/KVStore/GetVal|SetVal` (`adapter.py:399`)
    - field numbers `key=1, value=2, val=1` (`adapter.py:73-120`)
  - The Oracle regex additionally requires exactly `string key = 1;`, `int32 value = 2;` and
    `int32 val = 1;` (`oracle.py:75-79`).
  - The public prompt specifies neither field numbers nor the absence of a `package`. It was
    edited from "(int)" to "(int32)".
  - `RLIMIT_FSIZE` of 32 KiB is imposed on the server.
- **Changes what's measured:** yes. A correct proto with a `package` line or different field
  numbers passes upstream and fails v2.
- **Recommended fix:** Choose one:
  - Derive the package and field numbers from the passively parsed proto and send them in the
    challenge.
  - Use a pinned trusted grpcio client built from the candidate proto host-side.
  - At minimum, state the wire contract in the prompt and label the row `semantic_change`.

### hf-model-inference

- **Category:** A/B (verified).
- **What was done:**
  - The model export (~268.8 MB) exceeds the 256 MiB bundle ceiling. The public prompt was
    therefore extended with packaging instructions:
    - delete `tokenizer.json` and `special_tokens_map.json`
    - stay below 268,200,000 bytes
    - vendor dependencies into `/app/hf_service_dependencies`
    - run app.py in the foreground
  - The dossier's own model smoke scored 0 because the cleanup command was blocked
    (`candidate_capture_rejected`). The workaround created a new failure mode.
  - Upstream `test_model_downloaded` loads the model and tokenizer. v2 never checks the model
    directory, so a heuristic `app.py` could pass the fixed sentences.
  - An IPv4-only `0.0.0.0` listener is required, read from `/proc/net/tcp` (`adapter.py:105-123`).
- **Changes what's measured:** yes.
- **Recommended fix:**
  - Treat the bundle ceiling as a blocker to decide: raise it per row, or exclude the files through
    capture rules rather than prompt edits.
  - Add a hash check of `model.safetensors` against the pinned revision.
  - Accept dual-stack listeners.

### sqlite-db-truncate

- **Category:** B/A (verified).
- **What was done:**
  - The Oracle fails the whole file on any row whose `value` is not numeric or whose `word` is not
    a string (`oracle.py:46-48`).
  - Upstream only intersects `(word, value)` tuples and ignores non-matching rows
    (`hidden/sqlite-db-truncate/tests/test_outputs.py:21-27`). So "7 correct rows plus one
    `value: null` row" is a plausible recovery output that passes upstream and fails v2.
  - The dossier's claim that unrelated pairs "do not affect scoring" is false for such rows.
  - The agent timeout is 1200 s against upstream's 900 s.
  - `trunc.db` is mounted read-only. This is undisclosed.
- **Changes what's measured:** yes.
- **Recommended fix:**
  - Skip rows with mismatched types, and reject only a non-list root or missing keys.
  - Set the timeout to 900.
  - Update the dossier.

### vulnerable-secret

- **Category:** A.
- **What was done:** The agent timeout is 1200 s against upstream's 900 s (dossier `:15`). The
  Oracle is otherwise exact. The dossier still says "qualification pending".
- **Changes what's measured:** possibly (more time only).
- **Recommended fix:** Set the timeout to 900 and update the dossier.

### write-compressor

- **Category:** A.
- **What was done:**
  - Upstream compiles `decomp.c` with gcc and pipes `data.comp` through it. v2 uses a Python
    reimplementation of the decoder (`oracle.py:1-147`).
  - That decoder uses unbounded ints, assumes a zeroed buffer, and adds its own limits.
  - Conformance evidence is a single reference stream.
  - The network is `none` and the image is rebuilt locally. The dossier has no v2 section.
- **Changes what's measured:** possibly. Encoders that take decoder paths the reference stream
  never exercises could get a different verdict. Examples: negative literals, long overlapping
  matches, int overflow in `fraction`.
- **Recommended fix:** Run a host-side differential test against gcc-built `decomp.c` over varied
  encoder outputs. Disclose the network change.

### dna-assembly, dna-insert

- **Category:** A (disclosed).
- **What was done:** Upstream runs Primer3's `oligotm` binary. v2 uses a Python reimplementation
  (`securebench/verification/oligotm.py`), validated against only 7 vectors
  (`tests/test_oligotm.py:7-24`). The fixtures are byte-identical to upstream.
- **Changes what's measured:** possibly, only for primers whose Tm sits at the 58/72 °C or 5 °C
  bounds.
- **Recommended fix:** Build a large conformance corpus weighted toward those thresholds. Pin the
  Primer3 version.

### git-leak-recovery

- **Category:** B (disclosed).
- **What was done:** The Oracle rejects `secret[` in any object (`oracle.py:48-49`). Upstream checks
  only reachable history and `git fsck`-dangling objects.
- **Changes what's measured:** yes, stricter. The metadata still says `intelligence_impact: none`.
- **Recommended fix:** Relabel as `semantic_change`, or scope the check to match upstream.

### fix-git

- **Category:** B (disclosed).
- **What was done:** `/app/resources`, which contains the gold `patch_files`, is masked for the
  agent. This removes an upstream answer leak.
- **Changes what's measured:** yes, harder. The metadata says `none`.
- **Recommended fix:** Relabel as `semantic_change`.

### rstan-to-pystan

- **Category:** B (disclosed).
- **What was done:**
  - `test_r_rstan_not_installed` is dropped. This is accurately disclosed in `oracle.py:13-24`, the
    qualification record and the metadata.
  - The dossier has no implemented section, and its review boxes are unticked.
  - `tester-codex.yaml` allows `r-project.org`, so installing R is possible and undetected.
- **Changes what's measured:** yes (disclosed).
- **Recommended fix:** Complete the dossier. Remove `r-project.org` for this row, or capture an
  installed-package manifest.

### constraints-scheduling

- **Category:** B (minor).
- **What was done:** The Oracle is stricter than upstream in three places (`oracle.py:73-80`):
  - SUMMARY must match exactly; upstream uses a substring match.
  - ATTENDEE must match exactly; upstream uses a `.*email$` regex.
  - Exactly one meeting event is required; upstream takes the first match.

  It is also more lenient: the parser handles folded lines.
- **Changes what's measured:** possibly, for unusual ICS output only.
- **Recommended fix:** Mirror upstream's matching.

### gpt2-codegolf

- **Category:** B (low).
- **What was done:** A second hidden prompt was added. Its expected continuation was produced by the
  gold `reference.c` (`oracle.py:13-22`); upstream never asserted it.
- **Changes what's measured:** possibly. A correct implementation could diverge at a near-tie argmax.
- **Recommended fix:** Verify it against an independent GPT-2, record the per-step logit margin, and
  document where the value came from.

### mteb-leaderboard, mteb-retrieve, protein-assembly, raman-fitting

- **Category:** A.
- **What was done:**
  - Network allowlists (see P2).
  - Images are rebuilt locally and pinned by bare ID. The qualification record says
    `alexgshaw/<task>` does not exist, yet each dossier lists `alexgshaw/<task>:20251031`.
  - The mteb images install unpinned dependencies.
  - The Oracles are faithful.
  - None of the four dossiers has an implemented section.
- **Changes what's measured:** possibly.
- **Recommended fix:** Resolve the image discrepancy, justify the domain lists, and write the
  dossier sections.

### count-dataset-tokens, extract-moves-from-video

- **Category:** A (P2 only).
- **What was done:** The Oracles match upstream exactly. The dossiers wrongly say internet access is
  retained.
- **Changes what's measured:** possibly.
- **Recommended fix:** Correct the wording. For the video row, show that the download works under the
  allowlist.

### log-summary-date-ranges

- **Category:** A.
- **What was done:** Network is `none`, which is undisclosed. The image is rebuilt locally. The
  Oracle is exact.
- **Changes what's measured:** no in practice (the task is offline).
- **Recommended fix:** Disclose both.

### distribution-search (note)

Upstream sums in the array's own dtype, float32. v2 uses compensated float64. Verdicts could differ
only at the 1e-3 or 1e-5 tolerance boundary.

## Rows with no findings

These rows have no findings beyond the pack-wide ones:

- **DeepSWE (apart from P1):**
  - bandit-structured-nosec-directives: playbook defects 5, 8 and 9 were verified fixed
  - csstree-shorthand-expansion-compression
  - obsidian-linter-scoped-ignore-markers
  - pest-character-class-coalescing
  - python-statemachine-state-data-scoping
  - skrub-duration-encoding: `SKB_DATA_DIRECTORY` is harmless
  - sqlfmt-create-table-ddl-formatting
  - tomlkit-toml-table-converters
  - true-myth-iterable-collection-combinators
  - ts-pattern-match-each: no `Expect<`, `Equal<` or `@ts-expect-error` in shipped probes
  - narwhals-rolling-window-suite
- **Terminal-Bench (apart from P2):**
  - bn-fit-modify: KS bound reproduces scipy's `p >= 0.001`
  - chess-best-move
  - code-from-image
  - crack-7z-hash
  - db-wal-recovery
  - feal-linear-cryptanalysis
  - financial-document-processor
  - gcode-to-text

## Housekeeping

During the audit, a sub-agent imported one Oracle, which created
`benchmarks/terminal-bench/v2/hidden/dna-insert/oracle/__pycache__/oracle.cpython-314.pyc`. The file
is gitignored, and similar `__pycache__` files already exist in other Oracle directories. Delete it
if Oracle directories are digested.
