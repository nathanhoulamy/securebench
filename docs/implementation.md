# SecureBench Refactoring Roadmap

This document tracks the high-level implementation steps for moving SecureBench
toward the revised benchmark-pack and tester-harness standard. Details should be
filled in as each step is designed and implemented.

## 1. Benchmark Pack Loading

Add a family-agnostic loader for benchmark packs made of a `manifest.yaml` file
plus JSONL benchmark rows. This is separate from the current executable run config,
while keeping the existing Hugging Face adapter flow available as a
compatibility path.

The first pass supports this manifest envelope:

```yaml
id: example-pack
version: 1

defaults:
  family: terminal_task
  environment:
    image: python:3.11-slim
    setup:
      - pip install -e .
    network: none
    timeout_seconds: 30

asset_roots:
  public: assets/
  eval: hidden/

asset_defaults:
  read_only: true
```

Each JSONL row is normalized to the common author-facing envelope:

```json
{
  "id": "task-id",
  "family": "terminal_task",
  "input": {},
  "assets": [],
  "eval": {},
  "environment": {},
  "metadata": {}
}
```

Step 1 applies only common defaults and validation:

- `row.family` overrides `defaults.family`; one of them is required.
- `row.environment` shallow-merges over `defaults.environment`.
- missing `input`, `eval`, `environment`, and `metadata` become empty objects.
- missing `assets` becomes an empty list.
- `eval` remains a separate non-public section and is never moved into
  `input` or `assets`.
- family names are non-empty strings, but unknown families are accepted at load
  time.
- `asset_roots.public` defaults to `assets/`; `asset_roots.eval` defaults to
  `hidden/`; unsafe roots are rejected.

This step does not compile rows into `SecureBenchTask`, classify `eval.*` into
`evaluation_inputs` versus `hidden`, materialize assets, parse tester YAML, or
wire the new format into the CLI.

Deferred hardening: `parse_benchmark_row(...)` is currently intended for already
validated dictionary rows from the loader. If external callers begin using it
directly, add an explicit root-object guard so invalid direct inputs raise
`ConfigError` rather than lower-level attribute errors.

## 2. Row Compilation

Compile author-facing rows into internal `SecureBenchTask` and `ResourceBundle`
objects. Visibility should be derived from family/schema rules:

- `input.*` and top-level `assets[]` become public resources.
- family-specific `eval.*` fields become either `evaluation_inputs` or `hidden`.
- benchmark rows should not be able to arbitrarily override visibility.

The compiler turns a `BenchmarkRow` into a task spec consumed by
`task_from_spec(...)`. Existing task types still use specialized classes where
available, while new benchmark-family task types compile to generic
`SecureBenchTask` objects. Public row fields are flattened by key name, non-empty
`assets[]` becomes a public `assets` resource, and `eval.*` keys are classified
by a small registry. Unknown families and unknown `eval.*` keys default to
`hidden`.

Compiler metadata carries benchmark-pack details, row metadata, environment,
asset roots, and asset defaults. These fields are not agent-visible resources.
Resource-name collisions between public inputs, `assets`, and `eval.*` are
configuration errors.

Initial `eval.*` visibility registry:

- `multiple_choice`: `answer` is hidden.
- `short_answer`: `accepted_answers`, `tolerance` are hidden.
- `free_response`: `reference_answer`, `rubric` are hidden.
- `code_generation`: `tests` is `evaluation_inputs`; `reference_solution`
  and compatibility `canonical_solution` are hidden.
- `repo_patch`: `tests` is `evaluation_inputs`; `gold_patch` is hidden.
- `terminal_task`: `checker` is `evaluation_inputs`; `expected_state` is
  hidden.
- `tool_call`: `initial_state` is `evaluation_inputs`; `expected_calls`,
  `expected_final_state` are hidden.
- `browser_task`: `credentials` is `evaluation_inputs`; `success_check` is
  hidden.
- `desktop_task`: `success_check` is hidden.
- `artifact_task`: `reference_artifact`, `rubric` are hidden.
- `multimodal_qa`: `answer`, `rubric` are hidden.
- `preference_pair`: `preference`, `rubric` are hidden.

Compatibility note: `reference_solution` is the benchmark-pack
code-generation field for private/gold solutions. `canonical_solution` comes
from the current HumanEval adapter and remains accepted as a hidden
compatibility alias until that path is retired.

## 3. Materialization Expansion

Extend materialization beyond JSON values with a visibility-aware planner for
compiled `SecureBenchTask` objects.

Step 3 supports three lanes:

- public assets from top-level `assets[]`, resolved from `asset_roots.public`
  and copied into agent and test-sandbox workspaces.
- `evaluation_inputs` resources, materialized only for the test sandbox.
  JSON values keep using `securebench/evaluation_inputs/*.json`; file
  references resolve from `asset_roots.eval`.
- `hidden` resources, materialized only for evaluator-side storage. JSON
  values keep using `securebench/evaluator/*.json`; hidden file references also
  resolve from `asset_roots.eval` and are never mounted into agent or ordinary
  test-sandbox workspaces.

Public asset rows support:

```json
{"path": "fixtures/input.txt", "mount": "input.txt", "read_only": true}
```

`mount` defaults to `path`; `read_only` defaults to
`asset_defaults.read_only`. Non-public eval file references use the same
structural shape, but default to internal component paths such as
`securebench/evaluation_inputs/checks/check.py` or
`securebench/evaluator/expected.json`, and custom mounts must stay under the
appropriate internal root.

The file-reference shape is intentionally narrow: only `path`, `mount`, and
`read_only` are recognized as file-reference keys. Eval objects with additional
keys remain ordinary JSON resources until family schemas add richer validation.
Resolved asset roots and asset files must stay inside the benchmark package,
including after symlink resolution.

Path policy now has two responsibilities. Internal framework resources still
use fixed allowed roots (`securebench/public`,
`securebench/evaluation_inputs`, and `securebench/evaluator`). Public benchmark
asset mounts use a broader workspace-mount policy that permits normal relative
workspace paths while rejecting path traversal, absolute paths, backslashes,
mandatory denied paths, and reserved internal hidden/evaluator destinations.

Docker sandbox hardening is extended with optional bind mounts. Existing
sandbox behavior is unchanged when no extra mounts are configured. Read-only
assets can be copied into the workspace and then over-mounted into
`/workspace/<mount>` as read-only Docker bind mounts. The materialization layer
can derive those Docker bind mounts from a completed plan. This is the strong
container-mode integrity path; host-mode read-only behavior remains weaker and
should be treated as future harness work.

Deferred family-schema work: Step 3 recognizes file-reference structure
generically, but it does not yet decide which family fields are allowed or
required to be file references. That validation belongs with family schemas and
runner integration.

## 4. Tester YAML Parsing

Add a small tester config that contains only the run identity, benchmark pack
paths, output location, and harness selection. This parser is separate from the
old `securebench.config` Hugging Face run config and uses
`schema_version: "0.2"`.

The supported shape is:

```yaml
schema_version: "0.2"

run:
  id: repo-repair-codex
  output_dir: runs/repo-repair-codex

benchmark:
  manifest: ./benchmarks/repo-repair/manifest.yaml
  tasks: ./benchmarks/repo-repair/tasks.jsonl

harness:
  type: codex
  mode: mounted
  env:
    - CODEX_API_KEY
  config:
    version: latest
    task_file: task.json
    timeout_seconds: 900
```

Relative `run.output_dir`, `benchmark.manifest`, `benchmark.tasks`, and
submission `harness.path` values resolve against the tester YAML file
directory when loaded from disk. `parse_tester_config(...)` can also accept an
explicit `base_dir`.

Harness validation is deliberately minimal:

- allowed types are `codex`, `claude_code`, `command`, and `submission`.
- allowed modes are `host`, `container`, `mounted`, and `submission`.
- `submission` type must use `mode: submission` and provide `path`.
- non-submission types must use `host`, `container`, or the named-agent
  `mounted` mode.
- `env` is optional and contains environment variable names only, never
  `NAME=value` assignments.
- optional `harness.config` is preserved for Step 6 adapter-specific details.

Unknown fields are rejected at the root and in known sections, except inside
`harness.config`. Step 4 does not add `run.limit`, perform harness preflight,
load the benchmark, execute anything, or allow tester YAML to relax benchmark
security constraints.

## 5. Family Contracts, Schemas, and Runner Registry

Define the family-contract layer before implementing harness adapters. This
step should give every benchmark family a minimal internal contract describing
what kind of candidate artifact it expects, and should validate the
family-specific required and optional row fields for active families.

The first pass stays structural rather than implementing runners:

- define `CandidateKind` as `text`, `code`, or `patch`.
- define `FamilyContract(family, candidate_kind, requires_workspace=False)`.
- provide a registry lookup used by future harness adapters and family runners.
- allow unknown families to fail clearly once execution is attempted, while
  still allowing Step 1/2 loading and compilation.

Active contracts:

- `multiple_choice`: `text`
- `short_answer`: `text`
- `free_response`: `text`
- `code_generation`: `code`
- `repo_patch`: `patch`, requires a mutable workspace

Do not add visibility-derived fields such as `uses_evaluation_inputs` or
`uses_hidden`; those remain available from each task's `ResourceBundle`. Do not
add `legacy_task_type` or `runner_key`; future dispatch should use standard
family names directly. `submission` is a harness mode, not a candidate kind.

Deferred families: `terminal_task`, `tool_call`, `browser_task`,
`desktop_task`, `artifact_task`, `multimodal_qa`, and `preference_pair`. Future
candidate kinds such as `workspace`, `artifact`, and `trace` should be added
when those families become active.

This step does not run harnesses yet. Its job is to make the candidate-output
contract explicit so harness adapters know what they must produce.

Active-family schema validation runs at the start of row compilation, before
resources are constructed, so benchmark authors get row-shaped errors rather
than late runner failures. Unknown/deferred families may still load and compile,
but they fail execution-contract lookup until their contracts and runners are
implemented.

Active schemas:

- `multiple_choice`
  - required `input.question`: string
  - required `input.choices`: non-empty string array
  - required `eval.answer`: string, number, or non-empty string-or-number array
  - optional top-level `assets[]`
- `short_answer`
  - required `input.question`: string
  - optional `input.answer_format`: string
  - required `eval.accepted_answers`: non-empty string-or-number array
  - optional `eval.tolerance`: non-negative number
- `free_response`
  - required `input.prompt`: string
  - optional `input.context`: string or object
  - required `eval.rubric`: string or object
  - optional `eval.reference_answer`: string
- `code_generation`
  - required `input.prompt`: string
  - optional `input.language`: string
  - optional `input.starter_code`: string
  - required `eval.tests`: object
  - optional `eval.reference_solution`: string
  - compatibility: continue accepting optional `eval.canonical_solution` as a
    hidden HumanEval-era alias until the compatibility path is removed.
- `repo_patch`
  - required `input.repo`: string
  - required `input.base_commit`: string
  - required `input.instructions`: string
  - optional `input.hints`: string
  - required `eval.tests`: object
  - optional `eval.gold_patch`: string

Schema validation rejects unknown `input.*` and `eval.*` keys for active
families. Top-level `assets[]` remains common row structure; family schemas may
allow it but should not define custom asset visibility. Common asset-object
field validation for `path`, `mount`, `read_only`, `type`, and `mode` can be
introduced as shared asset-schema work, with materialization continuing to
support only the placement fields implemented so far.

Future maintainability note: the active-family validators are currently
hand-written because only five families are active and the rules are still
settling. If the family list grows, move these checks toward declarative schema
descriptors that list allowed fields, required fields, accepted value shapes,
and visibility expectations in one place. That would reduce duplicated helper
logic and make the benchmark standard easier to audit, while still compiling
rows into the same internal `ResourceBundle` model.

## 6. Harness Adapters

Introduce harness adapters as the new candidate-production spine. The first
implemented slice provides a generic harness builder plus an executable
`command` harness; other parsed harness types remain explicit follow-up work.

The command harness accepts:

```yaml
harness:
  type: command
  mode: container
  env:
    - OPENAI_API_KEY
  config:
    command: ["python", "-m", "my_harness"]
    artifact_path: candidate.txt
    task_file: securebench_task.json
    timeout_seconds: 120
```

`command` is required and may be a non-empty string or string array.
`artifact_path` is optional; when omitted, stdout becomes the candidate.
`task_file` defaults to `securebench_task.json`. `timeout_seconds`, when
provided, must be positive. Command config rejects unknown fields, and
`artifact_path` / `task_file` must be safe workspace-relative paths.

Before execution, SecureBench prepares an agent-visible workspace only:

- write the task payload from `task.agent_payload()`;
- materialize public resources and public `assets[]` with
  `VisibilityAwareMaterializer`;
- never materialize hidden or `evaluation_inputs` resources for the harness;
- in container mode, run the harness inside the benchmark row's resolved
  `environment.image` and derive read-only Docker bind mounts for read-only
  public assets.

Candidate output is normalized through the family contract. `text` and `code`
families populate `CandidateArtifact.text`; `patch` families populate
`CandidateArtifact.patch`. Unknown/deferred families still load and compile,
but fail clearly when a harness tries to execute them.

Host mode uses a rooted local workspace and is convenient for local tools, but
it is weaker isolation. Container mode uses `DockerSandbox` with the benchmark
environment image, the tester environment-variable allowlist, and existing
Docker hardening defaults. Named agent harnesses can use mounted tooling
overlays while still preserving the benchmark environment image as the runtime.

Deferred `submission` note: a future submission harness should read a file
keyed by task id, validate missing and duplicate task ids, preserve optional
candidate metadata, and ensure each submitted value matches the family
contract. This remains deferred because command-mode covers the important
agentic harness path first.

Named-wrapper note: `codex` now has a first mounted container harness that runs
inside the benchmark environment image and mounts a read-only Codex CLI overlay.
Candidate extraction remains deferred. `claude_code` and other agent wrappers
remain future work.

ACP can remain a future adapter path rather than a core dependency.

## 7. Family Runner Integration

Map benchmark families to candidate-output contracts and runners without adding
a separate global artifact section. Preserve current MMLU, HumanEval, and
SWE-bench behavior as compatibility paths while new development moves toward
family-based normalized rows and benchmark packs.

This is also the step where the full sandbox lifecycle becomes explicit. Step 6
creates only the harness working sandbox: the public workspace where the agent
or command sees `task.agent_payload()` and public assets. Step 7 must pair that
with a fresh evaluation/test sandbox per task or attempt. The test sandbox
receives the candidate artifact plus the public workspace state needed for
evaluation and only the `evaluation_inputs` resources allowed for that family.
Hidden resources remain evaluator-side only.

The intended standardized execution flow is:

1. compile a benchmark row into a `SecureBenchTask`;
2. create/materialize the harness working sandbox with public resources only;
3. run the harness and collect a family-shaped candidate artifact;
4. create a fresh test sandbox for scoring;
5. materialize public resources plus `evaluation_inputs` into that test
   sandbox;
6. run the family runner and keep hidden resources available only to trusted
   evaluator code.

## 8. CLI and Migration Path

Update the CLI so SecureBench can run the new tester YAML while the current
`securebench run --config ...` path keeps working during the transition. Add
focused smoke examples for the new pack format before removing or deprecating
old schema paths.
