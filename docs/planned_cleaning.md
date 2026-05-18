# Planned Legacy Cleanup

This document lists cleanup work to do only after the standardized
benchmark-pack and tester-harness path is complete, tested, and able to cover
the current compatibility use cases. Until then, keep these paths working.

## Cleanup Gate

Do not remove compatibility code until all of these are true:

- benchmark-pack loading, compilation, harness execution, family verifiers, and
  tester YAML CLI execution are wired end to end.
- MMLU, HumanEval, and SWE-bench-style evaluations have been ported to
  benchmark packs or intentionally dropped.
- regression fixtures exist for the replacement packs and verifier behavior.
- result records from the new path contain enough metadata to replace old run
  outputs for debugging and comparison.

## Run Config and Dataset Compatibility

The old Hugging Face-oriented run path has been removed now that
`securebench run --config` expects tester YAML:

- `securebench/config.py` and its old `dataset`, `adapter`, `producer`,
  `runner`, and `environment` run schema.
- `securebench/runtime.py` builders for old adapters, producers, and runners.
- `securebench/run.py` orchestration that assumed the old config structure.
- legacy run-schema documentation and configs.
- tests whose only purpose was preserving the old run schema.

Before removal, migrate any still-useful validation ideas into the new
benchmark manifest, tester config, harness, or family-verifier layers.

## Adapter Layer

Remove or shrink the old raw-dataset adapter system after important benchmarks
have been ported:

- `securebench/adapters/` classes for MMLU, HumanEval, and SWE-bench Verified,
  unless kept as explicit import/porting tools outside the main execution
  path.
- adapter registry tests and adapter-specific task-spec fixtures.
- adapter-specific visibility mapping that duplicates benchmark-pack family
  schemas.

If we keep any porting helpers, they should output standard
`manifest.yaml`/JSONL rows rather than internal `SecureBenchTask` specs.

## Legacy Candidate Producers

Review old candidate producers after harnesses are complete:

- `StaticCandidateProducer` may remain as a lightweight test utility.
- `TextCompletionProducer` and OpenAI-compatible producer code can be removed
  from the main path if direct model API evaluation is no longer a goal.
- `SandboxedCommandProducer` can likely merge into or be replaced by the new
  command harness.
- `WorkspaceAgentPatchProducer` and the standalone `securebench_agent` runtime
  should be removed only if Codex/Claude Code/command harnesses fully replace
  the built-in agent workflow.

Keep small reusable primitives only when they serve the standardized harness
interface directly.

## Task and Verifier Naming

Normalize legacy task names once replacement verifiers exist:

- replace `github_patch` with standard `repo_patch` throughout public-facing
  code.
- remove `GitHubPatchTask` if generic `SecureBenchTask` plus family contracts
  are sufficient.
- replace `GitHubPatchTask`/patch-specific assumptions with a `repo_patch`
  family verifier.
- ensure `CandidateArtifact.for_task(...)` no longer needs legacy
  task-type aliases.

This should happen after Step 7 proves that standard family verifiers can score
the active families without relying on legacy task classes.

## Materialization and Sandbox Primitives

Keep the newer visibility-aware materialization and path-policy code. Remove
older or redundant primitives only after they no longer serve tests or legacy
paths:

- decide whether `ResourceMaterializer` is still needed once
  `VisibilityAwareMaterializer` is used everywhere.
- remove old framework-owned path assumptions that conflict with benchmark-pack
  asset/mount semantics.
- keep `DockerSandbox` hardening and read-only bind mount support.
- keep `HostSandbox` only if host-mode harness execution remains supported.

## Documentation Cleanup

After legacy removal, update docs to make the new standard the only path:

- move compatibility notes out of the main roadmap.
- replace old MMLU/HumanEval/SWE-bench examples with benchmark-pack examples.
- remove references to the old run config, raw adapters, direct model
  producers, and `github_patch`.
- keep a short migration note only if external users still need to translate
  old configs.
