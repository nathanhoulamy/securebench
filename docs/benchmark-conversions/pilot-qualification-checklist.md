# First-wave conversion qualification checklist

Use this checklist on the Linux host after checking out the exact conversion
commit. Tick a row only after its real pinned image has run end to end and its
dossier contains the resulting evidence. Deterministic unit tests are useful,
but they do not replace Linux/Docker qualification.

Inventory review disposition and runtime qualification are separate. The
first-wave control, `sqlite-db-truncate`, and `vulnerable-secret` sections
remain intentionally unchecked; the twenty incrementally qualified rows below
currently have binary admission decisions. The intervening
`feal-differential-cryptanalysis` row retains its manually approved Excluded
decision, and `filter-js-from-html` remains Excluded under the current browser
trust model. `fix-ocaml-gc` is likewise Excluded until an independent bounded
compiler/runtime scenario runner exists. Global preflight and final pack
sign-off therefore remain incomplete.

Test-layout status is separate from admission: all twenty incremental rows
use the compact shared `file_bundle` qualification proof. `dna-assembly`,
`dna-insert`, `extract-elf`, `extract-moves-from-video`, and
`feal-linear-cryptanalysis` each add one declarative row record;
`financial-document-processor` extends the same matrix to bounded directory
trees, `fix-code-vulnerability` adds a two-file artifact/protocol row, and
`fix-git` adds a masked two-file passive row plus exact-path Git compatibility.
`gcode-to-text` returns to the declarative one-file passive pattern;
`git-leak-recovery` adds a bounded stored-tree Git parser and exact declared
nested-repository ownership compatibility.
All retain row-specific semantic, parser/Adapter, Oracle,
malicious-Candidate, and replay evidence in focused files.

## Run identity and host preflight

- [x] Branch is `split-verification-v2`; the prior incremental batch's tested
  implementation commit is
  `c3958a188db6565afed2a8de311c20bb036d7bdb`.
- [x] `git status --short` was clean at that published implementation commit.
- [x] The qualified `circuit-fibsqrt` working tree, based on
  `549b0a85e86f49f0a0a843c0dd6b19d1caf714e1`, was committed as
  `f588721e2aacd48a131057de5f5a0a5b40dbeb7a` and rechecked with a clean
  working tree.
- [x] The qualified `cobol-modernization` working tree, based on
  `bea43435c8a844fa64dd6a7128027556bb6d0d6b`, was committed as
  `40d36e15e3aa23a4aa401aa2a8f81b866253da6b` and rechecked with a clean
  working tree.
- [x] The five passive rows from `code-from-image` through
  `distribution-search` are implemented at `ad6b432`; their Linux
  qualification used that row implementation plus the reviewed
  `tester-linux.yaml` Hugging Face allowlist correction.
- [x] The compact qualification migration and `dna-assembly` implementation
  are committed at `035094b0d9f59c21221dfc71c1ed4ffd90b81614`.
- [x] The `dna-insert` implementation is committed at
  `d46e0480de186b69daff2eae901bb57a4a350319`.
- [x] The `extract-elf`, `extract-moves-from-video`,
  `feal-linear-cryptanalysis`, and `financial-document-processor`
  implementations and the generic nested-file selector are committed at
  `fa23d3969b9cc61aefac8a2ff3a4a2c969e94d71`.
- [x] The final pandas-NA fidelity refinement, refreshed financial-row
  qualification, `fix-code-vulnerability`, the read-only sibling mount and Git
  ownership compatibility, and `fix-git` conversion are based on that commit
  in the current working tree.
- [x] Host, date, OS, kernel, and architecture are recorded: 2026-08-26 through
  2026-09-01, Linux `7.0.0-29-generic`, x86_64.
- [x] `docker version` succeeds and Docker uses Linux/amd64 containers
  (Docker `29.7.2`).
- [x] Free disk space is sufficient for the pinned benchmark images and run
  output.
- [ ] The environment is installed with `python -m pip install -e '.[dev]'`.
- [x] The full `.venv/bin/python -m pytest -q -W error` suite passes
  (`1013 passed, 113 skipped`).
- [x] `.venv/bin/securebench audit-self --output-dir /tmp/securebench-audit-self`
  passes (`93/93`, no warnings).
- [x] `.venv/bin/securebench audit --config benchmarks/terminal-bench/tester-linux.yaml --output-dir /tmp/terminal-bench-v2-audit`
  passes with all twenty-three selected rows (`93/93`, no warnings).
- [x] `.venv/bin/securebench audit --config benchmarks/deep-swe/tester-linux.yaml --output-dir /tmp/deep-swe-v2-audit`
  passes with all three selected rows (`13/13`, no warnings).
- [x] The selected harness credential mode is usable. For `auth: api_key`, the
  configured env file must contain `OPENAI_API_KEY`; run `securebench auth
  codex status` only when `auth: subscription` is selected. API-key-backed
  smoke runs completed, and no subscription login is configured.
- [x] Every selected task image uses and resolves to the digest declared in its
  row; no mutable
  tag was substituted.

Audit artifacts: `/tmp/securebench-precommit-audit-self`,
`/tmp/securebench-precommit-terminal-audit`, and
`/tmp/securebench-precommit-deep-audit`; circuit-specific audits are under
`/tmp/securebench-circuit-precommit-audit-self`,
`/tmp/securebench-circuit-precommit-terminal-audit`, and
`/tmp/securebench-circuit-smoke/audit`; COBOL-specific audits are under
`/tmp/securebench-cobol-final-audit-self`,
`/tmp/securebench-cobol-final-terminal-audit`, and
`/tmp/securebench-cobol-final-one-row-audit`. The thirteen-row final reports
are under `/tmp/securebench-terminal-13-row-audit.FMImnH` and
`/tmp/securebench-self-audit.wZO30X`. The workspace filesystem had 186 GiB
free at the 2026-08-31 qualification pass. The `extract-elf` reports are under
`/tmp/securebench-extract-elf-terminal-audit`,
`/tmp/securebench-extract-elf-self-audit`,
`/tmp/securebench-extract-elf-deep-audit`, and
`/tmp/securebench-extract-elf-smoke/audit`; the workspace had 184 GiB free at
its 2026-09-01 qualification pass. The `extract-moves-from-video` reports are
under `/tmp/securebench-extract-moves-terminal-audit`,
`/tmp/securebench-extract-moves-self-audit`,
`/tmp/securebench-extract-moves-deep-audit`, and
`/tmp/securebench-extract-moves-smoke/audit`. The
`feal-linear-cryptanalysis` reports are under
`/tmp/securebench-feal-linear-terminal-audit`,
`/tmp/securebench-feal-linear-self-audit`,
`/tmp/securebench-feal-linear-deep-audit`, and
`/tmp/securebench-feal-linear-one-row-audit`. The final financial-document
reports are under `/tmp/securebench-financial-exact-terminal-audit`,
`/tmp/securebench-financial-exact-audit-self`,
`/tmp/securebench-financial-exact-deep-audit`, and
`/tmp/securebench-financial-exact-one-row-audit`. The final fix-code reports
are under `/tmp/securebench-fix-code-final-terminal-audit`,
`/tmp/securebench-fix-code-final-audit-self`,
`/tmp/securebench-fix-code-final-deep-audit`, and
`/tmp/securebench-fix-code-final-one-row-audit`. The final fix-git reports are
under `/tmp/securebench-fix-git-final2-terminal-audit`,
`/tmp/securebench-fix-git-final2-audit-self`,
`/tmp/securebench-fix-git-final2-deep-audit`, and
`/tmp/securebench-fix-git-final2-one-row-audit`. The final gcode reports are
under `/tmp/securebench-gcode-final-terminal-audit`,
`/tmp/securebench-gcode-final-audit-self`,
`/tmp/securebench-gcode-final-deep-audit`, and
`/tmp/securebench-gcode-final-one-row-audit`. The final Git leak reports are
under `/tmp/securebench-git-leak-final-terminal-audit`,
`/tmp/securebench-git-leak-final-audit-self`,
`/tmp/securebench-git-leak-final-deep-audit`, and
`/tmp/securebench-git-leak-final-one-row-audit`.

## Terminal-Bench

The tasks are ordered so these commands start exactly one new row at a time:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 1
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 2 --resume
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 3 --resume
```

Use a new `--output-dir` when intentionally rerunning a completed row. Confirm
the task ID in each result rather than inferring it from command order.

### Control: `terminal-bench/constraints-scheduling`

- [ ] The known-good control completes in the pinned Linux image.
- [ ] The captured candidate contains only `meeting_scheduled.ics` and remains
  within its declared byte bound.
- [ ] The Oracle, not guest output, issues the final verdict.
- [ ] Result path and execution digest are recorded: `_______________________`.

Control result: [ ] Passed  [ ] Failed

### `terminal-bench/sqlite-db-truncate`

- [ ] Missing `/app/recover.json` fails candidate capture or verification.
- [ ] The original/base state fails the intended recovery requirement.
- [ ] A reference recovery with at least seven distinct correct rows passes.
- [ ] Six correct rows plus duplicates fails; duplicates cannot inflate the
  recovery count.
- [ ] Extra candidate fields and unrelated rows cannot assert a verdict or
  change the host-owned expected set.
- [ ] Malformed JSON, an oversized file, a symlink, and a non-regular output are
  each rejected closed.
- [ ] The end-to-end Agent run completes in the pinned Linux image.
- [ ] The Candidate contains exactly the bounded declared artifact; inputs,
  logs, processes, and other workspace state are absent.
- [ ] Disposable state is removed and no container, mount, network rule, or
  helper state survives the case.
- [ ] Linux evidence and the execution digest are added to
  [`sqlite-db-truncate.md`](TerminalBench/sqlite-db-truncate.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

### `terminal-bench/vulnerable-secret`

- [ ] Missing `/app/results.txt` fails candidate capture or verification.
- [ ] The original/base state fails the exact-secret requirement.
- [ ] The reference-extracted secret passes through the bounded UTF-8 parser.
- [ ] A plausible but incorrect `FLAG{...}` value fails.
- [ ] Leading/trailing whitespace follows the documented original semantics and
  does not allow extra content to bypass comparison.
- [ ] Malformed UTF-8, an oversized file, a symlink, and a non-regular output
  are each rejected closed.
- [ ] The end-to-end Agent run completes in the pinned Linux image.
- [ ] The Candidate contains exactly the bounded declared artifact; the
  executable, processes, logs, and other workspace state are absent.
- [ ] Disposable state is removed and no container, mount, or network rule
  survives the case.
- [ ] Linux evidence and the execution digest are added to
  [`vulnerable-secret.md`](TerminalBench/vulnerable-secret.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

## Incremental Terminal-Bench conversions

Continue source-ordered Terminal rows one at a time after the first-wave pilot. For the fourth
Terminal row, resume the first three results and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 4 --resume
```

### `terminal-bench/bn-fit-modify`

- [x] The source verifier and all scoring assertions were mapped to independent artifact evidence.
- [x] No Trusted Helper or Evaluation Adapter is required; Candidate code never executes during verification.
- [x] `securebench.strict-csv/v1` has closed finite byte, row, column, cell-count, and cell-size bounds plus malformed-input tests.
- [x] The unmodified/missing-output state fails through Oracle-owned Candidate-error handling.
- [x] A deterministic correct DAG, intervention DAG, and 10,000-row sample pass.
- [x] The known-good reference passes through the real digest-pinned Linux image and stopped-state capture path.
- [x] Targeted edge, intervention, distribution, row-count, and column mutants fail.
- [x] Candidate verdict claims cannot affect scoring.
- [x] Malformed CSV, invalid UTF-8, NULs, duplicate headers, ragged rows, symlinks, directories, and oversized files fail closed.
- [x] The live Agent run completes with `infrastructure_error: null` and the Oracle correctly rejects its semantically wrong artifacts.
- [x] The Candidate contains exactly three declared regular files and no input, log, process, or workspace state.
- [x] No SecureBench container, network, or volume survives the live run.
- [x] Linux evidence, fidelity notes, and result provenance are recorded in [`bn-fit-modify.md`](TerminalBench/bn-fit-modify.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion; qualified on Linux on 2026-08-25. Live execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the fifth Terminal row, resume the first four results and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 5 --resume
```

### `terminal-bench/cancel-async-tasks`

- [x] The complete source verifier and all five semantic scenarios are mapped to independent evidence.
- [x] The Candidate contains only bounded regular `/app/run.py`; installed state and live processes are excluded.
- [x] The public Adapter contains task-scenario and signal-forwarding plumbing but no assertions or expected answers.
- [x] Every case receives a fresh event ledger, credential, process supervisor, Evaluation, and correlation IDs.
- [x] Missing/base Candidate behavior is rejected by the host Oracle without becoming infrastructure failure.
- [x] The reviewed reference passes concurrency, one-slot serialization, all cancellation positions, and queued-task cleanup.
- [x] Sequential, unbounded, signal-ignoring, timeout, and forged-verdict mutants fail.
- [x] A real closure-introspection credential-forgery exploit fails because Candidate code receives no helper credential.
- [x] Premature Candidate cancellation is distinguished from trusted signal forwarding and rejected.
- [x] Symlink, directory, and oversized Candidate shapes fail closed.
- [x] The full pinned-image Docker matrix passes and leaves no Candidate-controlled verdict path.
- [x] The cheap-model Agent smoke run completes without infrastructure error and its result provenance is recorded.
- [x] No SecureBench container, network, or volume survives the model-backed smoke run.
- [x] Linux implementation, fidelity, and deterministic qualification evidence are recorded in [`cancel-async-tasks.md`](TerminalBench/cancel-async-tasks.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Qualified on Linux on 2026-08-26. The API-key-backed
`gpt-5.6-luna` smoke passed with score `1.0`, no infrastructure error, Candidate
digest `sha256:fe2a8afa945641feeb1a5326af7b542cf489f3cf1395e7e0e006578ea649c5e7`,
and execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.
The hardened verification digest is
`sha256:b25489e66468575eaa3967c1429a6c72e81b91537757f72281e4e26f4b26236c`.
Closure credential exposure, signal-readiness nondeterminism, and interrupted
container cleanup races found during adversarial qualification were fixed and
covered by deterministic and live regression tests before approval.

For the sixth Terminal row, resume the first five results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 6 --resume
```

### `terminal-bench/chess-best-move`

- [x] The complete source verifier and its exact `strip().split()` semantics are mapped to host-only artifact scoring.
- [x] The Candidate contains only bounded regular `/app/move.txt`; the board image and live state are excluded.
- [x] No Adapter or Trusted Helper is needed, and Candidate content is never imported or executed.
- [x] The untouched pinned image fails Candidate capture and missing output is scored by the Oracle.
- [x] Both move orders and varied whitespace pass with the exact `e2e4`/`g2g4` multiset.
- [x] Missing, extra, duplicate, wrong, case-changed, and forged-verdict tokens fail.
- [x] Invalid UTF-8, symlink, directory, and oversized artifacts fail closed.
- [x] The reference passes stopped-Agent capture and host-only replay in the real pinned Linux image.
- [x] The cheap-model API smoke completes without infrastructure error and its incorrect move is rejected.
- [x] The one-row and full Terminal configuration audits pass without warnings.
- [x] Linux evidence, semantic fidelity, and result provenance are recorded in [`chess-best-move.md`](TerminalBench/chess-best-move.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux on 2026-08-26.
The pinned reference matrix passes `16/16`. The API-key-backed
`gpt-5.6-luna` smoke produced a semantically incorrect move and was correctly
rejected without infrastructure error. Execution digest:
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the seventh Terminal row, resume the first six results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 7 --resume
```

### `terminal-bench/circuit-fibsqrt`

- [x] The complete source verifier, 28 original cases, line bound, simulator semantics, and expected-value computation are mapped to independent evidence.
- [x] The Candidate contains only bounded regular `/app/gates.txt`; Candidate binaries, installed state, logs, and processes are excluded.
- [x] The public Adapter is assertion-free and contains no case corpus, Fibonacci implementation, expected value, threshold, or verdict logic.
- [x] The hardened simulator preserves valid gate/tick/output behavior while rejecting duplicate, malformed, negative, out-of-range, overlong, NUL-bearing, and executable-looking gate text.
- [x] Missing/base Candidate behavior is rejected by the host Oracle without becoming infrastructure failure.
- [x] The pinned upstream reference passes all 28 original and four run-seed-derived private cases in fresh Evaluations.
- [x] Constant-output, identity, and one-line reference-output-bit mutants fail.
- [x] Forged verdict text, repeated Evaluation IDs, invalid UTF-8, symlink, directory, oversized, and 32,000-line Candidate shapes fail or cannot affect scoring.
- [x] The upstream reference's failure at `N=0` and large 32-bit inputs is documented; private cases remain inside the original verifier's demonstrated positive-input/root-at-most-220 envelope.
- [x] The full pinned-image matrix passes `24/24`, including a real parser attack, and focused circuit/protocol/component/tester tests pass `98 passed, 8 skipped`.
- [x] The API-key-backed Luna smoke captures one bounded circuit and completes all 32 Evaluations without infrastructure error; its incorrect behavior is rejected.
- [x] No SecureBench container, network, volume, Evaluation root, or task-specific helper state survives qualification or the model smoke.
- [x] Linux evidence, semantic fidelity, and result provenance are recorded in [`circuit-fibsqrt.md`](TerminalBench/circuit-fibsqrt.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean protocol conversion qualified on Linux on 2026-08-27.
The official reference passes 32 fresh cases. The API-key-backed
`gpt-5.6-luna` smoke is correctly rejected with `incorrect_output`, score
`0.0`, and no infrastructure error. Candidate digest:
`sha256:8342730f90969df0de157383bdad78acc18442f744b80eddab2173c61c0413ae`.
Execution digest:
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the eighth Terminal row, resume the first seven results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 8 --resume
```

### `terminal-bench/cobol-modernization`

- [x] The complete COBOL program, source verifier, exact original three-step state transition, and expected bytes are mapped to independent evidence.
- [x] The Candidate contains only bounded regular `/app/program.py`; `.DAT` state, inputs, compiled files, installed packages, logs, and processes are excluded.
- [x] The public Adapter contains no users, books, balances, cases, expected bytes, assertions, scoring rules, or verdict logic.
- [x] Each host case runs in a fresh offline Evaluation; each bounded multi-step case safely replaces only the current input and stops Candidate descendants between invocations.
- [x] Accounts, books, and transactions are collected as bounded, correlated Output Artifacts only after Evaluation execution stops.
- [x] Missing/base Candidate behavior is rejected by the Oracle without becoming infrastructure failure.
- [x] The pinned upstream reference passes the exact source case and three run-seed-derived private valid-transaction cases.
- [x] No-op, published-fixed-output, forged-verdict, account-state, nonzero-exit, and repeated-Evaluation mutants fail or cannot affect scoring.
- [x] Candidate symlink, directory, oversized, input-path replacement, and Output Artifact symlink attacks fail closed.
- [x] The source verifier's single-sequence coverage and inability to prove implementation method from black-box outputs are documented as inherited limitations.
- [x] The final pinned-image matrix passes `19/19`; the complete suite passes `612 passed, 27 skipped`; full Terminal audits pass `33/33` without warnings.
- [x] The final API-key-backed Luna smoke captures one bounded `program.py`, passes all four fresh Evaluations with score `1.0`, and has no infrastructure error.
- [x] No SecureBench container, network, volume, Evaluation root, or task-specific helper state survives qualification or the model smoke.
- [x] Linux evidence, semantic fidelity, and result provenance are recorded in [`cobol-modernization.md`](TerminalBench/cobol-modernization.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean protocol conversion qualified on Linux on 2026-08-28.
The reference and final API-key-backed `gpt-5.6-luna` smoke both pass all four
fresh scenarios. The smoke Candidate digest is
`sha256:c98ee190eaff1a422afc3c096028ffafd88834bbacbe2eeef0baddf1401be5e5`;
verification digest
`sha256:fa87477d602589fcc6d8fd71205bcb915cd97b274b7d6f4d5f39c3289c61fcf8`;
execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the ninth Terminal row, resume the first eight results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 9 --resume
```

### `terminal-bench/code-from-image`

- [x] The complete prompt, public image, verifier entrypoint, and both source
  assertions were reconstructed; the prefix assertion is redundant with exact
  equality.
- [x] The Candidate contains only bounded regular `/app/output.txt`; image,
  implementation, installed state, logs, processes, and workspace state are
  excluded.
- [x] No Adapter, Output Artifact, Trusted Helper, or Candidate execution is
  required during verification.
- [x] Missing Candidate evidence is rejected by the host Oracle without an
  infrastructure error.
- [x] The exact reference and outer-whitespace variants pass the real bounded
  capture, store, parser, and Oracle path deterministically.
- [x] Prefix-only, wrong-nibble, case-changed, forged-verdict, structured-claim,
  NUL, and invalid-UTF-8 mutants fail.
- [x] Symlink, directory, oversized output, and unrelated-workspace-file cases
  prove the declared Candidate boundary fails closed or excludes undeclared
  state.
- [x] Exact content-addressed replay is deterministic; protocol Evaluation ID,
  credential, and case-state isolation are not applicable to this passive row.
- [x] The untouched digest-pinned image fails stopped Candidate capture on
  Linux/Docker.
- [x] The reference, prefix mutant, forged-verdict, and malicious file-shape
  matrix passes through real digest-pinned stopped-Agent capture on Linux.
- [x] One-row and complete Terminal audits plus the self-audit pass without
  warnings.
- [x] Final teardown inspection proves no Agent/Evaluation container, network,
  volume, credential, root, or task-specific temporary state survives.
- [x] An API-key-backed Luna Agent smoke is recorded after mandatory
  qualification; it passes with score `1.0` and no infrastructure error.
- [x] Deterministic evidence, semantic fidelity, and remaining work are
  recorded in [`code-from-image.md`](TerminalBench/code-from-image.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-08-31. The complete pinned-image matrix passes `20/20`; the Agent smoke
passes with Candidate digest
`sha256:3bcb1b46d8c7dfe114541e93c62c19adf62b601d43a252a6413a06539548eccc`
and no infrastructure error.

For the tenth Terminal row, resume the first nine results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 10 --resume
```

### `terminal-bench/count-dataset-tokens`

- [x] The complete prompt and verifier were reconstructed; the source checks
  substring containment rather than the prompt's requested bare-integer form.
- [x] The Candidate contains only bounded regular `/app/answer.txt`; datasets,
  tokenizer/model caches, scripts, logs, processes, and workspace state are
  excluded.
- [x] No Adapter, Output Artifact, Trusted Helper, or Candidate execution is
  required during verification.
- [x] Missing Candidate evidence is rejected by the host Oracle without an
  infrastructure error.
- [x] Bare, surrounding-text, embedded-digit, and valid-NUL forms containing
  `79586` pass the real deterministic capture, store, parser, and Oracle path,
  preserving the source predicate.
- [x] Off-by-one, transposed, comma-separated, space-separated, forged-verdict,
  structured-claim, and invalid-UTF-8 mutants fail.
- [x] Symlink, directory, oversized output, and unrelated cache-file cases
  prove the Candidate boundary fails closed or excludes undeclared state.
- [x] Exact content-addressed replay is deterministic; protocol Evaluation ID,
  credential, and case-state isolation are not applicable.
- [x] The untouched digest-pinned image fails stopped Candidate capture on
  Linux/Docker.
- [x] The reference, wrong-count, forged-claim, source-containment, and
  malicious file-shape matrix passes through real stopped-Agent capture.
- [x] One-row and complete Terminal audits plus the self-audit pass without
  warnings.
- [x] Final teardown inspection proves no Agent/Evaluation container, network,
  volume, credential, root, or task-specific temporary state survives.
- [x] Agent smoke evidence is recorded. The first attempt exposed a missing
  Hugging Face allowlist; after correcting the tester configuration, the
  infrastructure retry passes with score `1.0`.
- [x] Deterministic evidence, the prompt/verifier gap, semantic fidelity, and
  remaining work are recorded in
  [`count-dataset-tokens.md`](TerminalBench/count-dataset-tokens.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-08-31. The complete pinned-image matrix passes `22/22`; the corrected
API-key-backed Luna retry passes with Candidate digest
`sha256:918b025acea05118b642f076363ce95f0c05b72ed31bfd15b8b6088012b2df59`
and no infrastructure error.

For the eleventh Terminal row, resume the first ten results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 11 --resume
```

### `terminal-bench/crack-7z-hash`

- [x] The complete prompt, public archive identity, verifier entrypoint, and
  exact `strip()` comparison were reconstructed.
- [x] The Candidate contains only bounded regular `/app/solution.txt`; archive,
  extracted data, John build, logs, caches, processes, and workspace state are
  excluded.
- [x] No Adapter, Output Artifact, Trusted Helper, or Candidate execution is
  required during verification.
- [x] Missing Candidate evidence is rejected by the host Oracle without an
  infrastructure error.
- [x] Exact plaintext and outer-whitespace variants pass the real deterministic
  capture, store, parser, and Oracle path.
- [x] Truncated, extended, case-changed, space-inserted, extra-text,
  forged-verdict, structured-claim, NUL, and invalid-UTF-8 mutants fail.
- [x] Symlink, directory, oversized output, and undeclared extracted/log-file
  cases prove the Candidate boundary fails closed or excludes unrelated state.
- [x] Exact content-addressed replay is deterministic; protocol Evaluation ID,
  credential, and case-state isolation are not applicable.
- [x] The untouched digest-pinned image fails stopped Candidate capture on
  Linux/Docker.
- [x] Reference, semantic-mutant, forged-claim, whitespace, and malicious
  file-shape cases pass through real stopped-Agent capture.
- [x] One-row and complete Terminal audits plus the self-audit pass without
  warnings.
- [x] Final teardown inspection proves no Agent/Evaluation container, network,
  volume, credential, root, or task-specific temporary state survives.
- [x] The API-key-backed Luna smoke completes without infrastructure error;
  its missing Candidate is rejected through Oracle-owned Candidate-error
  handling.
- [x] Deterministic evidence, semantic fidelity, and remaining work are
  recorded in [`crack-7z-hash.md`](TerminalBench/crack-7z-hash.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-08-31. The complete pinned-image matrix passes `23/23`; the Luna smoke is
correctly rejected for `candidate_capture_rejected` with no infrastructure
error, and teardown is clean.

For the twelfth Terminal row, resume the first eleven results and confirm the
selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 12 --resume
```

### `terminal-bench/db-wal-recovery`

- [x] The complete prompt, source verifier, checked-in database/WAL identity,
  XOR recovery, and every scoring-relevant assertion were reconstructed.
- [x] The Candidate contains only bounded regular `/app/recovered.json`;
  databases, WAL/SQLite sidecars, scripts, logs, caches, processes, and
  workspace state are excluded.
- [x] No Adapter, Output Artifact, Trusted Helper, or Candidate execution is
  required during verification.
- [x] Missing Candidate evidence and a five-row base-only recovery are rejected
  by the host Oracle without an infrastructure error.
- [x] The reviewed 11-row reference passes the real deterministic capture,
  content store, strict JSON parser, and Oracle path.
- [x] Ordering, duplicate/missing-ID, stale-WAL-value, wrong-name, wrong-type,
  and missing-field mutants fail.
- [x] The source's unchecked fields, extra keys, and Python boolean-as-integer
  quirk remain accepted and are explicitly documented.
- [x] Forged verdict objects, malformed and ambiguous JSON, duplicate keys,
  invalid UTF-8, and NUL suffixes fail.
- [x] Symlink, directory, oversized output, and unrelated database/WAL/log-file
  cases prove the Candidate boundary fails closed or excludes undeclared state.
- [x] Exact content-addressed replay is deterministic; protocol Evaluation ID,
  credential, and case-state isolation are not applicable.
- [x] The untouched digest-pinned image fails stopped Candidate capture on
  Linux/Docker.
- [x] Reference, base-only, stale-update, forged-claim, and malicious file-shape
  cases pass through real stopped-Agent capture.
- [x] One-row and complete Terminal audits plus the self-audit pass without
  warnings.
- [x] Final teardown inspection proves no Agent/Evaluation container, network,
  volume, credential, root, or task-specific temporary state survives.
- [x] The API-key-backed Luna smoke completes without infrastructure error;
  its missing Candidate is rejected through Oracle-owned Candidate-error
  handling.
- [x] Deterministic evidence, semantic fidelity, inherited verifier gaps, and
  remaining work are recorded in
  [`db-wal-recovery.md`](TerminalBench/db-wal-recovery.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-08-31. The complete pinned-image matrix passes `31/31`; the Luna smoke is
correctly rejected for `candidate_capture_rejected` with no infrastructure
error, and teardown is clean.

For the thirteenth Terminal row, resume the first twelve results and confirm
the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 13 --resume
```

### `terminal-bench/distribution-search`

- [x] The complete prompt, source verifier, NumPy reference behavior, and every
  scoring-relevant shape, validity, normalization, and KL assertion were
  reconstructed.
- [x] The Candidate contains only bounded regular `/app/dist.npy`; scripts,
  packages, optimizer state, notebooks, logs, caches, processes, and workspace
  state are excluded.
- [x] A reusable bounded NPY float-summary parser was contracted, registered,
  adversarially tested, and kept free of row expectations and thresholds.
- [x] No Adapter, Output Artifact, Trusted Helper, or Candidate execution is
  required during verification.
- [x] Missing Candidate evidence is rejected by the host Oracle without an
  infrastructure error.
- [x] Independently solved float32 and float64 references pass the real capture,
  store, parser, and Oracle path and agree with direct NumPy calculations.
- [x] Uniform, forward-only, backward-only, wrong-count, two-dimensional,
  nonpositive, nonfinite, above-one, and normalization mutants fail.
- [x] The source's strict normalization boundary is exercised with passing
  just-inside and failing just-outside candidates.
- [x] Forged verdicts, malformed/truncated/trailing NPY, duplicate header keys,
  object/pickle dtypes, code-like header expressions, shape bombs, unsupported
  dtypes/versions, symlinks, directories, and oversize output fail closed.
- [x] Exact content-addressed replay is deterministic; protocol Evaluation ID,
  credential, and case-state isolation are not applicable.
- [x] Parser/capture rejection remains Candidate failure; Adapter and Helper
  failure classes are not applicable.
- [x] Parser, focused regression, and full warning-strict suites pass.
- [x] The untouched digest-pinned image fails stopped Candidate capture on
  Linux/Docker.
- [x] Float32/float64 reference, semantic-mutant, forged-claim, and malicious
  file-shape cases pass through real stopped-Agent capture.
- [x] One-row and complete Terminal audits plus the self-audit pass without
  warnings.
- [x] Final teardown proves no Agent/Evaluation container, network, volume,
  credential, root, or task-specific temporary state survives.
- [x] The API-key-backed Luna smoke produces one bounded Candidate and is
  correctly rejected for `forward_kl_out_of_tolerance` with no infrastructure
  error.
- [x] Deterministic evidence, parser trust contract, semantic fidelity, and
  remaining work are recorded in
  [`distribution-search.md`](TerminalBench/distribution-search.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-08-31. The complete pinned-image matrix passes `30/30`; the Luna smoke
Candidate digest is
`sha256:ffa5ffe7a82a4f252be99b163d71a46f386abcb985c741f2d05ea322770f21a6`
and is correctly rejected for `forward_kl_out_of_tolerance` with no
infrastructure error. The full warning-strict suite passes `728 passed, 51
skipped`; both complete audits pass `53/53` without warnings.

For the fourteenth Terminal row, resume the first thirteen results and confirm
the selected task ID, or derive a one-row temporary tasks file for an isolated
rerun:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 14 --resume
```

### `terminal-bench/dna-assembly`

- [x] The complete prompt, public sequence fixture, verifier entrypoint,
  BsaI parsing offsets, annealing/Tm logic, junction constraints, and circular
  assembly assertion were reconstructed.
- [x] The Candidate contains only bounded regular `/app/primers.fasta`;
  sequence inputs, scripts, installed Primer3, logs, caches, processes, and
  workspace state are excluded.
- [x] The public sequence asset, source image fixture, and host Oracle fixture
  are byte-identical and pinned by size and SHA-256.
- [x] The mutable source `oligotm` subprocess was replaced by a bounded
  pure-Python host Oracle utility fixed to the public flags and conformance-
  tested against Primer3 2.6.1.
- [x] No Adapter, Output Artifact, Trusted Helper, or Candidate execution is
  required during verification.
- [x] Missing Candidate evidence is rejected by the host Oracle without an
  infrastructure error.
- [x] The reviewed eight-primer reference passes real stopped capture, store,
  UTF-8 parser, Oracle, original fragment semantics, and exact replay.
- [x] Missing site/clamp, incomplete primer, missing/short binding, Tm range and
  pair-difference, junction mismatch/duplication, and wrong-assembly mutants
  fail with the intended categories.
- [x] Forged verdict/header claims, malformed lines, non-DNA/NUL/invalid-UTF-8
  text, symlink, directory, oversize, and unrelated-workspace changes fail
  closed or remain outside the Candidate.
- [x] The untouched digest-pinned image fails stopped Candidate capture on
  Linux/Docker.
- [x] Reference, missing-site, forged-verdict, wrong-assembly, missing,
  symlink, directory, and oversized cases pass through the real pinned Linux
  capture path.
- [x] Complete Terminal and self-audits pass `57/57`; the unchanged DeepSWE
  audit passes `13/13`, all without warnings.
- [x] Final teardown proves no Agent/Evaluation container, task image, network,
  volume, credential, root, or task-specific helper state survives.
- [x] The isolated API-key-backed Luna smoke captures one bounded Candidate
  and is correctly rejected for `missing_bsai_site` with no infrastructure
  error.
- [x] Deterministic evidence, utility trust contract, semantic fidelity, and
  inherited source limitations are recorded in
  [`dna-assembly.md`](TerminalBench/dna-assembly.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. The focused deterministic suite passes `45 passed, 5 skipped`; the
pinned-image row matrix passes `35/35`. The Luna Candidate digest is
`sha256:149b00f41ee30bfb571dd2827e9c429b3c1101f7182cdb1dbc0822a585f36ede`
and its semantic rejection has no infrastructure error. Complete Terminal and
self-audits pass `57/57` without warnings.

For the fifteenth Terminal row, resume the first fourteen results and confirm
the selected task ID, or derive a one-row temporary tasks file for an isolated
rerun:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 15 --resume
```

### `terminal-bench/dna-insert`

- [x] The complete prompt, public input/output fixture, source verifier,
  positional primer concatenation, insertion, overlap, annealing, and Tm
  predicates were reconstructed.
- [x] The Candidate contains only bounded regular `/app/primers.fasta`;
  sequence inputs, scripts, Primer3, logs, caches, processes, and workspace
  state are excluded.
- [x] The public and host Oracle sequence fixtures are byte-identical and
  pinned by size and SHA-256.
- [x] The Oracle derives the source insertion context from the immutable
  input/output pair and resolves the repeated-junction ambiguity at the exact
  source boundary.
- [x] The approved bounded Primer3-compatible Oracle utility is reused with no
  new framework component or executable dependency.
- [x] No Adapter, Output Artifact, Trusted Helper, or Candidate execution is
  required during verification.
- [x] Missing Candidate evidence is rejected by the host Oracle without an
  infrastructure error.
- [x] References with the insertion wholly in the forward primer and split
  across both primers pass capture, store, parser, Oracle, original source
  semantics, and replay.
- [x] The source's ignored-header, case-folding, trailing-whitespace, and
  universal-newline behavior is preserved without trusting header claims.
- [x] Missing insertion, short annealing, incorrect overlap, forward/reverse
  Tm range, and pair-difference mutants fail with the intended categories.
- [x] Forged verdicts, malformed lines, non-DNA/NUL sequences, invalid UTF-8,
  symlink, directory, oversize, and unrelated-workspace changes fail closed or
  remain outside the Candidate.
- [x] The untouched digest-pinned image fails stopped Candidate capture on
  Linux/Docker.
- [x] Reference, missing-insert, forged-verdict, pair-Tm, missing, symlink,
  directory, and oversized cases pass through the real pinned Linux path.
- [x] Complete Terminal and self-audits pass `61/61`; the unchanged DeepSWE
  audit passes `13/13`, all without warnings.
- [x] Final teardown proves no Agent/Evaluation container, task image, network,
  volume, credential, root, or task-specific state survives.
- [x] The isolated API-key-backed Luna smoke completes without infrastructure
  error; its missing Candidate is rejected through Oracle-owned Candidate-
  error handling.
- [x] Deterministic evidence, source quirks, semantic fidelity, and inherited
  limitations are recorded in
  [`dna-insert.md`](TerminalBench/dna-insert.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. The focused deterministic suite passes `28 passed, 5 skipped`; the
pinned-image row matrix passes `33/33`. The Luna smoke is correctly rejected
for `candidate_capture_rejected` with no infrastructure error. Complete
Terminal and self-audits pass `61/61` without warnings; the full suite passes
`801 passed, 61 skipped`.

For the sixteenth Terminal row, derive a one-row temporary tasks file for an
isolated rerun, or resume a result set that already contains the first fifteen
rows and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 16 --resume
```

### `terminal-bench/extract-elf`

- [x] The complete prompt, source verifier, generated C case, JavaScript
  reference, section-selection order, word decoding, known-value rule, and 75%
  coverage threshold were reconstructed.
- [x] The Candidate contains only bounded regular `/app/extract.js`; ELF
  inputs, output JSON, compiled files, scripts, caches, logs, processes, and
  workspace state are excluded.
- [x] The public Adapter releases only the current bounded ELF, invokes Node,
  drains bounded stdout/stderr, stops the process group, and contains no case,
  parser, expected mapping, threshold, assertion, score, or verdict.
- [x] Four pinned host-only ELF64 LSB cases and their C provenance are checked
  by size/SHA-256 and never mounted as a corpus into either VM.
- [x] The pure host Oracle independently parses the ELF section table and
  derives scored words without executing Candidate or reference code.
- [x] Challenge digest/index/check correlation and distinct Evaluation IDs are
  revalidated; every protocol case reconstructs the exact Candidate in a fresh
  Evaluation.
- [x] Missing/base Candidate behavior is rejected by the Oracle without
  becoming an infrastructure error.
- [x] The exact source JavaScript reference passes all four cases and exact
  Candidate replay through real digest-pinned Evaluations.
- [x] Half-coverage and wrong-known-word mutants fail; the exact 75% boundary
  and ignored unknown-key source behavior remain accepted.
- [x] String/non-integer values, malformed JSON, forged verdicts, corrupted
  correlation, repeated Evaluation IDs, and a bounded stdout-flood attack fail
  or cannot affect scoring.
- [x] Symlink, directory, oversized, and missing Candidate shapes fail closed
  through the compact shared `file_bundle` matrix.
- [x] The final pinned Linux matrix passes `20/20`; the sole skip is a
  redundant host-Node conformance check covered by the real reference run.
- [x] The complete warning-strict suite passes `815 passed, 68 skipped`;
  Terminal and self audits pass `65/65`, and DeepSWE passes `13/13`, without
  warnings.
- [x] Final teardown proves no SecureBench container, network, volume,
  Agent/Evaluation process, or row-specific process survives, and the task
  image is pruned.
- [x] The final isolated API-key-backed Luna smoke uses `reasoning_effort:
  none`, captures one bounded Candidate, and passes all four fresh cases with
  no infrastructure error.
- [x] Deterministic evidence, visibility, bounds, source quirks, semantic
  fidelity, and result provenance are recorded in
  [`extract-elf.md`](TerminalBench/extract-elf.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean black-box conversion qualified on Linux x86_64 on
2026-09-01. Candidate digest
`sha256:41df9448610504eab67d1a937b6d2fd1c6e661438f3dc2dfb4f29f3108935b18`
passes four fresh Evaluations with score `1.0`; verification digest
`sha256:46e26f225db07fcad43171efa789c82660f6828957373075ebb6985f40e42dc6`,
execution digest
`sha256:5d1cfeb94862145b23bf2a40d4fa5769583cffd2b6293808f81cc4ea84d7a3aa`.

For the seventeenth Terminal row, derive a one-row temporary tasks file for an
isolated rerun, or resume a result set containing the first sixteen rows and
confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 17 --resume
```

### `terminal-bench/extract-moves-from-video`

- [x] The complete prompt, source verifier, expected transcript, text-mode
  newline behavior, Levenshtein recurrence, normalization denominator, and
  inclusive 90% threshold were reconstructed.
- [x] The Candidate contains only bounded regular `/app/solution.txt`;
  downloaded video, OCR/transcription code, packages, caches, logs, processes,
  connections, and other workspace state are excluded.
- [x] The host transcript is exactly 1,346 bytes/characters, 280 lines, and is
  byte-pinned to the source verifier's `SOLUTION` by SHA-256.
- [x] No Adapter, Trusted Helper, Output Artifact, or Candidate execution is
  needed during verification; the host Oracle alone owns expected text,
  threshold, scoring, and verdict.
- [x] Strict UTF-8 parsing and an exact 16 KiB file bound keep passive parsing
  finite without excluding a plausible transcript.
- [x] Missing/base Candidate behavior is rejected by the Oracle without
  becoming an infrastructure error.
- [x] Exact, CRLF, 149-character append, 134-character deletion, and small NUL
  variants accepted by the source pass the real artifact path.
- [x] The adjacent 150-character append and 135-character deletion fail,
  proving both sides of the exact source threshold.
- [x] Lost line breaks, changed case, reordered moves, empty text, invalid
  UTF-8, and forged verdict text fail or cannot affect scoring.
- [x] Exact Candidate replay is stable; unrelated video bytes are excluded
  from the stored Candidate.
- [x] Symlink, directory, oversized, and missing Candidate shapes fail closed
  through the compact shared `file_bundle` matrix.
- [x] The pinned Linux row matrix passes `37/37`; the complete warning-strict
  suite passes `845 passed, 75 skipped`.
- [x] Terminal and self audits pass `69/69`; DeepSWE remains `13/13`; the
  isolated one-row audit passes `5/5`, all without warnings.
- [x] The Linux tester includes the YouTube, Google Video, and image domains
  required by the public task, matching the production Codex tester policy.
- [x] Final teardown proves no SecureBench container, network, volume, Agent,
  downloader, or row-specific process survives, and the task image is pruned.
- [x] The isolated API-key-backed Luna smoke uses `reasoning_effort: none` and
  completes without infrastructure error; its missing Candidate is correctly
  rejected through Oracle-owned Candidate-error handling.
- [x] Deterministic evidence, source-metric limitations, semantic fidelity,
  and result provenance are recorded in
  [`extract-moves-from-video.md`](TerminalBench/extract-moves-from-video.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. The Luna smoke is correctly rejected for
`candidate_capture_rejected` with no infrastructure error or Candidate digest;
row digest
`sha256:e305443dcf2ec5ed9cc5b6dd540c78828034bf374e7ac0252885652bf752c9ae`,
verification digest
`sha256:f4d8439bb6e77f274cb6d53d51e49ab2dd9265fe09298bdf940bb073ed4c0583`,
execution digest
`sha256:d76fbf3a86c6007492e78df23761b40be47573214126b2eb7c53bf4464379c24`.

### `terminal-bench/feal-differential-cryptanalysis`

- [x] The complete prompt and adaptive chosen-plaintext attack contract were
  reconstructed during portfolio review.
- [x] A faithful conversion requires a reusable supervisor-owned stateful
  bidirectional Oracle channel that is not currently implemented.
- [x] Fixed-query batching was rejected because it is not semantically
  equivalent to the source's adaptive interaction.
- [x] The row therefore has no executable v2 task, Candidate, live run, or
  qualification claim under the present framework.
- [x] The exclusion rationale and reconsideration condition are recorded in
  [`feal-differential-cryptanalysis.md`](TerminalBench/feal-differential-cryptanalysis.md).

Final status: [ ] Approved  [x] Excluded

Evidence/reason: Exclusion was manually approved after feasibility re-audit.
Reconsider only after a bounded adaptive host-to-Evaluation Oracle primitive is
implemented and qualified.

For the eighteenth executable Terminal row, derive a one-row temporary tasks
file for an isolated rerun, or resume a result set containing the first
seventeen executable rows and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 18 --resume
```

### `terminal-bench/feal-linear-cryptanalysis`

- [x] The complete prompt, image build, deterministic public inputs, source
  verifier, expected corpus, text-mode read, and 100 independent substring
  assertions were reconstructed.
- [x] The Candidate contains only bounded regular `/app/plaintexts.txt`;
  attack code, compiled tools, packages, logs, caches, processes, connections,
  and other workspace state are excluded.
- [x] The host corpus contains the exact 100 ordered, unique ASCII decimal
  strings from `soln.split()`, in a 2,047-byte canonical file pinned by
  SHA-256.
- [x] No Adapter, Trusted Helper, Output Artifact, or Candidate execution is
  needed; the host Oracle alone owns expected values, assertions, scoring, and
  verdict.
- [x] Strict UTF-8 parsing and a 16 KiB Candidate/artifact bound keep passive
  hostile input finite without excluding a plausible answer.
- [x] The untouched base image and a missing Candidate fail closed without an
  infrastructure error.
- [x] Canonical lines, delimiter-free concatenation, reversed comma-separated
  values, extra/NUL text, and duplicates pass both the source predicate and the
  real artifact path.
- [x] Missing-one, changed-one, hexadecimal, empty, invalid-UTF-8, and forged
  verdict Candidates fail or cannot affect scoring.
- [x] Exact Candidate replay is stable, and unrelated `attack.py` content is
  absent from the stored Candidate.
- [x] Symlink, directory, oversized, and missing Candidate shapes fail closed
  through the compact shared `file_bundle` matrix.
- [x] The pinned Linux row matrix passes `26/26`; the complete warning-strict
  suite passes `864 passed, 82 skipped`.
- [x] Terminal and self audits pass `73/73`; DeepSWE remains `13/13`; the
  isolated one-row audit passes `5/5`, all without warnings.
- [x] The pinned image is Linux/amd64; public `pairs.txt` and
  `ciphertexts.txt` are deterministic, and the declared digest is used for
  capture qualification and the live run.
- [x] Harness teardown prunes the task image and leaves no row container,
  network, volume, Agent, or task-specific process.
- [x] The isolated API-key-backed Luna smoke uses `reasoning_effort: none`,
  completes without infrastructure error, and correctly rejects its missing
  Candidate through Oracle-owned Candidate-error handling.
- [x] Deterministic evidence, inherited verifier weaknesses, semantic
  fidelity, and result provenance are recorded in
  [`feal-linear-cryptanalysis.md`](TerminalBench/feal-linear-cryptanalysis.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. The Luna smoke is correctly rejected for
`candidate_capture_rejected` with no infrastructure error or Candidate digest;
row digest
`sha256:6dcf862d1898be6220a1e29b0253dcd2e29f90f1a6acc699b1b9b09a26f21abf`,
verification digest
`sha256:a8dd4b8f1ebf03ca0f4504ef63bb120e54d6397829d77c185cebfe9e703809f3`,
execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

### `terminal-bench/filter-js-from-html`

- [x] The portfolio review reconstructed the dynamic Chromium alert check and
  clean-HTML byte-preservation requirement.
- [x] Running Candidate-filtered hostile HTML on the host would violate the
  Oracle trust boundary; an Evaluation browser result would remain an
  untrusted observation rather than a verdict.
- [x] Static inspection cannot faithfully replace browser execution, and a
  safe non-executing XSS specification would materially change the benchmark.
- [x] The row therefore has no executable v2 task, Candidate, live run, or
  qualification claim under the current framework.
- [x] The rationale is recorded in
  [`filter-js-from-html.md`](TerminalBench/filter-js-from-html.md).

Final status: [ ] Approved  [x] Excluded

Evidence/reason: Retain the authoritative portfolio Exclusion until a safe,
trusted browser-evidence design exists or the task receives a materially
different static security specification.

For the nineteenth executable Terminal row, derive a one-row temporary tasks
file for an isolated rerun, or resume a result set containing the first
eighteen executable rows and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 19 --resume
```

### `terminal-bench/financial-document-processor`

- [x] The complete prompt, randomized-name image build, all 17 public document
  identities, seven source tests, expected placement sets, amount table,
  newline/CSV behavior, and float tolerance were reconstructed.
- [x] The Candidate contains only bounded stopped directory trees for
  `/app/invoices`, `/app/other`, and `/app/documents`; OCR code, packages,
  caches, logs, processes, connections, and unrelated workspace files are
  excluded.
- [x] The approved generic `source.subpath` capability selects one bounded
  regular file inside a directory-tree Candidate only after validating the
  entire stored tree and all blobs under Candidate limits.
- [x] Schema and runtime tests reject absolute/traversing/non-canonical
  subpaths, wrong parent entries, tree limits, missing files, directories,
  symlinks, oversized files, and corrupted blob state.
- [x] The host expected corpus is pinned at 4,426 bytes and maps all source
  SHA-512 identities to the exact content-addressed SHA-256 blobs, values, and
  totals.
- [x] No Adapter, Trusted Helper, Output Artifact, Evaluation VM, or Candidate
  execution is needed; the host Oracle alone owns labels, expected values,
  assertions, scoring, and verdict.
- [x] The untouched image and missing output roots fail stopped Candidate
  capture without becoming infrastructure errors.
- [x] The exact reference state and source-accepted duplicate hashes, ignored
  invoice JSON, nested files, reordered CRLF rows, and 11 duplicate total rows
  pass the real passive path.
- [x] Misplacement, modified bytes, a non-empty source directory, header/count,
  amount/VAT, unknown-file, invalid-UTF-8, missing/wrong-type summary, and
  forged/path-traversal mutants fail or cannot affect scoring.
- [x] The source `< 0.01` numeric test is reproduced with Python floats,
  including adjacent tolerance cases; pandas 2.3.2's exact default NA tokens
  map to zero for VAT, as in the source verifier, and those tokens are rejected
  as filenames because pandas does not preserve them as strings.
- [x] Exact Candidate replay is stable, while root symlink, wrong root type,
  oversized tree, and missing Candidate attacks fail through the compact
  shared directory-capable `file_bundle` matrix.
- [x] Generic selector qualification passes `93/93`; the pinned Linux row
  matrix passes `43/43`; the complete warning-strict suite passes
  `912 passed, 88 skipped`.
- [x] The original source verifier passes all seven tests against the
  reconstructed reference state with its exact pytest 8.4.1 and pandas 2.3.2
  dependencies.
- [x] Terminal and self audits pass `77/77`; DeepSWE remains `13/13`; the
  isolated one-row audit passes `5/5`, all without warnings.
- [x] The pinned Linux/amd64 image digest is used for reference, base, mutant,
  and live qualification; the 17 public files total 4,002,650 bytes.
- [x] The final API-key-backed Luna smoke uses `reasoning_effort: none`,
  captures all three bounded directory entries, reaches all four passive
  artifacts without infrastructure error, and is correctly rejected for
  `incorrect_invoice_placement`.
- [x] Harness teardown prunes the task image and leaves no row container,
  network, volume, Agent, or task-specific process.
- [x] Security hardening and inherited verifier weaknesses are recorded in
  [`financial-document-processor.md`](TerminalBench/financial-document-processor.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. Final Luna Candidate digest
`sha256:26f4299278984e7b939f6501ad2704ced802cbc3f94fc1fda4cfe4451834ca7e`
is correctly rejected for `incorrect_invoice_placement` with no infrastructure
error; row digest
`sha256:de20210d04995b59aeb19075907a558edd14882b032bc71da405f624c62414d8`,
verification digest
`sha256:8c62a870d62219dc5da5ff38aacc3a690ad953d77c61460190e405a173eaf745`,
execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the twentieth executable Terminal row, derive a one-row temporary tasks
file for an isolated rerun, or resume a result set containing the first
nineteen executable rows and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 20 --resume
```

### `terminal-bench/fix-code-vulnerability`

- [x] The complete prompt, image mutation, six added source tests, 367 upstream
  Bottle regressions, report aggregation, and `_hkey`/`_hval` behavior were
  reconstructed.
- [x] The Candidate contains only bounded stopped `/app/bottle.py` and
  `/app/report.jsonl` regular files; repository metadata, tests, packages,
  processes, connections, and unrelated workspace state are excluded.
- [x] The pinned vulnerable and reference files are 175,565 bytes with reviewed
  SHA-256 identities, and the protected non-target source digest is pinned.
- [x] Passive verification accepts edits only inside the exact indented
  `_hkey`/`_hval` bodies and independently reproduces the source JSONL report
  semantics without importing Candidate code on the host.
- [x] The public assertion-free Adapter exposes only a closed bounded call
  surface and returns load, result-type/value, exception-type, and genuine
  pre-import built-in `ValueError` identity observations; it contains no
  expected answers or verdict logic.
- [x] Five host-selected cases cover all 21 direct source calls, 24 direct
  control guards, 96 `HeaderDict` calls, 72 `BaseResponse` calls, and 24
  deterministic run-seeded unseen normalizations in fresh Evaluation VMs.
- [x] The untouched vulnerable source with a correct report fails, while the
  exact upstream reference passes all five cases and exact Candidate replay.
- [x] `_hkey`-only, wrong-exception, forged same-name `ValueError`,
  unrelated-edit, wrong-report, and malformed mutants fail through the real
  pinned artifact/protocol path.
- [x] Both Candidate files reject missing, symlink, directory, oversized, and
  invalid-UTF-8 forms; forged outcomes, load claims, Challenge correlation, and
  reused Evaluation IDs cannot score.
- [x] Focused deterministic qualification passes `29 passed, 11 skipped`; the
  consolidated pinned Linux matrix passes `40/40`; the source verifier passes
  `373/373` against the reconstructed reference.
- [x] The complete warning-strict suite passes `997 passed, 109 skipped`;
  Terminal and self audits pass `89/89`; DeepSWE passes `13/13`; and the
  isolated row audit passes `5/5`, all without warnings.
- [x] The final API-key-backed Luna smoke uses `reasoning_effort: none`,
  captures both bounded files, passes all five fresh protocol cases without
  infrastructure error, and is correctly rejected for an unrelated source edit
  and incorrect report.
- [x] Harness teardown prunes the task image and leaves no row container,
  Evaluation network, volume, Agent, or task-specific process.
- [x] Fidelity hardening and limitations are recorded in
  [`fix-code-vulnerability.md`](TerminalBench/fix-code-vulnerability.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean hybrid conversion qualified on Linux x86_64 on
2026-09-01. Final Luna Candidate digest
`sha256:e3d27c66c26a485b614a4b648bf8f3981b23ca0f3c9e443a6ddfbee9438a541e`
is correctly rejected with row digest
`sha256:813003970f82d0bb3e9fbcd5d74587e9b1dcd1c707543098d5b7073d7497f16e`,
verification digest
`sha256:75e4fa0daa1a13cea3c2e1d34b0bb881f48317fc0facd21ce2b0d9c71e1a204d`,
and execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the twenty-first executable Terminal row, derive a one-row temporary tasks
file for an isolated rerun, or resume a result set containing the first twenty
executable rows and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 21 --resume
```

### `terminal-bench/fix-git`

- [x] The complete prompt, setup script, detached lost commit, reflog, merge
  conflict, two source assertions, and binary edge-whitespace semantics were
  reconstructed.
- [x] The Agent starts in the original `/app/personal-site` repository, while a
  reviewed read-only public mount masks the image's separate gold-copy
  directory and exposes no expected bytes.
- [x] The stopped Candidate contains only the bounded `about.md` and
  `default.html` regular files; Git metadata, reflogs, branches, resources,
  processes, connections, and credentials are excluded.
- [x] Read-only sibling mounts under a nested `/app` workdir are supported and
  tested; writable sibling mounts fail closed.
- [x] All Agent harnesses provide exact-path Git `safe.directory` entries for
  the configured workdir and declared directory-tree Candidate roots, preserve
  existing bounded configuration, reject ambiguous forms, and never use the
  unsafe wildcard.
- [x] The host-only Oracle reproduces source `bytes.strip()` behavior with
  hidden reviewed SHA-256 identities; it imports or executes no Candidate code.
- [x] The untouched master files fail, while reflog recovery, merge-conflict
  resolution from the lost commit, stopped capture, and exact replay pass. The
  original source verifier's two assertions pass against the same reference.
- [x] Partial about-only/layout-only, changed content, forged claims,
  Unicode-whitespace, invalid-UTF-8, duplicate/uncorrelated evidence, missing,
  symlink, directory, and oversized Candidates fail or cannot affect scoring.
- [x] Focused warning-strict qualification passes `36 passed, 5 skipped`; the
  consolidated exact-image Linux matrix passes `41/41`.
- [x] The complete warning-strict suite passes `997 passed, 109 skipped`;
  Terminal and self audits pass `89/89`; DeepSWE passes `13/13`; and the
  isolated row audit passes `5/5`, all without warnings.
- [x] The API-key-backed Luna smoke uses `reasoning_effort: none`, captures
  both bounded unchanged files without infrastructure error, and is correctly
  rejected for `incorrect_about_file` and `incorrect_layout_file`.
- [x] Harness teardown prunes the task image and leaves no row container,
  network, volume, Agent, or task-specific process.
- [x] Fidelity hardening and limitations are recorded in
  [`fix-git.md`](TerminalBench/fix-git.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. Final Luna Candidate digest
`sha256:b5f2a8faf4305db55a89ccb0cf515152940faeb03803971746c761bed0ea61fd`
is correctly rejected with row digest
`sha256:fc5f40de7b8f75f77c7c0cb8e95311c27f5517a0c0c3ca183052daa16a47e2fb`,
verification digest
`sha256:04713fdb4c73bec9e1652ff69484a5bdaee18fc98689795893c643dcb54a48c4`,
and execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

### `terminal-bench/fix-ocaml-gc`

- [x] The complete prompt, source setup, bootstrap build, basic testsuite run,
  and marker-based source assertion were reconstructed.
- [x] The source image has no canonical Git baseline, so a bounded replayable
  `git_patch` cannot currently be derived.
- [x] Capturing the Candidate-controlled compiler/build tree or trusting its
  generated `tests.txt` marker would not provide independent evidence.
- [x] A faithful conversion requires a reusable bounded compiler/runtime
  scenario runner and host-owned cases for the basic-suite behaviors; that
  capability is not implemented and is too broad to disguise as a row adapter.
- [x] The exclusion and requirements for a future redesign are recorded in
  [`fix-ocaml-gc.md`](TerminalBench/fix-ocaml-gc.md).

Final status: [ ] Approved  [x] Excluded

Evidence/reason: No approved executable pattern in the current framework. No
v2 row or live Agent run was added; the previously approved feasibility
exclusion was reconfirmed against the current architecture on 2026-09-01.

For the twenty-second executable Terminal row, derive a one-row temporary tasks
file for an isolated rerun, or resume a result set containing the first
twenty-one executable rows and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 22 --resume
```

### `terminal-bench/gcode-to-text`

- [x] The complete prompt, public G-code, source entrypoint, existence check,
  exact expected text, and `Path.read_text().strip()` behavior were
  reconstructed.
- [x] The pinned 1,661,422-byte public input has its reviewed SHA-256 identity;
  no separate expected output or verifier fixture enters the Agent.
- [x] The stopped Candidate contains only bounded `/app/out.txt`; input,
  scripts, renderings, caches, processes, connections, and credentials are
  excluded.
- [x] The host-only Oracle reproduces universal-newline and Unicode `strip()`
  semantics and imports or executes no Candidate code.
- [x] The absent baseline output fails capture, while the reviewed reference
  passes both original assertions, stopped capture, host verification, and
  exact replay.
- [x] Wrong-case, internal-substitution, explanatory-prefix/suffix, empty,
  forged-verdict, invalid-UTF-8, duplicate/uncorrelated, missing, symlink,
  directory, and oversized Candidates fail or cannot affect scoring.
- [x] Focused warning-strict qualification passes `20 passed, 5 skipped`; the
  consolidated exact-image Linux matrix passes `25/25`.
- [x] The complete warning-strict suite passes `997 passed, 109 skipped`;
  Terminal and self audits pass `89/89`; DeepSWE passes `13/13`; and the
  isolated row audit passes `5/5`, all without warnings.
- [x] The API-key-backed Luna smoke uses `reasoning_effort: none`, captures one
  bounded ten-byte `SHAPE-BOX` output without infrastructure error, and is
  correctly rejected for `incorrect_decoded_text`.
- [x] Harness teardown prunes the task image and leaves no row container,
  network, volume, Agent, or task-specific process.
- [x] Fidelity and limitations are recorded in
  [`gcode-to-text.md`](TerminalBench/gcode-to-text.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. Final Luna Candidate digest
`sha256:23bbd89a0fa21af9532cbdcf44e081c6f30f41dc6dba823e3a0bf942e8eabf05`
is correctly rejected with row digest
`sha256:100452e8ddb6859566a635257062c2b87b2be715093ac6f653dbdee00dfa7a9c`,
verification digest
`sha256:d664720f4d09c313a79a5f07170ab79d973434ab4d6446200e73e967e5425d2f`,
and execution digest
`sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.

For the twenty-third executable Terminal row, derive a one-row temporary tasks
file for an isolated rerun, or resume a result set containing the first
twenty-two executable rows and confirm the selected task ID:

```bash
.venv/bin/securebench run --config benchmarks/terminal-bench/tester-linux.yaml --limit 23 --resume
```

### `terminal-bench/git-leak-recovery`

- [x] The complete prompt, setup script, unreachable commit/tree/blob,
  pseudo-ref and reflogs, all five source assertions, and visible-worktree
  checksum behavior were reconstructed.
- [x] The image is pinned by immutable Linux/amd64 digest; no hidden test,
  expected secret, assertion, or scoring rule enters the Agent.
- [x] The stopped Candidate contains only a repository tree bounded to 128
  entries/1 MiB and one 4 KiB regular `/app/secret.txt`; live Git processes,
  configuration, credentials, connections, and external object stores are not
  captured.
- [x] The stored-tree parser is generic and assertion-free. It replaces
  candidate configuration, disables replacement objects, rejects symlinks,
  alternates, HTTP alternates, grafts and common object directories, and bounds
  Git object counts/sizes, command time/output, and returned evidence.
- [x] Exact `safe.directory` entries support the nested `/app/repo` repository
  on Linux without wildcard trust; existing bounded environment configuration
  is preserved and malformed forms fail closed.
- [x] The host-only Oracle reproduces secret output normalization, scans loose
  and packed object observations, requires the legitimate reachable commit,
  and independently checks visible worktree identity.
- [x] The absent output fails capture. The reference recovers the unreachable
  blob, expires reflogs, removes the pseudo-ref, packs/prunes the repository,
  and passes stopped capture, host verification, and exact replay.
- [x] Dirty history, forged/wrong output, changed worktree, removed required
  history, hostile Git configuration, external alternates,
  duplicate/uncorrelated evidence, missing artifacts, and
  symlink/directory/oversized Candidates fail or cannot affect scoring.
- [x] Focused warning-strict qualification passes `27 passed, 4 skipped`; the
  consolidated exact-image Linux matrix passes `31/31`.
- [x] The complete warning-strict suite passes `1013 passed, 113 skipped`;
  Terminal and self audits pass `93/93`; DeepSWE passes `13/13`; and the
  isolated row audit passes `5/5`, all without warnings.
- [x] The API-key-backed Luna smoke uses `reasoning_effort: none`, captures the
  two bounded artifacts, and passes with score `1.0` and no infrastructure
  error. The Oracle, not the model or guest Git output, issues the verdict.
- [x] Harness teardown prunes the task image and leaves no row container,
  network, volume, Agent, helper, or task-specific process.
- [x] Fidelity and fail-closed limitations are recorded in
  [`git-leak-recovery.md`](TerminalBench/git-leak-recovery.md).

Final status: [x] Approved  [ ] Excluded

Evidence/reason: Clean passive conversion qualified on Linux x86_64 on
2026-09-01. Final Luna Candidate digest
`sha256:14f97dfa461a8050a829974f6d396e503133cf293f555192356ffc73f4d03177`
passes with row digest
`sha256:1e217f34a4aece03be196abd3363b14c024d1fcfa58ed9bd74127154cdb4590d`,
verification digest
`sha256:c003f49abb85926aa345fd064ebd3d1eb16690d1f11c43842caf9a9ad8efe260`,
and execution digest
`sha256:dd0a026795dfbd3532192bbc450eea876824072db56eee75bc04f3cfed12f59b`.

## DeepSWE

The tasks are ordered so these commands start exactly one new row at a time:

```bash
.venv/bin/securebench run --config benchmarks/deep-swe/tester-linux.yaml --limit 1
.venv/bin/securebench run --config benchmarks/deep-swe/tester-linux.yaml --limit 2 --resume
.venv/bin/securebench run --config benchmarks/deep-swe/tester-linux.yaml --limit 3 --resume
```

Use a new `--output-dir` when intentionally rerunning a completed row. Confirm
the task ID in each result rather than inferring it from command order.

### `deep-swe/cattrs-partial-structuring-recovery`

- [ ] The unmodified base commit fails the new behavior checks.
- [ ] The gold/reference patch passes through the real Python adapter.
- [ ] Targeted mutants for nested partial values, atomic collections,
  refinement, default factories, extra keys, and detailed validation fail.
- [ ] Attrs classes, dataclasses, TypedDicts, inheritance, `init=False`, exports,
  frozensets, and legacy error round-trips are exercised.
- [ ] Candidate attempts to forge an observation, import hidden Oracle code, or
  read another case are rejected or cannot affect the verdict.
- [ ] Every Challenge runs in a fresh Evaluation reconstructed from the same
  immutable base and captured patch.
- [ ] Patch path/size limits reject tests, framework paths, and oversized or
  malformed patches.
- [ ] No candidate process, filesystem state, mount, or network state survives
  between cases.
- [ ] Linux evidence and the execution digest are added to
  [`cattrs-partial-structuring-recovery.md`](DeepSWE/cattrs-partial-structuring-recovery.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

### `deep-swe/fd-deterministic-multi-key-sorting`

- [ ] The unmodified base commit fails the new behavior checks.
- [ ] The gold/reference patch builds and passes through the real Rust/CLI
  adapter.
- [ ] Targeted mutants for key precedence, deterministic path tie-breaks,
  reverse, grouping, case sensitivity, missing values, natural ordering,
  seeded/unseeded random order, type order, and post-sort limits fail.
- [ ] Invalid modifier combinations and incompatibility with exec, batch exec,
  and detailed listing fail closed with bounded observations.
- [ ] Duplicate basenames, folded-equal paths, leading zeros, symlinks, mixed
  entry kinds, optional timestamps, and multiple roots are exercised.
- [ ] The pinned Linux filesystem exposes distinct creation/birth times for the
  created-time case; otherwise the row is excluded or redesigned rather than
  accepting a path-tie fallback.
- [ ] Malicious argv, path, output-volume, and filesystem scenarios stay inside
  the adapter and observation bounds.
- [ ] Every Challenge uses a fresh Evaluation and no process, file, mount, or
  network state survives between cases.
- [ ] Linux evidence, filesystem capability notes, and the execution digest are
  added to
  [`fd-deterministic-multi-key-sorting.md`](DeepSWE/fd-deterministic-multi-key-sorting.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

### `deep-swe/updo-policy-alerting`

- [ ] The unmodified base commit fails the new behavior checks.
- [ ] The gold/reference patch passes through the real Go adapter and trusted
  HTTP recorder.
- [ ] Targeted mutants for failure/recovery thresholds, degraded/healthy
  transitions, SSL re-entry, counter resets, current snapshots, cooldown, and
  per-target configuration fail.
- [ ] Webhook bodies include required zero-valued fields and preserved custom
  headers; `EventNone` and suppressed decisions cause no request.
- [ ] Recovery/healthy delivery and cross-event non-recovery cooldown semantics
  are exercised at exact time boundaries.
- [ ] Forged credentials, wrong paths/tokens, undeclared network attempts,
  excessive requests, bodies, and headers are rejected closed.
- [ ] Helper credentials and request ledgers are fresh and correlated to the
  current check, Challenge, and Evaluation only.
- [ ] Every Challenge uses a fresh Evaluation; no candidate or Helper process,
  ledger, credential, mount, or network rule survives the case.
- [ ] Linux evidence and the execution digest are added to
  [`updo-policy-alerting.md`](DeepSWE/updo-policy-alerting.md).

Final status: [ ] Approved  [ ] Excluded

Evidence/reason: `___________________________________________________________`

## Final pack sign-off

- [ ] Every selected converted row has exactly one binary final status: Approved or
  Excluded. “Pending”, “partial”, and “works locally” are not final statuses.
- [ ] Every Approved row demonstrates base failure, reference success,
  targeted-mutant rejection, malicious-candidate rejection, isolation, cleanup,
  and documented semantic fidelity.
- [ ] Each dossier records the tested commit, pinned image digest, Linux host,
  command/date, result location, and execution digest.
- [ ] Public and runtime roots contain no expected answers, hidden cases,
  assertions, scoring rules, gold changes, credentials, or remaining corpus.
- [ ] Candidate-controlled claims and guest test output are retained only as
  bounded observations, never as verdicts.
- [ ] A final `git status --short` and Docker/container/network inspection show
  no unintended state leaks.

Reviewer/date: `_____________________________________________________________`
