# SecureBench v2 next steps

This plan starts from [`current.md`](current.md). Preserve the core architecture: structural
visibility lanes, one durable candidate, check-centric verification, preflight capability gating,
and an Oracle-owned verdict. Do not restore the legacy family-specific verifier path.

## Completed 2026-08-20: small schema/runtime alignment pass

Keep the first follow-up intentionally small and finish it before starting another Candidate or
Trusted Helper engine.

1. [x] Add duplicate-key-rejecting loaders for benchmark YAML, row JSONL, adapter YAML, and Oracle
   YAML. Return sanitized `ConfigError` or `VerificationInfrastructureError` failures as
   appropriate.
2. [x] Make `securebench.strict-json/v1` use the same finite, duplicate-key-free JSON semantics as the
   protocol transport.
3. [x] Resolve the `allow_internal_symlinks` ownership question:
   - document it in the row-schema field reference if row-level opt-in is intended; or
   - remove it from the author-facing schema and place the policy in a reviewed candidate/parser
     contract.
4. [x] Add a compact executable-capability matrix test so every intentionally unsupported schema
   branch is proven to fail preflight before Agent execution.
5. [x] Re-run the full suite, robustness audit, schema generation check, wheel build, and live Docker
   protocol test.

Definition of done: authoring ambiguity is rejected consistently, the documentation and executable
schema agree, and no new schema feature is falsely presented as executable.

## Completed 2026-08-20: complete the `git_patch` vertical slice

This is the most direct way to make the `repo_patch` family and DeepSWE-style rows executable.
Reuse the existing capture and replay primitives rather than designing a second candidate format.

Required work:

1. [x] Define how the digest-pinned image/workdir provides the baseline repository and prove it is at
   `input.base_commit` before Agent execution.
2. [x] Derive a canonical binary-capable patch from the stopped Agent workspace; do not trust an
   Agent-authored patch file or stdout.
3. [x] Connect `capture_production()` to `capture_git_patch()` with framework-owned protected paths,
   author allow/exclude patterns, materialized file/byte bounds, and exact baseline identity.
4. [x] Introduce one candidate replay/materialization dispatcher used by verification instead of
   hard-coding `replay_file_bundle()` in the protocol runner.
5. [x] Replay patches into a clean repository baseline for every protocol case.
6. [x] Implement passive `artifact.source.path` observation for repository-relative paths without
   executing candidate code.
7. [x] Bind resume validation and result provenance to the patch candidate and its baseline.

Tests must cover wrong base commits, dirty baselines, binary patches, rename/delete/symlink cases,
protected-test modifications, path escapes, oversized materialized results, replay mismatch, and a
real fresh-Docker protocol case.

Definition of done: a minimal `repo_patch` row without Trusted Helpers runs end to end through
candidate production, stopped-state patch capture, fresh replay, protocol or artifact evidence,
Oracle verdict, persistence, cleanup, and resume.

## Completed 2026-08-20: establish the full protocol component/evidence contracts

Do this before implementing several Trusted Helpers independently; otherwise evidence and participant
APIs will need repeated redesign.

1. [x] Version an expanded Adapter format defining Challenge/Observation schemas, Evaluation
   Participants, required Trusted Helpers, Helper Access, Output Artifacts, and reduced bounds.
2. [x] Add host-owned Challenge IDs and Evaluation IDs to Challenge Evidence while keeping opaque
   Challenge context host-only.
3. [x] Define a Trusted Helper Catalog contract with fixed capabilities, settings validation, limit
   reduction, reset behavior, credential handling, and evidence schemas.
4. [x] Separate Candidate failures from Adapter, Trusted Helper, and framework infrastructure
   failures in Challenge Evidence.
5. [x] Keep public result serialization unchanged unless a reviewed bounded summary is explicitly
   required.

Definition of done: component contracts are typed and versioned, evidence from one Evaluation
cannot be mis-correlated, and unsupported component capabilities fail preflight.

## Implemented 2026-08-21: first Trusted Helper vertical slice

Use `securebench.http-request-recorder/v1` as the first vertical slice because it exercises the
external-state pattern without requiring a general-purpose database or process broker.

Required properties:

- [x] a fresh Trusted Helper instance and fresh credential for every Evaluation;
- [x] candidate-facing data plane on an internal Evaluation network only;
- [x] host-only control/evidence plane;
- [x] Adapter receives only scoped Helper Access;
- [x] bounded requests, headers, bodies, records, evidence, and lifecycle operations;
- [x] host Challenge and Evaluation IDs on every recorder record;
- [x] no route from Evaluation to the public internet;
- [x] teardown failures become Trusted Helper infrastructure errors.

Add adversarial tests for stale cross-Evaluation state, forged credentials, direct control-plane
access, record truncation, oversized bodies, host-header/SNI confusion, helper crashes, and evidence
from the wrong Evaluation ID.

The file-bundle protocol path, preflight admission, Helper Access, evidence correlation,
adversarial host-side tests, and the two-Evaluation live-Docker isolation test are complete. The
live pass demonstrated fresh request sequence/state and left no helper container or Evaluation
network behind.

## Implemented 2026-08-21: Output Artifacts

Once Challenge/Evaluation correlation exists:

1. [x] Capture only Adapter-declared Output Artifacts from the same disposable Evaluation.
2. [x] Apply byte/tree/path bounds before reading content into trusted memory.
3. [x] Parse with registered passive parsers; never import or execute the artifact.
4. [x] Bind parsed values, digests, and failures to the Challenge ID and Evaluation ID in
   Challenge Evidence.
5. [x] Ensure Output Artifacts never appear in public results except through the existing internal
   Challenge Evidence digest.

Definition of done: a protocol check with `output_artifacts` composes Observation, Trusted Helper,
and Output Artifact evidence into one Oracle evaluation and remains isolated across Evaluations.

The host and live-Docker tests cover the combined Observation, HTTP recorder, and Output Artifact
path across two fresh Evaluations. The current backend enforces an aggregate 16 MiB / 4,096-entry
collector capacity per Evaluation in addition to Adapter maxima and row-reduced limits.

## Completed 2026-08-21: portability and lifecycle hardening

1. [x] Treat case and Unicode-normalization aliases conservatively at host/container path
   boundaries, while retaining exact containment where Linux workdir semantics require it.
2. [x] Bound hostile directory enumeration before sorting for Git stopped-worktree capture and
   passive file-tree observation.
3. [x] Add executable backend capacities above row-authored candidate and passive-artifact bounds.
4. [x] Bound Docker and Oracle startup/cleanup operations and surface unreaped resources as
   infrastructure failures.
5. [x] Remove the obsolete Python-side Oracle case/evidence compatibility aliases while retaining
   the documented Oracle wire ABI.
6. [x] Add defense-in-depth validation at Output Artifact collection and reject noncanonical,
   NUL-containing, reserved, or mount-overlapping paths before collection.

The remaining resource-control gap is the host-backed Agent workspace itself: it needs a
framework-owned disk quota or deployment-enforced isolated storage before SecureBench can claim
that a running Agent cannot exhaust host disk capacity. Trusted resource-tree traversal and Git
baseline operations also need explicit admission/runtime entry and wall-clock budgets before the
framework can safely process arbitrarily large admitted packs.

Make candidate-store capture transactional, or add a reference-aware garbage collector, so a
capture rejected after writing some blobs cannot accumulate orphaned artifacts across interrupted
or repeatedly retried runs. Keep deletion conservative because blobs may be shared by valid
candidate manifests.

Add one coherent total Evaluation budget rather than unrelated magic constants: cap cases and
cumulative case time per row, bound combined Trusted Helper and Output Artifact evidence, and make
the maximum serialized Oracle request an executable preflight invariant. The row's reduced limits
should remain configurable below those framework capacities.

## Completed 2026-08-21: architecture-wide review after the major rework

- Resume, tester YAML, and candidate manifests now use strict duplicate-key-free decoders; corrupt
  NUL-padded records and numeric overflows are rejected rather than reused or allowed to crash a run.
- Candidate blobs/manifests, tester configuration, and Oracle manifests have backend read bounds.
- Artifact, Challenge, and Output Artifact evidence enforce bounded identities, finite JSON,
  correlated status/error fields, and explicit source metadata.
- Passive file-bundle tree evidence uses the tree's own digest and verifies every referenced blob
  before it reaches the Oracle.
- HTTP recorder evidence is revalidated against the recorder's response-state machine, not merely
  against broad status-code ranges.
- Full warning-strict, real-Docker protocol, self-audit, schema regeneration, packaging, and leak
  checks passed. The unresolved resource budgets above remain explicit future work.

## Priority 5: filesystem overlays — Phase 7 remains

The accepted Phase 1 contract is documented in
[`docs/split-verification/filesystem-overlay-v1.md`](docs/split-verification/filesystem-overlay-v1.md).
It fixes the proposed v1 payload, trust boundary, protected paths, normalized semantics, bounds,
capture/replay order, failure ownership, and security checklist. This documentation does not make
the feature executable. The Phase 2 schema/preflight gate migrates the unused limit names, validates
static root and mount policy, and retains the unconditional non-executable gate.

The Phase 3 review candidate adds the required tester-owned
`docker.overlay_workspace_bytes` capacity, binds it to resume provenance, and implements the
Linux-only sparse-ext4/loop-device workspace exposed through one Docker volume with distinct root
subpaths. Its capability probe requires reviewed Docker storage, proves enforced `ENOSPC`, recovers
stale interrupted state, and checks complete cleanup. Overlay execution remains disabled pending
review.

Phases 4 and 5 add canonical transactional capture and a standalone stopped-Agent capture
orchestrator. Phase 6 now adds fresh Evaluation reconstruction: it materializes and verifies the
pinned baseline, applies deletions/directories/files/links in the reviewed order, rescans the final
state before Candidate code runs, resolves absolute passive artifact paths, mounts reconstructed
roots into protocol Evaluations, collects overlay Output Artifacts, and destroys the fresh quota
workspace after every observation or Challenge.

The warning-strict local suite passes with `493 passed, 6 skipped`; the robustness audit, schema
generation, compilation, package build, and `git diff --check` also pass. Host-side tests cover
exact replay, forged baselines, corrupt chunks, traversal and symlink attacks, row-limit
revalidation, absolute artifact observation, Output Artifacts, cleanup, and fresh two-Challenge
isolation. A real two-volume Docker Evaluation test is present but intentionally skipped outside
the explicit root-Linux qualification environment.

### Next on macOS: finish the Phase 7 implementation

Continue development on the normal macOS workspace; the final Linux qualification is recorded in
its own section below and must not block other implementation work.

1. [x] Connect the Phase 5 quota-backed Agent capture orchestrator to the normal tester/harness
   path. Command, Codex, and Claude Code now stage public task inputs on a read-only framework
   mount, use only declared quota roots for durable writes, and keep CLI state on the bounded
   container tmpfs. Provider credentials remain behind the host relay. Focused tests prove the
   runner returns exactly one overlay Candidate and cleans Agent state after success, failure,
   rejection, timeout, preflight failure, infrastructure failure, and interruption.
2. [x] Implement and review the final capability-gated execution path. The run lock now protects a
   one-time probe of the exact Agent-overlay storage root before the harness is constructed, and
   the runner requires the resulting internal capability token before capture. macOS tests mock
   the quota probe and prove the supported sequence is probe then Agent, while unsupported or
   malformed host/storage facts fail before Agent execution. The source-controlled native
   qualification flag remains false, with no tester-config or environment-variable bypass, so the
   author-facing overlay path stays non-executable until the deferred native qualification passes.
3. Finish all remaining deterministic, mocked-Docker, failure-path, adversarial, schema, audit, and
   packaging checks available on macOS. When a test fundamentally requires native Linux, add it as
   an explicitly gated test and record it in the final qualification section instead of stopping
   development.
4. Continue with later roadmap work after the macOS implementation is complete. Do not wait for a
   Linux host between features; collect native-only qualification work for the single final pass.

## Later work

- Implement `batched-split/v1` only as a visibly weaker, separately reported fallback after strict
  Trusted Helper isolation is mature.
- Build admission tooling for base failure, reference success, targeted-mutant rejection,
  malicious-candidate rejection, and semantic-fidelity records.
- Define component registry governance and review/publication policy for pack-local adapters and
  Oracles.
- Add stronger Oracle OS confinement and, if required, signed result records.
- Convert more benchmark rows only when their required Candidate, check, and Trusted Helper features are
  executable; do not weaken preflight to admit them early.

## Final Linux-host qualification — deliberately deferred until the end

This is the last project step, not a blocker for ongoing macOS development. Add future
Linux-only checks to this section and continue with the next macOS-capable roadmap item.

Use a real root Linux host, not Docker Desktop on macOS. It must provide loop-backed ext4,
mount/umount, Docker `overlay2`, Docker volume subpaths, and every required digest-pinned test image
locally. Then:

1. Run the overlay backend probe and prove physical `ENOSPC`, volume-subpath behavior, stale-state
   recovery, and cleanup after success, failure, timeout, and interruption.
2. Run real quota-backed stopped-Agent capture through every supported normal harness path.
3. Run at least two real overlay Evaluations and prove distinct volumes, identical pinned-baseline
   reconstruction, no cross-Evaluation state, exact artifact/protocol behavior, and final-state
   digest enforcement.
4. Run all other explicitly gated Linux/Docker integration tests accumulated during development.
5. Inspect for leaked Agent/Evaluation/helper containers, Docker networks and volumes, loop mounts,
   backing files, temporary state, and credentials.
6. Run the warning-strict full suite, robustness audit, schema-generation check, package build, and
   `git diff --check` on Linux.
7. Only after every native gate passes, enable the reviewed overlay capability path and any other
   deferred Linux-only features. Update `current.md`, this roadmap, security documentation, and the
   capability matrix with the final tested state.

## Working rules for a future agent

- Begin on `split-verification-v2`, not `main`.
- Read `current.md`, the recommended schema, `docs/split-verification/security-model.md`, and
  `securebench/execution_profiles.py` before editing.
- Treat schema-valid and executable as separate states; add capability support explicitly rather
  than silently falling back.
- Develop and review everything possible on macOS. A missing native Linux environment is not an
  intermediate blocker: add the gated integration test and its requirement to the final Linux-host
  qualification section, then continue the roadmap.
- Preserve unrelated user files and inspect `git status` before editing.
- Use `rg` for discovery and `apply_patch` for edits.
- Keep batches small and add deterministic and failure-path tests on macOS. Add real-Docker/Linux
  tests when isolation changes, but defer running Linux-only tests to the single final qualification
  pass.
- Before handoff, run the commands recorded in `current.md`, inspect leaked Docker resources, build
  a wheel, review `git diff --check`, and push only to the feature branch.
