# SecureBench Schema Layout

This document defines the first-pass schema model for SecureBench. The goal is
to keep benchmark integration general: dataset-specific details live in
adapters, while task contracts reference dataset rows and override behavior only
when needed.

## Core Concepts

SecureBench has three layers:

1. `benchmark_adapter`: maps an existing benchmark dataset into SecureBench's
   plain normalized task spec.
2. `task_ref`: points to one dataset row or benchmark instance.
3. `task_contract`: optional per-task overrides for policy, parsing,
   execution, and evaluation.

The normalized task spec is the developer-facing adapter output. It is plain
dictionary/JSON-compatible data:

```yaml
id: task-id
benchmark_id: benchmark-name
task_type: multiple_choice
metadata: {}
resources:
  question:
    value: "2 + 2?"
    visibility: public
  answer:
    value: 2
    visibility: hidden
```

SecureBench converts this spec into internal task/resource objects. Custom
adapters should not need to import those internal classes.

The prompt usually belongs to the upstream dataset, not to SecureBench. A
SecureBench task should reference a row by stable ID when possible, or by
dataset/config/split/row index when no stable ID exists.

## Runtime Contexts

Repository tasks separate patch production from evaluation. A producer owns the
agent workspace used to inspect and edit a checkout, while a runner owns the
test sandbox used to apply the candidate patch and execute grading commands.
Each sandbox instance may keep state across commands for one task attempt, but
production configs should create fresh sandbox instances at task boundaries.

```text
agent_workspace:
  The sandbox where the agent reads task-visible files, edits code, and runs
  allowed tools.

test_sandbox:
  The sandbox where submitted code, generated code, or patches are executed.
  For repository patch tasks, this should be a fresh sandbox that receives only
  the candidate patch plus evaluator-controlled hidden patches and commands.

evaluator:
  A trusted process that parses outputs, checks schemas, starts sandbox runs,
  and scores results. It should not execute agent-generated code directly.
```

## Top-Level Benchmark Adapter

```yaml
schema_version: 0.1

benchmark:
  id: string
  name: string
  extends: one_of:
    - multiple_choice
    - code_generation
    - github_patch
    - custom

dataset:
  provider: huggingface | local_jsonl | local_csv | custom
  name: string
  config: optional_string
  split: string
  revision: optional_string
  id_field: optional_string

agent_view:
  include: list[string]
  exclude: list[string]

parser:
  type: string

output:
  type: string

policy:
  tools:
    allow: list[string]
    deny: list[string]
  network:
    allow: boolean
  filesystem:
    readonly_paths: list[string]
    writable_paths: list[string]
    forbidden_paths: list[string]

execution:
  agent_workspace:
    sandbox: docker | firecracker | local_dev | custom
  test_sandbox:
    sandbox: docker | firecracker | same_as_agent_workspace | custom
  setup:
    commands: list[string]
  test:
    commands: list[string]

evaluation:
  type: exact_match | test_command | pass_at_k | custom
```

## Per-Task Reference

Stable IDs are preferred.

```yaml
benchmark: swebench_verified

task_ref:
  id: astropy__astropy-12907
```

Datasets without stable IDs can use a row address.

```yaml
benchmark: mmlu

task_ref:
  config: abstract_algebra
  split: test
  row_idx: 0
```

`split` is the dataset partition, such as `train`, `validation`, `dev`, or
`test`.

## Per-Task Overrides

Most tasks should not need overrides. Use them for unusual rows only.

```yaml
benchmark: example_benchmark

task_ref:
  id: example-123

overrides:
  policy:
    tools:
      allow:
        - shell.exec
  execution:
    test:
      commands:
        - pytest tests/specific_test.py
```

## Task Type: Multiple Choice

Use this for MMLU-like benchmarks where a row contains a question, choices, and
an answer label.

```yaml
schema_version: 0.1

benchmark:
  id: mmlu
  name: MMLU
  extends: multiple_choice

dataset:
  provider: huggingface
  name: cais/mmlu
  config: abstract_algebra
  split: test
  revision: pinned_dataset_revision

agent_view:
  include:
    - question
    - choices
    - subject
  exclude:
    - answer

parser:
  type: multiple_choice_letter

output:
  type: dataset_class_label
  label_field: answer

policy:
  tools:
    allow: []
    deny: ["*"]
  network:
    allow: false

evaluation:
  type: exact_match
  expected_field: answer
```

Example task:

```yaml
benchmark: mmlu

task_ref:
  config: abstract_algebra
  split: test
  row_idx: 0
```

## Task Type: Code Generation

Use this for HumanEval-like benchmarks where the model emits code and the
framework executes it against tests.

```yaml
schema_version: 0.1

benchmark:
  id: humaneval
  name: HumanEval
  extends: code_generation

dataset:
  provider: huggingface
  name: openai/openai_humaneval
  config: openai_humaneval
  split: test
  id_field: task_id
  revision: pinned_dataset_revision

agent_view:
  include:
    - task_id
    - prompt
    - entry_point
  exclude:
    - canonical_solution
    - test

parser:
  type: python_code

output:
  type: source_code
  language: python

policy:
  tools:
    allow: []
    deny: ["*"]
  network:
    allow: false

execution:
  test_sandbox:
    sandbox: docker
  test:
    adapter: humaneval
    code_field: completion
    prompt_field: prompt
    test_field: test
    entry_point_field: entry_point

evaluation:
  type: pass_at_k
  k: 1
```

Example task:

```yaml
benchmark: humaneval

task_ref:
  id: HumanEval/0
```

## Task Type: GitHub Patch Task

Use this for SWE-bench-like benchmarks and other GitHub repository repair
benchmarks. This is intentionally generic; SWE-bench is just one adapter.

```yaml
schema_version: 0.1

benchmark:
  id: swebench_verified
  name: SWE-bench Verified
  extends: github_patch

dataset:
  provider: huggingface
  name: princeton-nlp/SWE-bench_Verified
  split: test
  id_field: instance_id
  revision: pinned_dataset_revision

github_patch:
  repo:
    field: repo
  base_commit:
    field: base_commit
  instructions:
    field: problem_statement

agent_view:
  include:
    - repo
    - base_commit
    - problem_statement
    - hints_text
    - version
  exclude:
    - patch
    - test_patch
    - FAIL_TO_PASS
    - PASS_TO_PASS

parser:
  type: git_diff

output:
  type: git_patch
  format: unified_diff
  include_binary: true

policy:
  tools:
    allow:
      - shell.exec
      - file.read
      - file.write
    deny: []
  network:
    allow: false

execution:
  agent_workspace:
    sandbox: docker
  test_sandbox:
    sandbox: same_as_agent_workspace
  setup:
    adapter: swebench
  test:
    adapter: swebench
    fail_to_pass_field: FAIL_TO_PASS
    pass_to_pass_field: PASS_TO_PASS

evaluation:
  type: test_command
  success:
    exit_code: 0
```

Example task:

```yaml
benchmark: swebench_verified

task_ref:
  id: astropy__astropy-12907
```

## Generic GitHub Patch Task Without SWE-bench

```yaml
schema_version: 0.1

benchmark:
  id: example_github_bugs
  name: Example GitHub Bug Benchmark
  extends: github_patch

dataset:
  provider: local_jsonl
  name: data/example_github_bugs.jsonl
  split: test
  id_field: task_id

github_patch:
  repo:
    field: repo_url
  base_commit:
    field: commit_sha
  instructions:
    field: issue_text

agent_view:
  include:
    - repo_url
    - commit_sha
    - issue_text
  exclude:
    - solution_patch
    - hidden_tests

output:
  type: git_patch
  format: unified_diff
  include_binary: true

execution:
  agent_workspace:
    sandbox: docker
  test_sandbox:
    sandbox: same_as_agent_workspace
  setup:
    commands:
      - pip install -e .
  test:
    commands:
      - pytest

evaluation:
  type: test_command
  success:
    exit_code: 0
```

## Future Hardening Hooks

These are intentionally not required for the MVP.

```yaml
integrity:
  protect_tests: boolean
  protected_paths: list[string]
  pre_run_hashes:
    - path: tests/
      sha256: string
  post_run_assertions:
    - type: path_hash_equals
      path: tests/test_example.py
      sha256: string

artifact_flow:
  extract_from_agent_workspace:
    - git_diff
  evaluate_in_fresh_sandbox: boolean
```

The secure future flow for repository tasks should be:

1. Agent edits files in `agent_workspace`.
2. SecureBench extracts `git diff --binary`.
3. SecureBench creates a fresh `test_sandbox`.
4. SecureBench applies the patch.
5. SecureBench applies hidden tests, if any.
6. SecureBench runs tests and reports results to the evaluator.

The local smoke path uses separate producer and runner sandbox instances by
default. Tests should not run directly in a reused agent workspace for real
benchmark evaluation.
