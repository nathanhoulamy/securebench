# First-wave conversion qualification checklist

Use this checklist on the Linux host after checking out the exact conversion
commit. Tick a row only after its real pinned image has run end to end and its
dossier contains the resulting evidence. Deterministic unit tests are useful,
but they do not replace Linux/Docker qualification.

## Run identity and host preflight

- [ ] Branch is `split-verification-v2` and the tested commit SHA is recorded:
  `____________________________`.
- [ ] `git status --short` is clean before the run.
- [ ] Host, date, OS, kernel, and architecture are recorded: `________________`.
- [ ] `docker version` succeeds and Docker uses Linux containers.
- [ ] Free disk space is sufficient for the pinned benchmark images and run
  output.
- [ ] The environment is installed with `python -m pip install -e '.[dev]'`.
- [ ] `.venv/bin/pytest -q` passes.
- [ ] `.venv/bin/securebench audit-self --output-dir /tmp/securebench-audit-self`
  passes.
- [ ] `.venv/bin/securebench audit --config benchmarks/terminal-bench/tester-linux.yaml --output-dir /tmp/terminal-bench-v2-audit`
  passes with all three selected rows.
- [ ] `.venv/bin/securebench audit --config benchmarks/deep-swe/tester-linux.yaml --output-dir /tmp/deep-swe-v2-audit`
  passes with all three selected rows.
- [ ] `.venv/bin/securebench auth codex status` confirms that the isolated
  harness login is usable.
- [ ] Every task image resolves to the digest declared in its row; no mutable
  tag was substituted.

Record the audit artifacts and host notes here: `____________________________`.

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

- [ ] All five converted rows have exactly one binary final status: Approved or
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
