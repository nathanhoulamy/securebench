# Terminal-Bench passive review: five-row pristine subset

This review covers the five passive Terminal-Bench rows selected for the initial
20-row paper subset: `bn-fit-modify`, `db-wal-recovery`, `dna-insert`,
`financial-document-processor`, and `git-leak-recovery`. I compared each source
grader with the v2 task entry, current host Oracle, and focused deterministic
tests. This is a fidelity review; it is not an admission decision.

The current inventory marks all five `implemented,requalification_pending`
([bn-fit-modify through dna-insert](inventory.csv#L116),
[financial-document-processor](inventory.csv#L142), and
[git-leak-recovery](inventory.csv#L147)). Historical dossier evidence does not
establish current admission: the portfolio README says the 25 historical rows
require requalification after the strict-split and Agent-network changes and
that neither pending nor historical evidence is a current admission decision
([README.md](README.md#L54-L60)).

## Focused deterministic validation

Command run without Docker or paid LLM execution:

```bash
.venv/bin/python -m pytest -q -rs -W error \
  tests/test_bn_fit_modify_v2.py \
  tests/test_db_wal_recovery_v2.py \
  tests/test_dna_insert_v2.py \
  tests/test_financial_document_processor_v2.py \
  tests/test_git_leak_recovery_v2.py \
  tests/test_terminal_file_bundle_qualification.py \
  -k 'bn-fit-modify or bn_fit or db-wal-recovery or db_wal or dna-insert or dna_insert or financial-document-processor or financial_document_processor or git-leak-recovery or git_leak'
```

Result: **119 passed, 21 skipped, 98 deselected in 10.93s**. The 21 skips are
the pinned-image Docker qualification cases (`SECUREBENCH_DOCKER_INTEGRATION=1`);
therefore this run validates the checked-in capture/parser/Oracle behavior and
mutation cases, not current end-to-end Agent execution or teardown.

## Requirement-to-evidence matrix

| Row | Original scoring inputs | Current v2 evidence and Oracle | Fidelity assessment and known limits | Missing current admission evidence |
|---|---|---|---|---|
| [`bn-fit-modify`](../../benchmarks/terminal-bench/tasks-v2.jsonl#L4) | The source checks the six learned edges and five-edge intervention graph ([source grader](../../benchmarks/terminal-bench/hidden/bn-fit-modify/tests/test_outputs.py#L44-L95)), then requires five sample columns, 10,000 rows, and a `D` KS-test boundary ([source grader](../../benchmarks/terminal-bench/hidden/bn-fit-modify/tests/test_outputs.py#L98-L151)). | The v2 task captures exactly the three declared CSV artifacts; the Oracle owns the edge sets, columns, row count, and KS boundary ([Oracle](../../benchmarks/terminal-bench/v2/hidden/bn-fit-modify/oracle/oracle.py#L12-L28), [Oracle](../../benchmarks/terminal-bench/v2/hidden/bn-fit-modify/oracle/oracle.py#L57-L140)). Focused tests cover reference success, edge/intervention/distribution/shape mutants, forged columns, malformed CSV, and bounded capture ([tests](../../tests/test_bn_fit_modify_v2.py#L124-L193)). | **Preserved on the scored artifact surface.** Strict CSV parsing is fail-closed. As the dossier records, output evidence cannot prove dataset use, Bayesian-network fitting, intervention provenance, or the full joint distribution ([dossier](TerminalBench/bn-fit-modify.md#L109-L118)); those are inherited source limitations. | Re-run the pinned image under the current policy, record current Agent capture/replay and teardown digests, and retain the existing deterministic base/reference/mutant/malicious evidence in the current qualification record. |
| [`db-wal-recovery`](../../benchmarks/terminal-bench/tasks-v2.jsonl#L12) | The source accepts a nonempty JSON list of typed records, requires IDs 1–11 in order, values 150/250 for IDs 1/2, names for IDs 3–11, and no duplicate IDs ([source grader](../../benchmarks/terminal-bench/hidden/db-wal-recovery/tests/test_outputs.py#L12-L35), [source grader](../../benchmarks/terminal-bench/hidden/db-wal-recovery/tests/test_outputs.py#L47-L107)). | The v2 strict-JSON artifact is checked by the host Oracle for the same structure and values ([Oracle](../../benchmarks/terminal-bench/v2/hidden/db-wal-recovery/oracle/oracle.py#L48-L88)). Focused tests cover the reviewed 11-row reference, source-unchecked fields and Python `bool`/`int` behavior, stale/base/name/type mutants, malformed/forged JSON, replay, and capture bounds ([tests](../../tests/test_db_wal_recovery_v2.py#L114-L218)). | **Preserved on the scored artifact surface.** The dossier records the intentional duplicate-key and size hardening, while preserving source type quirks; WAL/XOR/SQLite provenance is not independently observable and the fixed expected answer is inherited ([dossier](TerminalBench/db-wal-recovery.md#L185-L206)). | Re-run current pinned-image base/reference/mutant/malicious cases and cleanup, then update the historical Linux record with current policy and execution digests. The local deterministic suite is not a substitute for that run. |
| [`dna-insert`](../../benchmarks/terminal-bench/tasks-v2.jsonl#L15) | The source reads exactly four lines, lowercases the two sequence lines, requires DNA characters, reconstructs the insertion and vector overlaps, bounds annealing lengths, and checks `oligotm` ranges and pair difference ([source grader](../../benchmarks/terminal-bench/hidden/dna-insert/tests/test_outputs.py#L41-L102)). | The v2 task mounts the read-only sequence fixture and captures one UTF-8 artifact. The Oracle derives the insertion context from its host-only fixture, preserves positional line semantics, and checks insertion, overlaps, lengths, and Tm ([Oracle](../../benchmarks/terminal-bench/v2/hidden/dna-insert/oracle/oracle.py#L27-L117)). Focused tests verify fixture identity/source constants, reference variants against the original verifier, case/whitespace behavior, malformed/forged outputs, semantic mutants, replay, and capture bounds ([tests](../../tests/test_dna_insert_v2.py#L125-L290)). | **Preserved on the scored artifact surface.** The source does not inspect FASTA headers or prove a particular primer-design procedure; the v2 utility computes the declared Tm predicate from bounded candidate text. Those limitations are documented ([dossier](TerminalBench/dna-insert.md#L458-L481)). | Re-run the pinned image and current stopped-state/replay/teardown matrix. The deterministic reference and source-semantic comparisons pass, but the Docker cases were skipped in this review. |
| [`financial-document-processor`](../../benchmarks/terminal-bench/tasks-v2.jsonl#L19) | The source checks invoice/other file-hash sets, summary header and 11-row shape, per-file and total numeric values, VAT-as-zero behavior, and an empty source directory ([source grader](../../benchmarks/terminal-bench/hidden/financial-document-processor/tests/test_outputs.py#L31-L68), [source grader](../../benchmarks/terminal-bench/hidden/financial-document-processor/tests/test_outputs.py#L71-L97), [source grader](../../benchmarks/terminal-bench/hidden/financial-document-processor/tests/test_outputs.py#L106-L225)). | The v2 task captures three bounded directory trees plus `invoices/summary.csv`; the Oracle checks expected SHA-256 identities, immediate regular files, placement, empty source, safe filenames, CSV shape, and source numeric/NA semantics ([Oracle](../../benchmarks/terminal-bench/v2/hidden/financial-document-processor/oracle/oracle.py#L111-L191)). Focused tests derive host expectations from the source grader, pass the reference state, preserve source-accepted duplicate/ignored-file/row-order quirks, reject state/summary/path/encoding mutants, and test replay ([tests](../../tests/test_financial_document_processor_v2.py#L166-L223), [tests](../../tests/test_financial_document_processor_v2.py#L249-L400)). | **Preserved on the pinned corpus and scored final state.** The Oracle deliberately retains source set semantics and ignored nested/JSON behavior while rejecting unsafe summary names; it does not turn the fixed document corpus into a general OCR evaluation ([dossier](TerminalBench/financial-document-processor.md#L713-L730)). | Re-run the current pinned-image matrix, including the 17-document Agent-produced state, tree/parser bounds, malicious path cases, replay, and cleanup. The larger tree is the main resource cost, but no fidelity defect warrants replacement. |
| [`git-leak-recovery`](../../benchmarks/terminal-bench/tasks-v2.jsonl#L23) | The source checks recovered secret text, absence of `secret[` in reachable history and dangling objects, preservation of a required commit message, and visible worktree checksum ([source grader](../../benchmarks/terminal-bench/hidden/git-leak-recovery/tests/test_outputs.py#L11-L63), [source grader](../../benchmarks/terminal-bench/hidden/git-leak-recovery/tests/test_outputs.py#L66-L113)). | The v2 task captures a bounded Git repository and secret file; the Oracle checks normalized secret text, expected worktree, all parsed object contents, reachable-history case-insensitive leakage, and required commit ([Oracle](../../benchmarks/terminal-bench/v2/hidden/git-leak-recovery/oracle/oracle.py#L23-L57), [Oracle](../../benchmarks/terminal-bench/v2/hidden/git-leak-recovery/oracle/oracle.py#L85-L105)). Focused tests cover source constants, reference/replay, leaked-secret/base/worktree/history/config/alternates mutants, forged claims, and capture bounds ([tests](../../tests/test_git_leak_recovery_v2.py#L127-L235)). | **Preserved for the intended SHA-1 non-bare repository shape.** The Oracle scans all parsed objects, closing the source verifier's unreachable-ancestor blind spot; that is a documented hardening difference. Unsupported repository shapes remain outside the source contract ([dossier](TerminalBench/git-leak-recovery.md#L907-L925)). | Re-run the current pinned image with base/reference/cleanup and malicious repository cases, then record parser/replay/teardown digests. The Git parser is more complex, but the review found no semantic reason to replace it. |

## Keep/replace recommendation

Keep all five in the pristine subset. None has a confirmed semantic mismatch, and
each has a small, assertion-free passive Oracle with deterministic reference and
mutation coverage. If the paper schedule forces a smaller first run, defer
`bn-fit-modify` first because its 10,000-row numerical artifact is the largest
candidate and `financial-document-processor` second because its bounded tree and
17-document corpus are the most expensive to exercise. That is a budget choice,
not a fidelity finding; replacing either row would require qualifying a different
row and is unlikely to save time overall. `db-wal-recovery`, `dna-insert`, and
`git-leak-recovery` are suitable low-to-moderate-cost representatives of JSON,
scientific-text, and repository-state artifacts.

Until the current Docker/policy qualification is rerun, report these five as
**qualification-pending/requalification-pending**, never as Approved. The
repository admission rule requires base failure, reference success, targeted
mutant rejection, malicious-candidate rejection, and documented semantic fidelity
([AGENTS.md](../../AGENTS.md#L107-L112)); the deterministic run above supplies the
local portion but not the skipped pinned-image evidence.
