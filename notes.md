# SecureBench Notes

## Durable Resource Visibility

SecureBench now separates benchmark-specific classification from framework-wide
enforcement. Adapters are the primary classification boundary: they understand
the raw benchmark row and return a plain normalized task spec with resource
visibility labels. SecureBench then converts that spec into internal
`Resource`, `ResourceBundle`, and `SecureBenchTask` objects.

The intended flow is:

```text
raw row -> adapter returns plain task spec -> framework builds resources/tasks
  -> public view goes to candidate producers
  -> evaluation view goes to test sandboxes
  -> hidden view goes to evaluator-side code
  -> result view redacts non-public values
```

This removes the need for downstream components to remember benchmark-specific
rules such as "do not serialize `answer`" or "do not put `test_patch` in the
workspace task file." Producers should continue using `task.agent_payload()`,
which is now backed by the task's public resource view. Result records may
include resource names and visibility summaries, but not hidden resource values.

The built-in adapters live in `securebench/securebench/adapters/` and use the
same path expected from third-party adapters: they return plain dictionaries
with `id`, `benchmark_id`, `task_type`, `metadata`, and `resources`.
Task classes are now structural containers only. They do not infer visibility
from fields such as `answer`, `tests`, or `test_patch`; populated tasks should
come from `task_from_spec(...)` or explicit internal `ResourceBundle`
construction.

`Resource` and `ResourceBundle` are internal framework mechanisms, not the
custom adapter authoring interface. Declarative adapters and native normalized
datasets should target the same plain task spec shape.

`hidden_fields` has been removed. `ResourceBundle` is now the sole
task-carried visibility mechanism.

`expose` has also been removed. A resource's visibility alone determines which
component views include it. If a future benchmark needs more precise
materialization behavior, that should be introduced as an explicit policy
mechanism rather than another visibility-like flag.

## Future Adapter Inputs

Declarative adapters should let simple benchmarks avoid writing Python adapter
classes. The declarative form should describe how to produce the same plain
task spec that Python adapters return today. It should support row/context field
paths, constants, ID templates, metadata mapping, resource visibility labels,
and a small set of built-in transforms such as JSON-list parsing. This is a fit
for simple multiple-choice, classification, QA, and HumanEval-like field
renaming. Benchmarks with conditional logic, unusual parsing, nested assembly,
or benchmark-specific cleanup should continue using Python adapters.

Native normalized datasets should let benchmark authors skip raw-dataset
adaptation entirely. In that mode, each dataset row is already a valid task spec
with `id`, `benchmark_id`, `task_type`, `metadata`, and `resources`. A future
run config could expose this as an identity adapter or as
`dataset.format: task_spec`. This is likely the easiest path for benchmarks
created specifically for SecureBench.

The `evaluation_inputs` visibility name is useful but a little abstract. A
future migration could rename it to `sandbox_input`, meaning data that is not
visible to the candidate producer but is available to the evaluation/test
sandbox. For example, secure-native HumanEval might make public prompt text
visible to the producer, sandbox inputs visible to the test sandbox, and
expected outputs hidden for trusted evaluator comparison.

Do not reintroduce `expose` yet, but keep the use case in mind. A future flag
with a clearer name such as `include_in_payload` or `materialize` could be
useful when visibility alone is too coarse. Examples include public audit
metadata that should not be prompt material, or sandbox file resources that
should be mounted into a container but not serialized into a JSON payload.

This visibility layer prevents framework-level routing mistakes, but it is not
an isolation boundary. A workspace agent still needs a properly isolated
sandbox: no hidden mounts, no broad host mounts, controlled environment
variables, no Docker socket, fresh test sandboxes, and hardened Docker options.

Deferred follow-up: wire materialization into runtime test-sandbox and
evaluator flows, strengthen audit/replay redaction, and add schema-level
declarations for custom adapters.

## Resource Materialization

Road B Option 1 adds internal materialization primitives without changing the
public run schema. `MaterializedResource` records the resource name,
visibility, kind, target component, framework-owned relative path, and
serialization format. `MaterializationPlan` groups those resources by target
component, and `ResourceMaterializer` can write the plan through the existing
sandbox-style `write_file` interface.

The immediate value is centralization rather than new benchmark capability.
Before this layer, each producer or runner had to invent its own files and
paths: task markdown for a workspace agent, candidate patches for a repository
runner, generated test scripts for code-generation tasks, hidden patch files,
and future fixture or input files. That pattern works for smoke paths, but it
spreads security-sensitive decisions across many modules. Materialization gives
SecureBench one framework-owned place to decide which resources can become
files, which component receives them, how names are made path-safe, how values
are serialized, and where future path policy should be enforced.

The current materializer uses only framework-owned paths:

- `securebench/public/<resource_name>.json` for public resources materialized
  for the agent or test sandbox
- `securebench/evaluation_inputs/<resource_name>.json` for evaluation inputs
  materialized for the test sandbox
- `securebench/evaluator/<resource_name>.json` for trusted evaluator-side
  materialization plans

This phase intentionally does not define public schema fields for `path`,
`source`, `mode`, or component overrides. Those fields remain the Option 3
possibility rather than being rejected in principle. Future schema-declared
paths could be validated against the same materialization model, and should be
allowed only to narrow physical placement within what resource visibility
already permits.

Option 3 path configurability might still be useful because not every benchmark can
consume framework-owned JSON files directly. Some existing tools expect inputs
at conventional paths, such as `tests/fixtures/input.json`, `data/questions.json`,
`cases/private.json`, or a package-specific config file. Some benchmark authors
may provide local fixture directories rather than Git repositories. Browser,
GUI, and simulation benchmarks may also expect static assets, scenario files,
or environment manifests in specific directory layouts. In those cases, schema
paths should let a benchmark request placement compatible with its runner, but
not widen access: visibility must still decide the component, path traversal
must be rejected, mandatory denied paths must win, and collisions with
framework files or repository files must be handled explicitly.

Only current value-backed `text` and `json` resources are materialized, and both
are serialized as deterministic JSON for now. Future internal resource kinds
such as `file`, `directory`, `artifact`, and `scratch` fail clearly until file
and directory materialization semantics are designed.

`result` remains a redacted serialization view, not a materialization target.
Current evaluator views include `public` and `hidden`, but not
`evaluation_inputs`. That is compatible with today's trusted scoring flow. A
future evaluator-side replay or reconstruction mode may need evaluator
materialization to include `evaluation_inputs` as well, if the trusted
evaluator context should reproduce the full task state.

Hidden-resource materialization should remain evaluator/trusted-side only.
Current runners generally access hidden resources directly through trusted task
objects, so there is no need to write hidden files for normal agent or test
sandbox execution. Future hidden materialization may be useful when a trusted
scorer process expects file inputs, when an evaluator sandbox needs hidden
expected answers or rubrics, when LLM-judge verification needs private reference
answers and grading criteria, or when SecureBench needs a verifier-only replay
bundle for audit and reproducibility. These uses should produce trusted-side
files such as evaluator inputs, never agent-visible or ordinary test-sandbox
mounts.

## Materialization Path Policy

Road C adds an internal path policy layer between materialization planning and
sandbox writes. Road B decides which resources can become files for a
component; Road C validates that the planned paths are allowed for that
component before any files are written.

The current policy is intentionally small and internal. It validates only
framework-owned paths, with fixed allowed roots:

- `agent`: `securebench/public`
- `test_sandbox`: `securebench/public` and `securebench/evaluation_inputs`
- `evaluator`: `securebench/evaluator`

Mandatory denied paths are rejected independently of allowed roots:
`/ground_truth`, `/scorer`, `/eval`, `/task/hidden.json`,
`/task/evaluation_inputs.json`, `/input/hidden.json`, and
`/output/score.json`. These paths come from the older prototype's access-policy
direction and serve as a global floor for future schema-declared placement.

Dynamic denies are intentionally deferred. With the current framework-owned
roots, they are mostly redundant because evaluator-owned paths are already
outside the agent and test-sandbox allowed roots. They should become useful
when future work introduces broader roots, runner-generated control files,
evaluator-only files, hidden patch artifacts, or Option 3 schema-declared paths.
Developer-provided allowlists or denylists are also deferred. If added, they
should only narrow access and must remain subordinate to mandatory denies,
future dynamic denies, and visibility-derived component access.

Patch-style benchmarks need an additional hardening note. A fresh test sandbox
prevents the workspace agent from seeing hidden tests while producing a patch,
but candidate code may still tamper with hidden tests or evaluator-controlled
files once those files are present in the test sandbox. Future mitigations
include materializing hidden test assets read-only where possible, keeping
hidden tests outside candidate-writable repository trees, applying hidden tests
immediately before test commands, verifying hashes before execution, and
recording explicit audit metadata when a benchmark cannot avoid this risk.

## Agent Payload Task IDs

`agent_payload()` does not strictly need to include the task ID for the agent to
solve a task. The ID is mainly useful for orchestration: logs, transcripts,
artifacts, retries, and evaluator joins can all reference the same stable task.

Including IDs in the agent-visible payload may weaken benchmark hygiene if the
ID itself is a clue, such as a public benchmark row ID or GitHub issue-style
identifier. This matters most when network access is enabled or when evaluating
against benchmarks that may be memorized.

A cleaner split is to keep the task ID in an evaluator/orchestration envelope
and omit it from the agent-visible payload:

```python
{
    "task_id": task.id,
    "agent_payload": task.agent_payload(),
}
```

This preserves traceability without making the identifier part of the prompt
seen by the agent.

## HumanEval Code Output Normalization

For the first HumanEval smoke runs, rely on the OpenAI-compatible producer's
system prompt to ask for an append-only, indented Python function body with no
repeated imports, decorators, function signature, Markdown fences, or
explanation. This matches the original HumanEval completion-style assumption:
the evaluator appends the model completion to the dataset prompt, then appends
hidden tests and `check(entry_point)`.

Deferred follow-up: add conservative runner-side normalization if real chat
model outputs include common wrappers. Start with stripping Markdown fences and
removing an exact repeated prompt prefix. Avoid aggressive code repair or
function-body extraction until failures show it is needed.

## CodeGenerationRunner Scope

The current `CodeGenerationRunner` is really a HumanEval-style Python completion
test runner. It assumes the evaluator can build one script by concatenating the
dataset prompt, the model's completion, hidden tests, and `check(entry_point)`.

That is correct for HumanEval, but it is not yet a general code-generation
runner. Future code-generation benchmarks may require different modes, such as
running a full generated source file, comparing stdout against expected output,
executing multiple files, or running a separate unit-test command.

Deferred follow-up: split the generic task type from the runner execution mode.
For example, keep `task_type: code_generation`, but introduce runner config or
specific runner classes for `python_completion_tests`, `python_program_io`, and
other evaluation styles.

## Docker Sandbox Hardening

`DockerSandbox` now applies restrictive Docker options by default. Container
creation uses no-network mode, drops Linux capabilities, sets a read-only root
filesystem, mounts tmpfs for `/tmp`, applies memory and PID limits, and enables
`no-new-privileges:true`. The `/workspace` bind mount remains writable so
SecureBench can materialize task files, candidate artifacts, repository
checkouts, and test outputs without requiring a writable container root.

Run configs can override these defaults through a small `sandbox` section with
`defaults`, `agent_workspace`, and `test_sandbox` policies. Existing configs
that omit this section inherit the restrictive defaults. These controls are
still a practical Docker hardening layer, not a formal isolation proof: a real
deployment still needs careful image selection, no Docker socket mounts,
explicit secret allowlists, and host-level containment.

GitHub patch tasks now split repository clone/checkout from sandboxed patch
production and evaluation. SecureBench prepares the repository checkout from
the trusted host side, places a fresh copy under the sandbox workspace root,
and then starts the sandbox with the prepared repository already present. This
means the test sandbox does not need network access merely to clone the
repository. Candidate patch application, hidden patch application, setup
commands, and test commands still run inside the sandbox.

Dependency setup remains intentionally conservative in this phase. The chosen
Option A moves only clone/checkout into trusted preparation; setup commands
still execute in the sandbox. This keeps setup failures part of the evaluation
attempt and avoids trusting arbitrary benchmark setup commands on the host, but
it means network-dependent setup requires a prebuilt image, local cache, or a
future prepared-environment phase. Option B would also run dependency setup in
trusted preparation, giving a stronger no-network test-sandbox story but
blurring whether setup is part of evaluation and risking host-side execution of
benchmark commands. Option C would build a full task image or snapshot with
repo and dependencies already prepared; this is closest to large-scale
SWE-bench-style evaluation, but it adds image lifecycle, caching, invalidation,
cleanup, and storage complexity.

Deferred follow-up: separate dependency/environment preparation from test
execution more explicitly. A future prepared-environment layer should let the
framework build or select benchmark/task images before evaluation, then run
candidate patch application and tests in a fresh no-network sandbox.

## Workspace Agent Command Policy

The built-in workspace agent's `run_command` allow/deny lists are useful
guardrails, but they are not a security boundary. Allowing a broad executable
such as `python`, `pytest`, or even some `git` operations can still permit
network access, environment inspection, filesystem traversal, subprocesses, or
other side effects from inside that allowed program.

Deferred follow-up: treat command policy as agent guidance and audit logging,
not isolation. Real untrusted workspace-agent runs need Docker/OS-level
controls such as no-network mode, explicit environment allowlists, resource
limits, dropped capabilities, fresh workspaces, and no mounted secrets.

## Workspace Agent Traceability

The SWE-bench smoke run can fail with an empty candidate patch even when the
agent exits successfully and reports a useful final summary. The current output
does not preserve enough of the agent's tool-call sequence to diagnose whether
the model attempted an edit, whether `apply_patch` failed, whether a file write
was skipped, or whether the final diff was empty for another reason.

Deferred follow-up: persist a compact, sanitized agent trace in producer
metadata. It should include step number, tool name, safe arguments such as file
paths or patch length, and bounded result metadata such as `ok`, exit code,
content length, stdout/stderr length, and error type. Do not store full file
contents, full patches, `.env` data, hidden patches, or hidden test lists in
the trace.

## Generic GitHub Patch Evaluation

Keep GitHub patch evaluation benchmark-neutral. SWE-bench is the first target,
but runner behavior should be expressed through generic concepts:

- hidden patch groups, such as a `tests` patch applied only during evaluation
- named test groups, such as `fail_to_pass`, `pass_to_pass`, `regression`, or
  `security`
- configurable command templates that consume selected test groups

Avoid baking SWE-bench field names into `GitHubPatchRunner`. The SWE-bench
adapter can map its raw fields into generic task fields, while the runner reads
only those generic fields.

## Sandbox Lifecycle Isolation

Benchmark evaluation should use a fresh test sandbox per task attempt, while
commands within the same attempt should run in the same sandbox. This lets setup
commands persist for the current task without allowing files, processes, caches,
or package installs to bleed into later tasks.

The current default paths follow that model: auto-created Docker sandboxes are
closed at the end of a task attempt, `GitHubPatchRunner` can use a sandbox
factory, and workspace patch producers can use a sandbox factory to avoid
sharing an agent workspace across rows. Injected test sandboxes may still be
shared intentionally by unit tests, so production config should prefer factories
or auto-created sandboxes.

Deferred follow-up: keep tightening this contract in public APIs and docs so
future runners/producers cannot accidentally reuse one long-lived sandbox for a
batch.

## Agent Image Minimality

The SecureBench agent Docker image should contain only the standalone
`securebench_agent` runtime, command policy helpers, and the minimal
OpenAI-compatible client/model code needed by the agent. It should not copy the
host-side `securebench` framework package into untrusted benchmark sandboxes.
This keeps the sandbox import graph independent from CLI/config/adapters,
runners, datasets, evaluators, and Docker orchestration code.

Deferred follow-up: keep the standalone runtime's Python compatibility floor
explicitly tested against old benchmark images such as `3.9-slim-bullseye`, so
future host-framework syntax changes do not break agent startup in benchmark
environments.
