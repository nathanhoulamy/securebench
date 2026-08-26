# Guide for implementing the first v2 benchmark conversions

This is the working handoff for the next conversion agent. It turns the existing review dossiers
into executable SecureBench v2 rows without restoring hidden-test execution or family-specific
verifiers.

The immediate goal is a small pilot, not bulk conversion or admission-tool automation. Convert a
few representative rows, exercise each verification pattern, and let concrete row needs drive the
next reusable Adapter, parser, or Trusted Helper. Author and deterministically qualify changes
locally, then run the image-dependent and end-to-end checks on the available Linux machine.

## Read these sources first

Use the following order so that older conversion material is not mistaken for the current runtime
contract:

1. [`AGENTS.md`](../../AGENTS.md) — architectural invariants.
2. [`current.md`](../../current.md) — the implemented capability matrix and accepted deferred
   operational hardening.
3. [`docs/split-verification/schema.md`](../split-verification/schema.md) — author-facing v2 design.
4. [`docs/split-verification/security-model.md`](../split-verification/security-model.md) — trust
   boundary and current limitations.
5. [`securebench/schemas/benchmark.py`](../../securebench/schemas/benchmark.py) — executable schema
   source of truth.
6. [`securebench/execution_profiles.py`](../../securebench/execution_profiles.py) — what preflight
   actually permits.
7. [`docs/split-verification/examples/executable.yaml`](../split-verification/examples/executable.yaml)
   and the executable `constraints-scheduling` pack under
   [`benchmarks/terminal-bench/`](../../benchmarks/terminal-bench/) — smallest complete reference.
8. [`inventory.csv`](inventory.csv) and the selected row's dossier in this directory — reviewed
   source behavior, proposed boundary, fidelity decision, and mutation plan.
9. The original benchmark row, verifier entrypoint, every scoring assertion, base revision, and
   gold/reference change recorded by that dossier.

The pre-v2 `manifest.yaml`, `tasks.jsonl`, and hidden test runners under `benchmarks/` are conversion
inputs only. The v2 loader rejects their format, and their verifier scripts must not become a new
execution path.

## Non-negotiable conversion model

Every converted row must keep this sequence:

1. The Agent sees only the public prompt and public assets.
2. SecureBench stops the Agent environment and captures exactly one bounded, durable Candidate.
3. Every protocol Challenge reconstructs that Candidate from the immutable baseline in a fresh
   Evaluation.
4. A public, assertion-free Adapter exposes behavior and optionally uses scoped Trusted Helpers.
5. Bounded evidence returns to the host Oracle. Only the Oracle owns expectations, scoring, and the
   verdict.

There are only two schema check types:

| Review pattern | V2 shape |
|---|---|
| Passive artifact verification | `artifact` check |
| Black-box challenge/response | `protocol` check |
| Trusted external state | `protocol` check with `trusted_helpers` |
| Runtime-produced files | `protocol` check with `output_artifacts` |

Do not copy a dossier's pattern label mechanically. Some early dossiers call a transformation
"passive artifact verification" because the final bytes are parsed passively, even though producing
those bytes requires executing Candidate code. In v2 that is a `protocol` check with an Output
Artifact. A true `artifact` check never executes Candidate code during verification.

## Current capability boundary

The pilot may use:

- `terminal_task` with `file_bundle`;
- `repo_patch` with `git_patch`;
- passive JSON, UTF-8 text, ICS, strict CSV, and tree-manifest parsers;
- `securebench.adapter/v2` protocol checks;
- regular-file and directory-tree Output Artifacts;
- `securebench.http-request-recorder/v1` for bounded HTTP request evidence;
- `securebench.append-only-event-ledger/v1` for timestamped nonce/event evidence;
- `securebench.process-supervisor/v1` for host-owned launch, timing, and a
  bounded allowlisted signal schedule;
- `strict-split/v1` with a fresh Evaluation for every Challenge.

Do not use `filesystem_overlay` in the pilot. Its implementation remains source-gated until the
separate root-Linux native qualification is complete. Do not use `batched-split/v1`, writable
public assets, an unregistered parser/helper, or another Adapter format. When a selected row needs a
missing capability, implement a small reviewed vertical slice and make preflight accept it only
after its contract, bounds, failure ownership, adversarial tests, and real-Docker isolation test
exist.

Two operational risks are accepted for this supervised pilot: active `file_bundle` and `git_patch`
Agent workspaces have no framework-owned disk quota, and interrupted non-overlay capture can leave
unreferenced blobs. Their impact, later fixes, and pilot mitigations are recorded in
[`current.md`](../../current.md#accepted-deferred-operational-hardening). Start with one worker and
monitored, pilot-specific run storage.

## Recommended pilot rows and order

The selection deliberately starts with clean conversions and introduces complexity gradually.
`constraints-scheduling` is the already executable baseline and should be rerun before adding a new
row.

| Order | Row | Pattern and Candidate | Why select it | Expected new work |
|---:|---|---|---|---|
| 0 | `terminal-bench/constraints-scheduling` | Artifact; `file_bundle` | Known-good end-to-end control | None; rerun it on Linux |
| 1 | [`terminal-bench/sqlite-db-truncate`](TerminalBench/sqlite-db-truncate.md) | Artifact; `file_bundle` | Small JSON deliverable and existing strict JSON parser | Row, host Oracle, qualification cases |
| 2 | [`terminal-bench/vulnerable-secret`](TerminalBench/vulnerable-secret.md) | Artifact; `file_bundle` | Small UTF-8 deliverable with a different task shape | Row, host Oracle, malicious-artifact cases |
| 3 | [`deep-swe/cattrs-partial-structuring-recovery`](DeepSWE/cattrs-partial-structuring-recovery.md) | Protocol; `git_patch` | Clean Python black-box conversion | Reusable schema/action Adapter and Oracle |
| 4 | [`deep-swe/fd-deterministic-multi-key-sorting`](DeepSWE/fd-deterministic-multi-key-sorting.md) | Protocol; `git_patch` | Clean CLI/filesystem behavior in a different language | Reusable CLI/filesystem-scenario Adapter and Oracle |
| 5 | [`deep-swe/updo-policy-alerting`](DeepSWE/updo-policy-alerting.md) | Protocol plus HTTP recorder; `git_patch` | Exercises the implemented external-state path | Policy Adapter, recorder settings, correlated Oracle |
| 6 | [`deep-swe/bandit-incremental-cache-control`](DeepSWE/bandit-incremental-cache-control.md) | Protocol plus a witness service; `git_patch` | A second external-state row that tests whether the helper model generalizes | New narrowly scoped Trusted Helper; do only after row 5 |

Rows 1–5 are the first wave. Row 6 is the second trusted-state example: it is intentionally selected
to drive a real missing component, but it must remain non-executable until the witness Helper is
specified, registered, implemented, and qualified. Do not disguise that witness as Candidate
output or overload the HTTP recorder beyond its registered static-response/request-ledger contract.

If one selected image or upstream snapshot is unavailable, replace the row with another
**Approved — Clean conversion** of the same pattern from `inventory.csv`. Record the reason; do not
quietly switch to an excluded, major-redesign, or semantically weaker row.

## Pack layout

Keep manifest source roots disjoint and let placement determine visibility. A typical converted
pack should look like:

```text
benchmarks/<benchmark>/
  manifest-v2.yaml
  tasks-v2.jsonl
  tester-linux.yaml
  <public-root>/
    <task-id>/...
  v2/evaluation_inputs/
    <task-id>/adapter/
      adapter.yaml
      adapter implementation
  v2/hidden/
    <task-id>/
      oracle/
        oracle.yaml
        oracle implementation
      cases/                  # optional static host cases
      helper-settings.yaml    # only when a Helper requires settings
      qualification/          # optional host-only reference/mutant material
```

Terminal-Bench already uses `docker/`, `v2/evaluation_inputs/`, and `v2/hidden/` as its three roots.
Do not place a secret merely somewhere under the pack and assume it is hidden: it must resolve
under the manifest's host root and be referenced through `verification.resources.host`.

For DeepSWE, add an explicit v2 manifest/tasks pair rather than modifying the preserved pre-v2
source files. Use three new non-overlapping roots if needed. The digest-pinned image should provide
the clean repository at the exact full `base_commit`; do not copy a repository tree into a public
asset as a workaround.

## Converting one row

### 1. Reconstruct the intended behavior

Read the complete public instruction, original verifier entrypoint, all fail-to-pass assertions,
and relevant pass-to-pass assertions. Build a short behavior table in the dossier:

| Public requirement | Challenge or artifact evidence | Host-only Oracle decision |
|---|---|---|
| What the Agent is asked to implement | What can be observed without trusting Candidate claims | Predicate, expectation, or threshold |

Classify assertions that only inspect private object identity, mocks, exact helper calls, or an
unrelated regression mechanism. Preserve externally visible consequences. If a scored distinction
cannot be independently observed, record a semantic change rather than embedding the assertion in
the Adapter.

Check that every hidden scoring requirement is supported by the public prompt. Conversion is not an
opportunity to surprise the Agent with a new behavior contract.

### 2. Choose the durable Candidate

For Terminal-Bench output tasks, capture only prompt-declared deliverables with `file_bundle` and
tight per-entry/aggregate bounds. Candidate paths must be under `environment.workdir`, must not
overlap public mounts, and should not include logs, tests, caches, or a whole workspace when one file
is sufficient.

For DeepSWE repository tasks, use `git_patch` with the dossier's full base commit. Pin sensible
patch, changed-file, and changed-byte limits. Exclude tests, reports, framework paths, and other
prompt-forbidden output independently of the Agent's choices. SecureBench must derive the patch
from the stopped worktree; never ask the Agent to submit a trusted patch file.

Do not put the Candidate capture policy into the prompt unless the public task genuinely needs to
name its deliverable. Admission review must confirm that the chosen Candidate shape includes every
valid solution the public prompt permits.

### 3. Route every resource by visibility

Before writing the row, inventory every file or directory:

| Lane | May contain | Must not contain |
|---|---|---|
| `public` (`input`, `assets`) | Prompt, public fixtures, public source inputs | Cases, expected answers, scoring, gold patch |
| `evaluation_inputs` (`resources.runtime`) | Assertion-free Adapter and generic runtime plumbing | Expected outputs, tests, thresholds, Oracle code |
| `hidden` (`resources.host`) | Oracle, challenge generator/corpus, expectations, Helper settings, qualification references | Anything that must execute as Candidate code |

The current Challenge is released one at a time by the Oracle. Do not mount the whole hidden case
corpus into Evaluation. Original hidden tests and `test.patch` may inform conversion and
qualification, but must never be executed or mounted as the v2 verifier.

### 4. Implement checks and components

For an artifact row:

- reference a declared Candidate entry;
- use the narrowest registered passive parser and matching byte/tree limits;
- make the host Oracle validate the parsed value;
- never import, execute, unpickle, or shell out to Candidate content.

For a protocol row, write a reviewed `securebench.adapter/v2` manifest and assertion-free Adapter.
The Adapter may parse one typed Challenge, prepare bounded inputs, invoke Candidate behavior, and
return a bounded Observation or declared Output Artifact. It must not contain expected values,
assertions, score thresholds, pass/fail logic, a reference solution, or a hidden corpus. A crash,
timeout, or malformed response is an Adapter infrastructure failure, not an invented Candidate
verdict.

Use the smallest reusable protocol surface suggested by the row. Good first components are a
schema/action runner for cattrs and a CLI/filesystem-scenario runner for fd. Reuse should mean a
stable assertion-free interface, not a universal Adapter with arbitrary command execution and
task-specific branches.

For external state, use a Trusted Helper only for facts that must be independently witnessed. The
row selects a registered type and reduces its limits; it cannot add capabilities. For Updo, the
built-in HTTP recorder can return a fixed configured response and provide the host-correlated
request ledger. The Adapter receives only scoped Helper Access. The Oracle—not the Adapter—decides
whether the observed request sequence and bodies are correct.

The host Oracle uses `securebench.oracle/v1`: initialize, consume artifact evidence or emit/evaluate
one Challenge at a time, and finalize. Keep opaque expected context in the host process. Parse every
Candidate-originated value as hostile bounded data and return only bounded public diagnostics.

### 5. Write and preflight the v2 row

Start from the executable example, not an old row. Preserve the original public instruction unless
the dossier explicitly approved a semantic rewrite. Use only digest-pinned images. Include source
dataset/revision and dossier metadata. Then load, compile, and call executable preflight in a
focused test before any Agent run.

The row and component manifests are closed schemas. Do not add convenience keys and do not catch a
preflight error by silently selecting a weaker Candidate/check/profile.

### 6. Add a manual qualification record

Append an `Implemented v2 conversion` section to the row's existing dossier. Record:

- row ID, Candidate type, checks, parsers, Adapter protocol, Helpers, and Output Artifacts;
- exact source commit and digest-pinned image;
- any difference from the reviewed conversion design;
- base, reference, mutant, malicious, isolation, and end-to-end results;
- Linux host characteristics relevant to the image/runtime, command, date, and result digest;
- final fidelity decision and any remaining limitation.

Gold/reference patches, expected answers, mutant fixtures, and original hidden tests are
qualification material. Keep them host-only and never mount them into Agent or Evaluation. They are
not the scoring Oracle and must not be revealed through public diagnostics.

## Qualification matrix for every row

Admission tooling is deferred, so encode these as focused tests and document the result manually.
A row is not complete because its reference solution passes.

1. **Base failure:** the unmodified base or missing Terminal deliverable fails the intended checks.
2. **Reference success:** a reviewed correct Candidate passes from a clean baseline.
3. **Targeted-mutant rejection:** at least one mutant per important semantic axis fails. Prefer
   plausible almost-correct implementations over syntax errors.
4. **Malicious-Candidate rejection:** exercise the row's relevant attacks—fixed outputs, forged
   IDs or helper claims, modified protected tests, path/symlink escapes, malformed or oversized
   artifacts/observations, hidden-resource guesses, and undeclared networking.
5. **Fresh isolation:** run at least two Challenges and prove distinct Evaluation IDs, no writable
   state crossing cases, fresh Helper state/credentials, and exact Candidate replay.
6. **Failure ownership:** distinguish Candidate rejection from Adapter, Trusted Helper, Oracle, and
   SecureBench infrastructure failure.
7. **Semantic fidelity:** map every retained public requirement to independent evidence, and record
   every deliberately dropped distinction and its intelligence impact.
8. **Leak check:** after real Docker runs, inspect for leftover Agent/Evaluation/helper containers,
   networks, volumes, credentials, and task-specific temporary state.

For artifact rows, deterministic tests can construct bounded candidate files directly and run the
real parser/Oracle path, as `tests/test_constraints_scheduling_v2.py` does. For `git_patch` rows,
capture base, reference, and mutant stopped worktrees through the real patch capture/store/replay
path. Do not bypass Candidate validation by handing arbitrary observations directly to the Oracle.

Run focused deterministic qualification before an Agent-backed attempt. An Agent run measures the
benchmark; it is not a substitute for proving that the benchmark distinguishes base, correct,
mutant, and malicious Candidates.

## Linux execution workflow

Use the existing `split-verification-v2` branch. Do not work on or merge into `main` during the
pilot. The SSH host name, credentials, and checkout location are deployment details and must not be
committed.

On the Linux host:

1. Pull the current feature branch and verify `git status` before editing or running.
2. Confirm native architecture, free space, Docker availability, and Docker storage with `uname
   -a`, `df -h`, `docker info`, and `docker system df`.
3. Create or refresh the project environment using the repository's locked dependency workflow.
4. Pull every selected benchmark image by its source tag, resolve its repository digest, and put
   the immutable digest reference in the v2 row. A dossier's mutable tag is source metadata, not an
   acceptable v2 image reference.
5. For a DeepSWE row, start the image read-only and verify `/app` is a clean Git repository whose
   `HEAD` exactly matches `input.base_commit`. If it does not, fix the image contract; do not change
   the row's base commit to whatever happens to be present.
6. Run schema/load/compile/preflight tests, then the row's base/reference/mutant/malicious tests,
   then its real fresh-Docker integration test.
7. Run one end-to-end Agent smoke attempt with `max_workers: 1` and a pilot-specific output
   directory. Use the minimum network allowlist required by the public task.
8. Inspect result provenance and Docker/host leaks, record evidence in the dossier, and check disk
   usage before the next row.

Useful repository checks after each small batch:

```bash
.venv/bin/python -m pytest -q -W error
SECUREBENCH_DOCKER_INTEGRATION=1 .venv/bin/python -m pytest -q -W error \
  tests/test_v2_protocol_verification.py
.venv/bin/python -m tools.generate_schemas
.venv/bin/python -m securebench.cli audit-self --output-dir /tmp/securebench-audit
git diff --check
```

Add focused Linux integration tests for the converted row rather than relying only on the generic
protocol file. Run the full suite when a central parser, Adapter contract, Trusted Helper, capture,
or replay path changes.

Linux conversion testing is distinct from the final filesystem-overlay qualification. Ordinary
`file_bundle` and `git_patch` rows should run on Linux now. Do not enable the overlay source gate or
perform root/loop/ext4 qualification as a side effect of converting them.

## When to change the framework

Framework work is justified when a selected row cannot be represented by the implemented closed
contracts without weakening the architecture. Before coding, write the missing component's narrow
contract and answer:

- What independent fact must it expose?
- Why can neither a passive parser nor the existing Adapter Observation establish that fact?
- What capability does the Evaluation receive?
- What stays on the host-only control/evidence plane?
- What are the byte, count, time, process, credential, and lifecycle limits?
- How are Challenge and Evaluation IDs bound and revalidated?
- Which failures belong to Candidate, Adapter, Helper, or framework?
- How is fresh state and teardown proven with real Docker?

Implement the contract and runtime together, register them fail-closed, and add adversarial tests.
Do not add a task-name conditional, arbitrary host callback, general-purpose shell Helper, or
family-specific verifier escape hatch.

## Pilot completion criteria

The first pilot is complete when:

- at least one new artifact row, one ordinary protocol row, and Updo's recorder-backed row pass the
  full manual qualification matrix on Linux;
- the remaining selected rows are either qualified or have a precise documented component blocker;
- every new Adapter remains assertion-free and every expectation remains host-only;
- every protocol case demonstrably uses a fresh Evaluation and correctly correlated evidence;
- no source tag, hidden test runner, gold patch, or candidate-reported verdict is used as a trust
  shortcut;
- dossier implementation records and `current.md`/`next_steps.md` accurately describe what became
  executable;
- warning-strict tests, relevant live-Docker tests, schema generation, audit, packaging, diff, and
  leak checks are clean.

Only after this pilot should the project decide which conversion/admission steps are repetitive
enough to automate and whether the deferred workspace quota and transactional Candidate publication
should be the next framework batch.
