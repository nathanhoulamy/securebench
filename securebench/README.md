# SecureBench Source Layout

The active package is organized around the benchmark-pack execution pipeline:

- `benchmark_pack.py`, `benchmark_compiler.py`, `tasks.py`, and `resources.py`
  define the core benchmark/task model.
- `families/` contains benchmark family contracts and row schema validators.
  Add new benchmark family schemas here, one module per family.
- `tester_config.py`, `tester_run.py`, and `cli.py` parse tester YAML and run
  benchmark packs end to end.
- `harnesses/` contains candidate-producing harness implementations. Add new
  harness types here, one module per implementation family.
- `candidates/` contains candidate artifact interfaces and extraction logic.
- `verifiers/` contains family verifiers. Add new benchmark-family verifiers
  here, one module per family.
- `sandboxes/` contains execution backends and sandbox command policy wrappers.
- `workspaces/` contains resource materialization and path-policy checks for
  agent, test-sandbox, and evaluator workspaces.

Top-level files are intentionally reserved for central benchmark concepts and
runner entry points. Implementation families live in packages so the available
extension points are visible from the directory tree.

# More In Depth

- `securebench/README.md`: Explains the source layout and where each major concept lives.
- `securebench/__init__.py`: Public package exports for core run and verifier APIs.
- `securebench/benchmark_pack.py`: Loads benchmark pack manifests and JSONL task rows.
- `securebench/benchmark_compiler.py`: Converts raw benchmark rows into normalized `SecureBenchTask` objects.
- `securebench/tasks.py`: Defines normalized task models and helpers for reading task resources.
- `securebench/resources.py`: Defines resource visibility, redaction, and component-specific resource views.
- `securebench/tester_config.py`: Parses and validates tester YAML config files.
- `securebench/tester_run.py`: Runs a tester config end to end: load pack, run harness, verify, write JSONL.
- `securebench/cli.py`: Command-line entry point for running tester YAML configs.
- `securebench/env.py`: Loads dotenv-style environment files.
- `securebench/errors.py`: Shared SecureBench configuration error type.

## Candidates

- `securebench/candidates/__init__.py`: Public exports for candidate artifact APIs.
- `securebench/candidates/base.py`: Defines `CandidateArtifact` and `CandidateProducer`.
- `securebench/candidates/extraction.py`: Extracts family-shaped candidates from stdout, files, or git diffs.

## Families

- `securebench/families/__init__.py`: Public exports for family contracts and schema validators.
- `securebench/families/base.py`: Defines `FamilyContract`, candidate kinds, validator types, and shared schema helper functions.
- `securebench/families/registry.py`: Registers known family contracts and dispatches row validation to each family module.
- `securebench/families/multiple_choice.py`: Validates `multiple_choice` row input and eval schema.
- `securebench/families/short_answer.py`: Validates `short_answer` row input and eval schema.
- `securebench/families/free_response.py`: Validates `free_response` row input and eval schema.
- `securebench/families/code_completion.py`: Validates `code_completion` row input and eval schema.
- `securebench/families/repo_patch.py`: Validates `repo_patch` row input and eval schema.

## Harnesses

- `securebench/harnesses/__init__.py`: Public exports for harness implementations and factory.
- `securebench/harnesses/registry.py`: Builds the right harness producer from tester YAML.
- `securebench/harnesses/command.py`: Implements the host/container command harness.
- `securebench/harnesses/codex.py`: Implements the Codex mounted harness and overlay handling.
- `securebench/harnesses/shared.py`: Shared harness helpers for workspaces, config parsing, and cleanup.

## Verifiers

- `securebench/verifiers/__init__.py`: Public exports for verifier APIs and implemented verifiers.
- `securebench/verifiers/base.py`: Defines the verifier interface and `VerificationResult`.
- `securebench/verifiers/registry.py`: Chooses the verifier for a benchmark family.
- `securebench/verifiers/code_completion.py`: Verifies Python code-completion candidates using inline tests.
- `securebench/verifiers/multiple_choice.py`: Verifies text candidates against hidden multiple-choice answers.

## Sandboxes

- `securebench/sandboxes/__init__.py`: Public exports for sandbox backends and policy wrappers.
- `securebench/sandboxes/base.py`: Defines the sandbox interface and command result model.
- `securebench/sandboxes/host.py`: Runs commands and file operations on the host within a workspace root.
- `securebench/sandboxes/docker.py`: Runs commands and file operations inside Docker containers.
- `securebench/sandboxes/policy.py`: Adds command allow/deny policy enforcement around sandboxes.

## Workspaces

- `securebench/workspaces/__init__.py`: Public exports for workspace materialization and path policy.
- `securebench/workspaces/materialization.py`: Materializes public/eval/hidden resources into workspace files.
- `securebench/workspaces/path_policy.py`: Validates workspace paths and prevents unsafe/cross-visibility mounts.
