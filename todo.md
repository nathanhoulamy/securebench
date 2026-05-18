# SecureBench Roadmap

## Project Goal

SecureBench is a framework for evaluating AI agents against benchmarks without
letting the agent tamper with the benchmark, evaluator, tests, answer keys, or
grading infrastructure.

The core idea is to separate:

1. The untrusted agent workspace.
2. The trusted evaluator process.
3. The sandbox that executes untrusted code or candidate patches.

For the MVP, the schema and interfaces should still leave room for a stricter future flow where the agent workspace produces an artifact, then a fresh test sandbox evaluates it.

## Current Architecture Decisions

- The evaluator does not need to be a sandbox at first. It can be a trusted
  process, as long as it never directly executes agent-generated code.
- Dataset prompts should usually remain in the upstream dataset. SecureBench
  should reference dataset rows by stable ID or row address.
- Benchmark-specific logic belongs in adapters.
- SecureBench should normalize benchmark rows into a few common task types:
  - `multiple_choice`
  - `code_completion`
  - `github_patch`
- SWE-bench should not be treated as a one-off core abstraction. It should be an
  adapter on top of the generic `github_patch` primitive.
- For GitHub patch tasks, the candidate output is a Git patch from
  `git diff --binary`, not an exact match against the gold patch.
- SWE-bench compatibility means formatting the candidate patch as JSONL with:
  - `instance_id`
  - `model_name_or_path`
  - `model_patch`

## Current Files

- `docs/schema-layout.md`
  - First-pass schema layout and examples for MMLU, HumanEval, SWE-bench, and
    generic GitHub patch tasks.
- `securebench/tasks.py`
  - Normalized task dataclasses:
    - `MultipleChoiceTask`
    - `CodeCompletionTask`
    - `GitHubPatchTask`
- `securebench/adapters/base.py`
  - Base adapter interface.
- `securebench/adapters/mmlu.py`
  - Converts MMLU rows into `MultipleChoiceTask`.
- `securebench/adapters/humaneval.py`
  - Converts HumanEval rows into `CodeCompletionTask`.
- `securebench/adapters/swebench.py`
  - Converts SWE-bench Verified rows into `GitHubPatchTask`.
  - Formats SWE-bench-compatible prediction objects.
- `securebench/adapters/registry.py`
  - Provides built-in adapter lookup:
    - `get_adapter("mmlu")`
    - `get_adapter("humaneval")`
    - `get_adapter("swebench_verified")`
- `securebench/runners/base.py`
  - Base runner interface and structured `RunnerResult`.
- `securebench/runners/multiple_choice.py`
  - Exact-match runner for `MultipleChoiceTask`.
- `securebench/runners/code_completion.py`
  - HumanEval-style Python code-completion runner.
- `securebench/runners/github_patch.py`
  - Skeleton runner for clone, checkout, patch, test, and diff flows.
- `securebench/sandboxes/base.py`
  - Minimal sandbox interface and command result type.
- `securebench/sandboxes/docker.py`
  - Docker CLI sandbox backed by a temporary workspace directory.
- `securebench/policy.py`
  - First command policy gate with allow/deny lists and attempted command logs.
- `securebench/candidates/base.py`
  - Candidate production interface and `CandidateArtifact`.
- `securebench/candidates/static.py`
  - Static producer for tests and fixtures.
- `securebench/candidates/text.py`
  - Direct text producer for non-agentic prompt-to-output model calls.
- `securebench/candidates/openai_compatible.py`
  - OpenAI-compatible Chat Completions client for direct text generation.
  - Supports endpoint/base URL, model name, API key environment variable,
    timeout, temperature, max tokens, and extra request body fields.
- `securebench/candidates/workspace.py`
  - Sandboxed command producer for file/stdout artifacts.
  - Sandboxed patch producer that runs an agent command in a checked-out repo
    and uses process exit as the done signal before collecting
    `git diff --binary`.
- `securebench/evaluator.py`
  - Small orchestration layer:
    - adapt row
    - produce candidate
    - select runner
    - evaluate candidate
- `securebench/run.py`
  - Batch run executor for YAML configs.
  - Iterates dataset rows, evaluates each row, writes JSONL records, and returns
    a run summary.
- `securebench/cli.py`
  - CLI entry point:
    - `python -m securebench.cli run --config configs/mmlu-static-smoke.yaml`
    - supports `--limit` and `--output` overrides.
- `securebench/datasets.py`
  - Hugging Face dataset references and row iteration helpers.
  - Built-in helpers:
    - `mmlu_ref()` for `cais/mmlu`
    - `swebench_verified_ref()` for `princeton-nlp/SWE-bench_Verified`
  - Rows include adapter context such as `config`, `split`, and `row_idx`.
- `securebench/config.py`
  - Executable YAML config loader for benchmark run configs.
  - Builds Hugging Face dataset refs, adapters, producers, and runner
    instances.
- `docs/run-schema.md`
  - Documents the first executable run schema with an MMLU example.
- `configs/mmlu-static-smoke.yaml`
  - Static producer smoke config for local/non-network checks.
- `configs/mmlu-openai-smoke.yaml`
  - OpenAI-compatible producer smoke config for real model runs.
- `tests/test_adapters.py`
  - Tests for adapter behavior and hidden field handling.
- `tests/test_registry.py`
  - Tests for adapter registry lookup behavior.
- `tests/test_multiple_choice_runner.py`
  - Tests for multiple-choice parsing and scoring.
- `tests/test_code_completion_runner.py`
  - Tests for HumanEval script construction and sandbox interaction.
- `tests/test_github_patch_runner.py`
  - Tests for GitHub patch runner command flow.
- `tests/test_policy.py`
  - Tests for command policy checks and sandbox enforcement.
- `tests/test_candidates.py`
  - Tests for static, direct text, sandboxed command, and sandboxed patch
    candidate production.
- `tests/test_openai_compatible.py`
  - Tests for OpenAI-compatible request construction, API key handling,
    response parsing, and integration through `TextCompletionProducer`.
- `tests/test_evaluator.py`
  - Tests for runner selection and end-to-end row/task evaluation.
- `tests/test_datasets.py`
  - Tests for Hugging Face dataset calls, row context, and missing dependency
    behavior.
- `tests/test_config.py`
  - Tests for YAML config loading, validation, runtime object construction, and
    adapter/runner compatibility.
- `tests/test_run.py`
  - Tests for batch JSONL execution with injected dataset rows.
- `tests/test_cli.py`
  - Tests for CLI config loading, overrides, summaries, and error reporting.

## Important Security Invariant

Adapters may keep hidden evaluator data on normalized task objects, but
`agent_payload()` must never expose hidden fields to the agent.

Examples of hidden fields:

- MMLU: `answer`
- HumanEval: `canonical_solution`, `test`
- SWE-bench: `patch`, `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`

## Next Implementation Milestone

Build the runner and sandbox spine:

```text
dataset row
  -> adapter
  -> normalized SecureBench task
  -> runner
  -> sandbox
  -> artifact/result
  -> evaluator result
```

Start with simple local/Docker execution. Do not overbuild Firecracker, hidden
test protection, or full policy enforcement yet.

## Completed MVP Spine Tasks

1. Add adapter registry.
   - File: `securebench/adapters/registry.py`
   - Goal:
     - `get_adapter("mmlu")`
     - `get_adapter("humaneval")`
     - `get_adapter("swebench_verified")`

2. Add runner base interfaces.
   - Suggested files:
     - `securebench/runners/base.py`
     - `securebench/runners/multiple_choice.py`
     - `securebench/runners/code_completion.py`
     - `securebench/runners/github_patch.py`
   - Keep these small.
   - A runner should accept a normalized task and return a structured result.

3. Add sandbox abstraction.
   - Suggested files:
     - `securebench/sandboxes/base.py`
     - `securebench/sandboxes/docker.py`
   - Minimal methods:
     - `run(command, workdir=None, timeout=None)`
     - `write_file(path, content)`
     - `read_file(path)`
     - `extract_file(path)`
   - The first implementation can shell out to Docker CLI.

4. Implement `GitHubPatchRunner` skeleton.
   - Flow:
     1. Clone repo inside sandbox.
     2. Check out `base_commit`.
     3. Make task instructions available to the agent.
     4. Run a placeholder agent command or manually supplied patch.
     5. Extract `git diff --binary`.
     6. Run configured tests.
     7. Return patch, exit code, stdout, stderr.

5. Implement `CodeCompletionRunner` for HumanEval-style tasks.
   - Flow:
     1. Receive generated Python code.
     2. Combine prompt, completion, and hidden tests.
     3. Run in sandbox.
     4. Return pass/fail and logs.

6. Implement `MultipleChoiceRunner`.
   - Flow:
     1. Parse model output into a choice.
     2. Compare against hidden answer.
     3. Return exact-match result.

7. Add a first policy gate.
   - Suggested files:
     - `securebench/policy.py`
   - Initial scope:
     - allow/deny command names
     - log every attempted command
   - Later scope:
     - filesystem restrictions
     - network restrictions
     - browser/tool restrictions
     - artifact export restrictions

## Immediate Next Tasks

1. Define the `securebench-agent` command contract.
   - Inputs:
     - task file path
     - repo path for workspace tasks
     - output path for text/code artifacts when needed
   - Completion signal:
     - process exit or timeout
   - Outputs:
     - text artifact file for non-patch sandboxed workflows
     - repo edits for patch workflows

2. Run a real MMLU smoke benchmark from Hugging Face.
   - Install the `hf` optional dependency.
   - Run `configs/mmlu-static-smoke.yaml` against a small limit to verify
     dataset loading and JSONL output.
   - Run `configs/mmlu-openai-smoke.yaml` once `OPENAI_API_KEY` is configured.

3. Add integration tests for Docker-backed execution.
   - Start with `CodeCompletionRunner` and a tiny Python task.
   - Skip when Docker is unavailable.

4. Harden patch production/evaluation separation.
   - `SandboxedPatchProducer` should produce patches in an agent workspace.
   - `GitHubPatchRunner` should evaluate patches in a clean test sandbox.

5. Harden `GitHubPatchRunner` from skeleton to useful MVP.
   - Choose or build a Docker image with `git` and language runtime support.
   - Support setup commands before tests.
   - Decide how test commands are derived from task metadata or caller config.
   - Preserve and expose command results in a clearer artifact structure.

6. Add SWE-bench prediction export helper.
   - Convert `GitHubPatchRunner` output into JSONL using
     `SWEBenchVerifiedAdapter.format_prediction()`.

7. Expand policy integration.
   - Wrap Docker sandboxes with `PolicySandbox` in evaluator/orchestrator paths.
   - Add policy config parsing once benchmark config files exist.

## MVP Scope

The MVP should prove the end-to-end loop, not perfect isolation:

- MMLU exact-match task can run.
- HumanEval generated code can be tested in a sandbox.
- Generic GitHub patch task can clone, patch, diff, and test.
- SWE-bench adapter can produce a `GitHubPatchTask`.
- SWE-bench candidate patch can be formatted as JSONL.

## Future Hardening

After the MVP works:

- Split agent workspace and test sandbox.
- Evaluate patches in a fresh sandbox.
- Add protected test path checks.
- Hash tests before and after agent execution.
- Prevent agent writes to evaluator/test infrastructure.
- Add stricter network controls.
- Add browser/file/API policy gates.
- Add pinned dataset revisions for reproducibility.
- Add audit logs for every tool call and sandbox operation.

## Useful Mental Model

Adapters translate benchmark rows.

Runners execute normalized task types.

Sandboxes isolate untrusted execution.

The evaluator scores results but does not run agent code directly.

The policy gate mediates what the agent is allowed to do.
