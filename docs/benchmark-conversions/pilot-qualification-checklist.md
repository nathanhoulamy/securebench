# First-wave conversion qualification checklist

Use this checklist on the Linux host after checking out the exact conversion
commit. Tick a row only after its real pinned image has run end to end and its
dossier contains the resulting evidence. Deterministic unit tests are useful,
but they do not replace Linux/Docker qualification.

Inventory review disposition and runtime qualification are separate. The
first-wave control, `sqlite-db-truncate`, and `vulnerable-secret` sections
remain intentionally unchecked; the eleven incrementally qualified rows below
currently have binary admission decisions. Global preflight and final pack
sign-off therefore remain incomplete.

Test-layout status is separate from admission: all eleven incremental rows use
the compact shared `file_bundle` qualification proof. The migration preserved
all 149 combined cases across the shared matrix and the five newest focused
files; `dna-assembly` adds one declarative row record while retaining its
Primer3, semantic, parser, and replay evidence in its focused files.

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
- [x] Host, date, OS, kernel, and architecture are recorded: 2026-08-26 through
  2026-09-01, Linux `7.0.0-29-generic`, x86_64.
- [x] `docker version` succeeds and Docker uses Linux/amd64 containers
  (Docker `29.7.2`).
- [x] Free disk space is sufficient for the pinned benchmark images and run
  output.
- [ ] The environment is installed with `python -m pip install -e '.[dev]'`.
- [x] The full `.venv/bin/python -m pytest -q -W error` suite passes
  (`773 passed, 56 skipped`).
- [x] `.venv/bin/securebench audit-self --output-dir /tmp/securebench-audit-self`
  passes (`57/57`, no warnings).
- [x] `.venv/bin/securebench audit --config benchmarks/terminal-bench/tester-linux.yaml --output-dir /tmp/terminal-bench-v2-audit`
  passes with all fourteen selected rows (`57/57`, no warnings).
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
free at the 2026-08-31 qualification pass.

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
