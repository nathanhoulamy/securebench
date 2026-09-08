# SecureBench split-verification architecture

This file is the repository-wide source of truth for architectural intent.
SecureBench assumes the agent, its workspace, and its output are adversarial.
Correctness must be decided outside the environment that produced the solution.

The architecture is independent of the isolation backend; Docker is the current
implementation. It assumes the backend enforces the declared boundaries and
access restrictions. Arbitrary kernel, container-runtime, or hypervisor escapes
are outside scope; configuring and verifying the required isolation is our
responsibility.

## Core components

1. **Agent environment:** The environment where the agent receives public
   materials and develops the solution.
2. **Candidate:** The extracted submission, such as a git diff, selected files,
   generated artifacts, or state changes.
3. **Evaluation environment:** A fresh environment containing the candidate and
   runtime/adapter components. Candidate-controlled code executes only here
   during evaluation.
4. **Oracle:** Trusted host-side logic that owns secret cases, expected answers,
   scoring rules, and the final verdict.

## Required flow

1. Give the Agent environment only the public task and public assets, with
   external access restricted to the declared resource policy.
2. Stop the Agent environment and capture exactly one bounded, durable, replayable
   candidate. Never capture live processes, connections, credentials, mounts,
   or in-memory state.
3. Reconstruct that candidate from an immutable baseline in a fresh Evaluation
   environment for each case. Candidate-controlled state is disposable between
   cases.
4. Let the Oracle release only the current bounded challenge through a reviewed,
   assertion-free adapter whose implementation need not be secret.
5. Return bounded observations as internal evidence. Only the Oracle may compare
   against secrets, score evidence, or issue a verdict.
6. Destroy the Evaluation environment and case-local state before the next case.

## Verification model

SecureBench has only two core check types:

- **Artifact:** passively parse bounded candidate bytes. Never import or execute
  candidate code.
- **Protocol:** exercise the candidate in an Evaluation environment through an
  adapter and return bounded observations to the Oracle.

Benchmark review has identified three verification patterns:

1. **Passive artifact verification:** inspect bounded candidate artifacts
   without executing candidate code. This maps to an `artifact` check.
2. **Black-box challenge/response:** send one Oracle-selected challenge through
   an adapter and observe candidate behavior. This maps to a `protocol`
   check.
3. **Trusted external state:** let the candidate interact with a controlled
   service whose host-only control or evidence plane reports what occurred.
   This is a capability inside a `protocol` check, not a third check type.

Checks may combine these patterns. CLI, HTTP, browser, compiler, lifecycle, and
multi-peer behavior are protocol variants, not new check types. All returned
artifacts and trusted-service evidence must remain correlated to the same check
and case.

## Visibility and trust

- `public`: visible to the Agent environment, Evaluation environment, and host.
- `evaluation_inputs`: visible to the Evaluation environment, but not the Agent
  environment.
- `hidden`: visible only to the host and Oracle.

Protected evaluation secrets, expected answers, grading assertions, scoring logic,
and the remaining case corpus must never enter either environment. Candidate
claims, guest test results, stdout, and diagnostics are untrusted observations,
not verdicts. Enforce strict bounds,
reject malformed or ambiguous data, pin runtime identities, disable unnecessary
network access, and fail closed.

Adapters may be withheld from the Agent and delivered via `evaluation_inputs`,
but security must not depend on hiding their implementation. Assume candidate code may compromise
the entire Evaluation environment, including the adapter process. Read-only
adapter files and schema-valid responses do not establish truthful measurements.
Oracle decisions must remain defensible when guest observations are adversarial;
properties requiring trusted measurement need independently protected evidence.

## Resource-access policy

Define permitted resources, external services, and communication paths explicitly
for Agent and Evaluation environments. Express policy independently of Docker
options, deny undeclared access, and verify that the backend enforces the policy.
Access to a declared relay, proxy, or helper does not authorize direct access to
host services or other evaluations.

## Implementation discipline

- Preserve one replayable candidate and the Agent/Evaluation/Oracle separation;
  do not add family-specific verifier escape hatches.
- Keep adapters generic and assertion-free. Put task-specific judgment in the
  Oracle. Assertion-free means no authoritative correctness judgments or secret
  expectations; input validation, protocol checks, and bound enforcement remain
  required.
- Treat schema-valid target features as unavailable for admitted benchmark runs
  until runtime preflight and qualification tests demonstrate support. Explicit
  experimental runs may exercise unqualified features to collect that evidence,
  but must preserve the trust boundaries and remain distinct from admitted runs.
- A conversion must demonstrate base failure, reference success, targeted-mutant
  rejection, malicious-candidate rejection, and documented semantic fidelity.
- Tests demonstrate the behaviors and attacks exercised, not universal security.
- Final conversion admission is binary: **Approved** or **Excluded**. Work in
  progress may be marked qualification-pending, but must not be presented as an
  approved conversion or included in admitted benchmark results.

Field-level contracts live in `securebench/schemas/benchmark.py` and generated
JSON Schemas. Architectural detail and current limitations live in
`docs/split-verification/schema.md` and
`docs/split-verification/security-model.md`.
