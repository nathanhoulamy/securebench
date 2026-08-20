# SecureBench split-verification architecture

This file is the repository-wide source of truth for architectural intent.
SecureBench assumes the agent, its workspace, and its output are adversarial.
Correctness must be decided outside the environment that produced the solution.

## Core components

1. **Agent VM:** The environment where the agent receives public materials and
   develops the solution.
2. **Candidate:** The extracted submission, such as a git diff, selected files,
   generated artifacts, or state changes.
3. **Evaluation VM:** A fresh environment containing the candidate and public
   runtime/adapter components. Candidate-controlled code executes only here
   during evaluation.
4. **Oracle:** Trusted host-side logic that owns secret cases, expected answers,
   scoring rules, and the final verdict.

## Required flow

1. Give the Agent VM only the public task and public assets.
2. Stop the Agent VM and capture exactly one bounded, durable, replayable
   candidate. Never capture live processes, connections, credentials, mounts,
   or in-memory state.
3. Reconstruct that candidate from an immutable baseline in a fresh Evaluation
   VM for each case. Candidate-controlled state is disposable between cases.
4. Let the Oracle release only the current bounded challenge through a reviewed,
   public, assertion-free adapter.
5. Return bounded observations as internal evidence. Only the Oracle may compare
   against secrets, score evidence, or issue a verdict.
6. Destroy the Evaluation VM and case-local state before the next case.

## Verification model

SecureBench has only two core check types:

- **Artifact:** passively parse bounded candidate bytes. Never import or execute
  candidate code.
- **Protocol:** exercise the candidate in an Evaluation VM through a public
  adapter and return bounded observations to the Oracle.

Benchmark review has identified three verification patterns:

1. **Passive artifact verification:** inspect bounded candidate artifacts
   without executing candidate code. This maps to an `artifact` check.
2. **Black-box challenge/response:** send one Oracle-selected challenge through
   a public adapter and observe candidate behavior. This maps to a `protocol`
   check.
3. **Trusted external state:** let the candidate interact with a controlled
   service whose host-only control or evidence plane reports what occurred.
   This is a capability inside a `protocol` check, not a third check type.

Checks may combine these patterns. CLI, HTTP, browser, compiler, lifecycle, and
multi-peer behavior are protocol variants, not new check types. All returned
artifacts and trusted-service evidence must remain correlated to the same check
and case.

## Visibility and trust

- `public`: visible to the Agent VM, Evaluation VM, and host.
- `evaluation_inputs`: visible to the Evaluation VM, but not the Agent VM.
- `hidden`: visible only to the host and Oracle.

Secrets, expected answers, assertions, scoring logic, and the remaining case
corpus must never enter either VM. Candidate claims, guest test results, stdout,
and diagnostics are untrusted observations—not verdicts. Enforce strict bounds,
reject malformed or ambiguous data, pin runtime identities, disable unnecessary
network access, and fail closed.

## Implementation discipline

- Preserve one replayable candidate and the Agent/Evaluation/Oracle separation;
  do not add family-specific verifier escape hatches.
- Keep adapters generic and assertion-free. Put task-specific judgment in the
  Oracle.
- Treat schema-valid target features as non-executable until runtime preflight
  and adversarial tests prove support.
- A conversion must demonstrate base failure, reference success, targeted-mutant
  rejection, malicious-candidate rejection, and documented semantic fidelity.
- Conversion status is binary: **Approved** or **Excluded**.

Field-level contracts live in `securebench/schemas/benchmark.py` and generated
JSON Schemas. Architectural detail and current limitations live in
`docs/split-verification/schema.md` and
`docs/split-verification/security-model.md`.
