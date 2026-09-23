# Paper subset review: five TerminalBench protocol rows

This is a bounded admission review for the five TerminalBench protocol rows
proposed for the initial 20-row pristine subset:
`cancel-async-tasks`, `circuit-fibsqrt`, `cobol-modernization`, `extract-elf`,
and `fix-code-vulnerability`. It is a paper-scope review, not a certification
of the other implemented rows.

All five rows are implemented, but the inventory marks them
`requalification_pending`. The dossier's design verdict is separate from a
current admission decision; the portfolio explicitly says that historical
qualification records do not constitute current admission
([inventory](inventory.csv), [status explanation](README.md#implementation-and-qualification-status)).

The focused deterministic command already run for this review was:

```text
.venv/bin/pytest -q \
  tests/test_cancel_async_tasks_v2.py \
  tests/test_circuit_fibsqrt_v2.py \
  tests/test_cobol_modernization_v2.py \
  tests/test_extract_elf_v2.py \
  tests/test_fix_code_vulnerability_v2.py
```

It completed with **144 passed, 40 skipped**. The skipped tests require Docker
or other image-dependent qualification. No Docker or paid model run was used
for that deterministic run. A subsequent real-Docker run of the two rows with
available cached images was:

```text
SECUREBENCH_DOCKER_INTEGRATION=1 .venv/bin/python -m pytest -q -W error \
  tests/test_circuit_fibsqrt_v2.py tests/test_cobol_modernization_v2.py \
  --junitxml=/tmp/securebench-paper-terminal-protocol.xml
```

It completed with **31 passed, 2 skipped in 82.12s**. The skips were the
reference-replay tests because their `/tmp` reference fixtures were absent;
they are evidence gaps, not passing reference qualifications. The remaining
three rows still have no current Docker result in this review, so every row
below remains pending a complete current admission record.

## Requirement and evidence matrix

The first column links the original scoring entrypoint. The second links the
current host Oracle and the third links the current focused tests. Those files
are evidence sources, not executable admission shortcuts: the v2 Oracle owns
the expected answers and verdict.

| Row | Original scoring surface | Current Oracle and tests | What the v2 check actually establishes |
|---|---|---|---|
| [`cancel-async-tasks`](../../benchmarks/terminal-bench/hidden/cancel-async-tasks/tests/test_outputs.py) | Five subprocess scenarios check concurrent starts, one-slot serialization, cancellation at/below/above the concurrency limit, and cleanup counts/timing (`test_outputs.py:17-172`). | [`oracle.py`](../../benchmarks/terminal-bench/v2/hidden/cancel-async-tasks/oracle/oracle.py) correlates lifecycle and process-supervisor helpers, validates nonce-bearing event sequences, timing, signal order, and cleanup (`:76-166`, `:168-348`). [`test_cancel_async_tasks_v2.py`](../../tests/test_cancel_async_tasks_v2.py) covers semantic mutants, forged claims, credential forgery, and pinned replay (`:397-501`). | Host-correlated lifecycle evidence proves the task events and signal timing for the five retained scenario shapes. Candidate stdout and claims are not scoring evidence. |
| [`circuit-fibsqrt`](../../benchmarks/terminal-bench/hidden/circuit-fibsqrt/tests/test_outputs.py) | The source compiles an immutable simulator and compares 28 positive inputs against `fib(isqrt(n)) mod 2^32` (`test_outputs.py:56-147`). | [`oracle.py`](../../benchmarks/terminal-bench/v2/hidden/circuit-fibsqrt/oracle/oracle.py) owns the expected arithmetic and evaluates the artifact shape plus each protocol result (`:48-70`, `:84-99`, `:101-166`). [`test_circuit_fibsqrt_v2.py`](../../tests/test_circuit_fibsqrt_v2.py) checks parser bounds, original/private cases, forged outputs, and real-pinned mutants (`:177-332`). | The Candidate supplies `gates.txt`; the public adapter runs the reviewed simulator and returns bounded status/stdout/stderr. The host compares exact numeric results for the retained 28 cases plus four run-seeded cases. |
| [`cobol-modernization`](../../benchmarks/terminal-bench/hidden/cobol-modernization/tests/test_outputs.py) | The source runs the same program three times over fixed account/book/transaction files and compares the resulting fixed-width files byte-for-byte (`test_outputs.py:34-93`). | [`oracle.py`](../../benchmarks/terminal-bench/v2/hidden/cobol-modernization/oracle/oracle.py) computes expected records independently for the source case and three seeded cases, then checks correlated output artifacts (`:31-141`, `:172-229`). [`test_cobol_modernization_v2.py`](../../tests/test_cobol_modernization_v2.py) covers state preservation, seeded cases, forged claims, source mutants, and artifact symlinks (`:170-325`). | In one fresh Evaluation per case, the Candidate process is restarted for each transaction input. Host-owned expected fixed-width artifacts, exit codes, and correlation identifiers determine the result. |
| [`extract-elf`](../../benchmarks/terminal-bench/hidden/extract-elf/tests/test_outputs.py) | The source runs Candidate and a reference parser on one compiled ELF and accepts no incorrect values with at least 75% of reference mappings (`test_outputs.py:316-390`). | [`oracle.py`](../../benchmarks/terminal-bench/v2/hidden/extract-elf/oracle/oracle.py) loads four digest-pinned host-only ELF cases, independently parses sections, and enforces no-incorrect-values plus 75% coverage (`:57-134`, `:137-152`, `:202-269`). [`test_extract_elf_v2.py`](../../tests/test_extract_elf_v2.py) checks pinned cases, parser conformance, exact coverage, forged verdicts, and real replay (`:107-287`). | One host-selected ELF enters each disposable Evaluation. The Candidate output is compared to host-computed mappings; the reference script is never imported or executed as the v2 verdict mechanism. |
| [`fix-code-vulnerability`](../../benchmarks/terminal-bench/hidden/fix-code-vulnerability/tests/test_outputs.py) | The source requires `/app/report.jsonl`, exact `cwe-93` reporting for `/app/bottle.py`, and `_hkey` normalization/error behavior (`test_outputs.py:13-133`). | [`oracle.py`](../../benchmarks/terminal-bench/v2/hidden/fix-code-vulnerability/oracle/oracle.py) passively checks the report and protected-source digest, then evaluates five host-generated call cases (`:62-106`, `:143-180`, `:274-360`). [`test_fix_code_vulnerability_v2.py`](../../tests/test_fix_code_vulnerability_v2.py) checks artifact bounds, source digest, reports, behavior mutants, forged correlation, and pinned replay (`:102-455`). | The source bytes are checked without host execution. In Evaluation, only an allowlisted wrapper surface is called; the host compares exact returned values and genuine `ValueError` outcomes across direct and wrapper calls. |

## Forgery and trust assessment

The relevant threat model assumes that Candidate code can inspect or tamper
with guest-side adapter state. A schema-valid observation, guest stdout, or
adapter-side claim is therefore not independently trusted. The rows are
acceptable only where the host Oracle either compares the observation with
host-owned expectations or uses a protected helper for the property that
cannot be reconstructed from guest claims.

| Row | What a fully compromised guest can forge | Evidence that remains host-owned | Assessment |
|---|---|---|---|
| `cancel-async-tasks` | Candidate can forge its own stdout, exit claims, and in-process state. It can also call the loopback task service, but it receives no helper credential and cannot write the host ledger. | The parent adapter owns the service and helper credentials; the lifecycle ledger and process supervisor are correlated by challenge and Evaluation IDs. The redesign specifically removed ledger access from Candidate-visible callback closures ([dossier](TerminalBench/cancel-async-tasks.md), lines 115-133). | No confirmed forgery defect. This is the strongest row in the set for a property requiring trusted external state. Current Docker/requalification evidence is still required. |
| `circuit-fibsqrt` | Candidate can return a synthetic adapter response or implement a lookup/solver after seeing the released input. Guest process claims are not meaningful. | The simulator is public runtime plumbing; the Oracle computes expected arithmetic and chooses four seed-dependent cases outside the published list. | This is a normal black-box challenge/response trust model: it establishes behavior on hidden host-selected inputs, not provenance of the implementation. No helper is needed for the scored property. |
| `cobol-modernization` | Candidate controls the transaction program and output files, and can make adapter-side observations look successful. It could implement a lookup for the visible case family. | Expected account/book/transaction bytes are generated in the host Oracle and output artifacts are correlated to the same challenge and Evaluation. | Black-box behavior is measurable, but implementation provenance and general COBOL equivalence are not. The row is suitable only with its documented valid-record scope. |
| `extract-elf` | Candidate sees the current ELF and can emit a synthetic mapping or a forged verdict-shaped JSON value. | The four ELF bytes and their expected mappings remain host-only; the Oracle validates challenge digest/index, fresh IDs, integer mappings, incorrect values, and coverage. | No confirmed guest-forgery path to a passing result without satisfying the host mapping predicate. The result proves the extraction behavior on the pinned corpus, not a general ELF implementation. |
| `fix-code-vulnerability` | Candidate code is imported into the adapter process (`adapter.py:23-33`), so a compromised guest could monkeypatch adapter-side behavior or fabricate returned observations. | The report and protected-source digest are passively checked by the host; hidden calls, expected outcomes, and the final verdict remain in the Oracle. The Oracle also requires fresh correlated cases (`oracle.py:274-360`). | The artifact half is independently defensible. The protocol half is behavioral evidence, not proof that an unmodified process executed the calls. This is acceptable for a behavioral paper claim, but the paper must not describe guest observations as trusted execution traces. |

No row in this matrix should claim that an adapter response is truthful merely
because it has the right schema. `cancel-async-tasks` has independently
protected helper evidence for lifecycle state. The other four rely on the
standard black-box property: the host keeps expected answers and hidden cases,
while the Candidate may see the current challenge and must produce a matching
bounded result.

## Semantic fidelity and missing evidence

| Row | Fidelity limitation | Paper condition for admission |
|---|---|---|
| `cancel-async-tasks` | Work and cleanup delays are shortened, and helper access was redesigned after the source's closure-forgery issue. The five concurrency/cancellation shapes and ordering are retained ([dossier](TerminalBench/cancel-async-tasks.md), lines 127-143). | Pending current image qualification. Admit if the fresh helper correlation and malicious-Candidate cases pass; report the bounded timing model. |
| `circuit-fibsqrt` | The public prompt says all unsigned 32-bit inputs, but the source verifier covers positive values with square roots no greater than 220. The upstream reference is wrong for `N=0` and large inputs; the converted row retains that demonstrated envelope ([dossier](TerminalBench/circuit-fibsqrt.md), lines 116-136). | Pending. The paper must state the qualified input envelope. If the paper claims all-`uint32` correctness, replace this row or repair and requalify the reference and challenge domain. |
| `cobol-modernization` | The source scores one valid transaction sequence. Seeded cases remain within the three-account/three-book valid fixed-width domain and do not establish malformed records, overdrafts, duplicate IDs, overflow, or broad program equivalence ([dossier](TerminalBench/cobol-modernization.md), lines 121-140). | Pending. Admit only with the narrower valid-record/state-transition claim; otherwise replace it with a row whose public scorer covers the claimed domain. |
| `extract-elf` | The host corpus is four pinned Linux/amd64 ELF64 little-endian files. ELF32, big-endian, and other object formats are outside demonstrated coverage ([dossier](TerminalBench/extract-elf.md), lines 119-135). | Pending. State the corpus and ELF64 little-endian scope. A broader parser claim requires additional host cases and conformance evidence. |
| `fix-code-vulnerability` | The protected-source rule is intentionally narrower than the source verifier: unrelated source edits or refactors outside `_hkey`/`_hval` fail even if the original tests would pass ([dossier](TerminalBench/fix-code-vulnerability.md), lines 149-166). | Pending. This narrowing matches the public request to fix the named vulnerability without unrelated changes. Admit after current artifact/protocol replay, with the source-scope rule disclosed. |

The current Docker result materially improves evidence for `circuit-fibsqrt`
and `cobol-modernization`: their focused adapter, Oracle, mutant, and schema
checks passed in the 31-test run above. Their reference replay tests were two
of the skipped tests because the required `/tmp` fixtures were absent, so this
does not yet establish current reference success or a binary admission.

## Recommendation for the initial subset

Do not present the five rows as currently admitted. The deterministic result is
useful qualification evidence, but it does not replace the required fresh
Agent capture, Evaluation replay, isolation/resource preflight, and malicious
Candidate checks.

For a faithful paper subset, retain all five only if the paper states the
documented scopes above and records current qualification evidence. If the
paper requires a claim that matches each public prompt without narrowing, do
not repair the claims silently: replace `circuit-fibsqrt` or
`cobol-modernization` when their claimed domains are broader than their
demonstrated source scoring, and replace any row whose current Docker replay
cannot be completed. If one protocol row must be replaced now, use
`gpt2-codegolf` as the first candidate replacement: its conversion retains the
source contract and adds a host-only continuation case to close the published
fixed-output shortcut ([dossier](TerminalBench/gpt2-codegolf.md), lines 73-115). It
still requires current requalification before admission.

**Review disposition:** all five are **qualification-pending**, with no
current binary Approved decision. `cancel-async-tasks` has the clearest trusted
measurement story; `circuit-fibsqrt`, `cobol-modernization`, and `extract-elf`
need explicit scope language; `fix-code-vulnerability` needs its protected
source boundary and guest-side behavioral trust model described accurately.
