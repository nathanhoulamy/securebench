# TerminalBench and DeepSWE conversion portfolio

This directory is the canonical design record for converting TerminalBench 2.0
and DeepSWE to split verification. Each dossier records the original grading
surface, the proposed durable candidate, the evidence strategy, fidelity limits,
and the validation plan.

The implementation workflow for turning these dossiers into v2 rows is in the
[`conversion guide`](conversion-guide.md).
The first-wave Linux admission record is the
[`pilot qualification checklist`](pilot-qualification-checklist.md).

## Portfolio

| Benchmark | Rows | Design approved | Design excluded |
|---|---:|---:|---:|
| DeepSWE | 113 | 97 | 16 |
| TerminalBench 2.0 | 89 | 73 | 16 |
| **Total** | **202** | **170** | **32** |

Of these, 162 rows have an approved clean or semantic-change conversion design
and eight have an approved major-redesign direction. The other 32 are excluded:
16 DeepSWE rows still need a stronger decision or design, and 16 TerminalBench
rows have an explicit no-conversion decision.
Approval does not imply that the required runtime capabilities are implemented
yet.

The design disposition is tracked separately from approval status:

| Benchmark | Clean | Semantic change | Major redesign | No conversion | Total |
|---|---:|---:|---:|---:|---:|
| DeepSWE | 32 | 64 | 17 | 0 | 113 |
| TerminalBench 2.0 | 51 | 16 | 6 | 16 | 89 |
| **Total** | **83** | **80** | **23** | **16** | **202** |

The authoritative per-row status is [`inventory.csv`](inventory.csv). Dossier
headers deliberately defer to that inventory so status cannot drift between two
sources.

## Implementation and qualification status

`review_status`, `final_verdict`, and `disposition` describe the portfolio's
design review. They do not claim that a v2 row exists or that a row is admitted
for benchmark use. The machine-readable implementation and runtime state lives
in the `implementation_status` and `qualification_status` columns of
[`inventory.csv`](inventory.csv):

| State | Rows | Meaning |
|---|---:|---|
| Implemented | 66 | A v2 task row exists in the executable TerminalBench (36) or DeepSWE (30) pack. |
| Design only | 104 | The row has a reviewed design but no v2 task row yet. |
| Excluded | 32 | The portfolio disposition excludes conversion under the current trust model. |

The implemented TerminalBench rows were qualified or requalified on 2026-09-22
against their pinned images under real Docker. Rows converted from a published
registry image are pinned by repository digest; the three Wave B rows have no
published image and are pinned by locally built image ID, which is host-local
(see the record's image-pinning caveat). The current admission record is
[`terminal-bench-qualification-record.md`](terminal-bench-qualification-record.md);
the machine-readable result is `runs/qualification/terminal-bench-qualification.json`.
DeepSWE admission is recorded in
[`deepswe-qualification-record.md`](deepswe-qualification-record.md).

| `qualification_status` | Rows | Meaning |
|---|---:|---|
| `approved` | 60 | Gates 1–8 executed and passed; admitted (30 TerminalBench, 30 DeepSWE). |
| `fidelity_review_pending` | 3 | Gates pass, but the semantic-fidelity decision is deferred. |
| `evidence_gap_pending` | 1 | `circuit-fibsqrt`: gate 2 unproven, no reference netlist exists. |
| `qualification_pending` | 1 | `install-windows-3.11`: implemented but has no focused test. |
| `reproducibility_pending` | 1 | `password-recovery`: gates pass, but its image rebuilds to a different ID every time (random `setup.sh`). |

Open fidelity questions are parked in the
[fidelity review queue](fidelity-review-queue.md), and conversion blockers plus
decisions awaiting review are in
[conversion blockers](conversion-blockers.md). Parking is not admission: a
parked row stays pending and must not appear in admitted results.

The four DeepSWE rows remain `qualification_pending`; DeepSWE requalification has
not run yet.

The [paper subset queue](paper-subset.md) records the proposed ten-per-benchmark
scope, fidelity reviews, and first new DeepSWE conversion. Selection is not
admission. The Helm unified-stream, kgateway hash-policy, and oxvg selector
designs are protocol checks with artifact observations: producing their output
requires candidate execution, despite the earlier passive-pattern labels.

## Source revisions

- DeepSWE: `e016041a6ccf8da29906afc9a3f5a8df940a1f78`
- TerminalBench 2.0: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`

Every dossier links to its pinned source row and records the candidate image,
original verifier entrypoints, tests, and acceptance surface used during review.

## Mapping review patterns to the v2 schema

The portfolio found no need for another schema-level check type:

| Review pattern | V2 representation |
|---|---|
| Passive artifact verification | An `artifact` check with a bounded registered parser |
| Black-box challenge/response | A `protocol` check with a public assertion-free adapter |
| Trusted external state | A `protocol` check with a scoped trusted service |
| Black-box plus passive artifact | A `protocol` check with returned bounded artifacts |
| Hybrid of all three | One correlated `protocol` check with services and returned artifacts |

Trusted external state is therefore a protocol capability, not a third check
type. Services, adapters, parsers, and Oracles require reviewed, versioned
component contracts.

## Trust boundary

1. The Agent receives only public task material and produces one durable
   candidate.
2. Candidate code may execute only in a disposable Evaluation environment.
3. Hidden cases, expected values, scoring, and trusted evidence remain with the
   host Oracle.
4. Artifact parsers are passive and bounded.
5. Candidate claims, guest test reports, and guest diagnostics are not trusted
   evidence by themselves.
6. Each scored observation must be correlated to the current check and case.

The complete contract is documented in the
[`schema`](../split-verification/schema.md) and
[`security model`](../split-verification/security-model.md).

## Decision meanings

- **Clean:** the intended behavior can be preserved without meaningful semantic
  loss.
- **Semantic change:** the conversion is implementable, but the dossier records
  an explicit loss or behavioral substitution.
- **Major redesign:** the task needs new shared verification infrastructure or a
  material benchmark redesign.
- **Excluded:** do not convert. The row either needs a stronger decision or
  design, or has an explicit no-conversion disposition under the current trust
  model. The detailed disposition remains in the inventory so the reason is not
  lost.

The focused [`action queue`](action-queue.md) contains all 32 excluded rows
plus the eight approved major-redesign rows. Clean and semantic-change rows
remain queryable in `inventory.csv`.

## Implementation rule

A dossier is not an executable benchmark. Convert a row only when all candidate,
parser, adapter, service, and evidence capabilities it requires pass executable
preflight. Every completed conversion must demonstrate base failure, reference
success, targeted-mutant rejection, malicious-candidate rejection, and recorded
semantic fidelity. Unsupported rows must remain visibly blocked rather than
falling back to a weaker verifier.
