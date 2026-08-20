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

## Priority 3: implement one Trusted Helper

Use `securebench.http-request-recorder/v1` as the first vertical slice because it exercises the
external-state pattern without requiring a general-purpose database or process broker.

Required properties:

- a fresh Trusted Helper instance and fresh credential for every Evaluation;
- candidate-facing data plane on an internal Evaluation network only;
- host-only control/evidence plane;
- Adapter receives only scoped Helper Access;
- bounded requests, headers, bodies, records, and time;
- host Evaluation ID on every recorder record;
- no route from Evaluation to the public internet;
- teardown failures become infrastructure errors.

Add adversarial tests for stale cross-Evaluation state, forged credentials, direct control-plane
access, record truncation, oversized bodies, host-header/SNI confusion, helper crashes, and evidence
from the wrong Evaluation ID.

Definition of done: a file-bundle protocol row with `trusted_helpers` executes under
`strict-split/v1`; the same Trusted Helper declaration no longer fails preflight; fresh-Evaluation
isolation is demonstrated in real Docker.

## Priority 4: Output Artifacts

Once Challenge/Evaluation correlation exists:

1. Capture only Adapter-declared Output Artifacts from the same disposable Evaluation.
2. Apply byte/tree/path bounds before reading content into trusted memory.
3. Parse with registered passive parsers; never import or execute the artifact.
4. Bind parsed values, digests, truncation, and failures to the Challenge ID and Evaluation ID in
   Challenge Evidence.
5. Ensure Output Artifacts never appear in public results except as approved digests/summaries.

Definition of done: a protocol check with `output_artifacts` composes Observation, Trusted Helper,
and Output Artifact evidence into one Oracle evaluation and remains isolated across Evaluations.

## Priority 5: filesystem overlays

Do not implement capture until the canonical representation is reviewed. Specify:

- baseline identity and allowed include roots;
- additions, modifications, deletions, modes, ownership normalization, and directories;
- safe internal symlinks, hardlinks, path length/depth, and special-file rejection;
- protected system regions and credential/package-manager state;
- deterministic capture, content addressing, replay, and cleanup.

Then implement stopped-state capture, clean-baseline replay, passive `source.path`, protocol replay,
and adversarial tests. This remains the highest-risk candidate transport.

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

## Working rules for a future agent

- Begin on `split-verification-v2`, not `main`.
- Read `current.md`, the recommended schema, `docs/split-verification/security-model.md`, and
  `securebench/execution_profiles.py` before editing.
- Treat schema-valid and executable as separate states; add capability support explicitly rather
  than silently falling back.
- Preserve unrelated user files and inspect `git status` before editing.
- Use `rg` for discovery and `apply_patch` for edits.
- Keep batches small, add failure-path tests, and test with real Docker when isolation changes.
- Before handoff, run the commands recorded in `current.md`, inspect leaked Docker resources, build
  a wheel, review `git diff --check`, and push only to the feature branch.
