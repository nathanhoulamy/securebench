# Fidelity review queue

This file parks conversions whose **semantic fidelity decision is deliberately
deferred**. It was opened on 2026-09-22 so that known mismatches between a task's
public prompt and its demonstrated evidence are recorded explicitly instead of
being silently narrowed while the conversion work continues.

## What parking means

Parking is **not** admission and **not** an exemption.

- Final admission stays binary: **Approved** or **Excluded** ([`AGENTS.md`](../../AGENTS.md)).
- A parked row remains `qualification_pending` / `requalification_pending`. It must
  not appear in admitted benchmark results or in paper coverage counts.
- A parked row may still complete every other qualification gate. Parking records
  that one specific gate — gate 7, semantic fidelity — has no accepted decision yet.
- Parking must never be used to avoid gate 3 or 4. An Oracle is never weakened to
  clear a row, and a mismatch is never resolved by quietly rewriting the claim.

The `fidelity_review` column in [`inventory.csv`](inventory.csv) carries the pointer:
`none` for rows with no open question, or the anchor below for a parked row.

## Resolving a parked entry

Each entry needs one of these outcomes recorded before the row can be admitted:

1. **Narrow the claim** — qualify against the demonstrated envelope and state that
   envelope in the paper. Admissible, but the paper must not describe the row as
   covering the full public prompt.
2. **Replace the row** — substitute a row whose demonstrated scope matches its
   public prompt. `gpt2-codegolf` is the named reserve for the protocol subset.
3. **Repair and requalify** — fix the reference or challenge domain so the row
   genuinely covers its public prompt, then rerun the full matrix.

## Parked entries

### circuit-fibsqrt — domain mismatch + missing reference

**Row:** `terminal-bench/circuit-fibsqrt` · artifact + protocol ·
[dossier](TerminalBench/circuit-fibsqrt.md)

Two separate open items:

1. **Domain mismatch.** The public prompt asks for all unsigned 32-bit inputs. The
   source verifier only covers positive values whose integer square root is at most
   220, and the upstream reference is wrong for `N = 0` and for large inputs. The
   converted row retains that demonstrated envelope, so it must not be described as
   pristine against the full public requirement.
2. **Reference solution does not exist.** `tests/test_circuit_fibsqrt_v2.py`
   expected it at `/tmp/securebench-circuit-reference/gates.txt`, an ephemeral path
   that is now empty, so `test_reference_passes_real_pinned_evaluations` skips and
   **gate 2 (reference success) is unproven**. Producing one means synthesising a
   gate-level netlist for `fib(isqrt(n)) mod 2^32` — a substantial piece of work in
   its own right, not a fixture copy.

Note: `benchmarks/terminal-bench/docker/circuit-fibsqrt/gates.txt` is the identity
starter stub shipped to the agent (`out_i = out_i`), **not** a reference solution.
It is correctly public and is not a leak.

**Recommended outcome:** replace with `gpt2-codegolf`, or repair the reference and
challenge domain together. Narrowing alone is awkward here because the mismatch is
against the public prompt the agent actually reads.

### cobol-modernization — valid-records-only domain

**Row:** `terminal-bench/cobol-modernization` · protocol ·
[dossier](TerminalBench/cobol-modernization.md)

The source scores one valid transaction sequence, and the seeded cases stay inside
the three-account / three-book valid fixed-width domain. The conversion does not
establish behavior for malformed records, overdrafts, duplicate IDs, or numeric
overflow, and does not establish broad COBOL program equivalence. Black-box behavior
on the retained domain is measurable; implementation provenance is not.

The reference was also expected at `/tmp/securebench-cobol-reference/program.py` and
is absent, so gate 2 is unproven here too. Unlike circuit-fibsqrt this is
recoverable: the source program is checked in at
`benchmarks/terminal-bench/docker/cobol-modernization/src/program.cbl` and can be
ported faithfully to a host-only reference.

**Recommended outcome:** narrow the claim. Admit with the explicit
valid-record/state-transition scope stated in the paper.

### extract-elf — pinned ELF64 corpus

**Row:** `terminal-bench/extract-elf` · protocol ·
[dossier](TerminalBench/extract-elf.md)

The host corpus is four pinned Linux/amd64 ELF64 little-endian files. ELF32,
big-endian, and other object formats are outside demonstrated coverage. The result
proves extraction behavior on the pinned corpus, not a general ELF implementation.

**Recommended outcome:** narrow the claim; state the corpus and the ELF64
little-endian scope. A broader parser claim needs additional host cases.

### fix-code-vulnerability — narrowed source rule + in-process adapter

**Row:** `terminal-bench/fix-code-vulnerability` · artifact + protocol ·
[dossier](TerminalBench/fix-code-vulnerability.md)

Two documented limits:

1. The protected-source rule is intentionally **narrower** than the source verifier:
   unrelated edits or refactors outside `_hkey`/`_hval` fail even where the original
   tests would pass. This matches the public request to fix the named vulnerability
   without unrelated changes, but it is a deliberate narrowing.
2. Candidate code is imported into the adapter process, so a compromised guest can
   monkeypatch adapter-side behavior or fabricate returned observations. The artifact
   half is independently defensible; the protocol half is **behavioral evidence, not
   proof that an unmodified process executed the calls**.

**Recommended outcome:** narrow the claim, and require that the paper not describe
guest observations as trusted execution traces.

## Not parked

Recording why, so these are not re-litigated:

- **`bn-fit-modify`, `db-wal-recovery`, `dna-insert`, `financial-document-processor`,
  `git-leak-recovery`** — the passive review found no confirmed semantic mismatch.
  Their limits (no proof of dataset use, no WAL/XOR provenance, fixed document
  corpus) are *inherited source limitations*, not conversion-introduced narrowings,
  and are already recorded in each dossier.
- **`cancel-async-tasks`** — shortened work/cleanup delays are a declared bounded
  timing model, and the five concurrency/cancellation shapes are retained. It has the
  strongest trusted-measurement story in the protocol set.
- **`git-leak-recovery`** — its Oracle scans all parsed objects, closing a blind spot
  in the source verifier. That is a hardening difference in the safe direction and is
  documented as such.
