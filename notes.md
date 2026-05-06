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

Deferred follow-up: use the resource views to drive explicit test-sandbox
materialization, evaluator inputs, stronger audit/replay redaction, and
schema-level declarations for custom adapters.

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

For the first HumanEval and GitHub patch smoke runs, the existing
`DockerSandbox` is acceptable as a local execution environment. A
`DockerSandbox` instance now owns one persistent container so setup commands,
installed packages, and command-side effects persist within a single task
attempt. Producers and runners are responsible for creating fresh sandbox
instances at task boundaries.

Deferred follow-up: harden `DockerSandbox` before using it as a stronger
untrusted-code boundary. At minimum, add no-network execution, memory and CPU
limits, PID limits, dropped capabilities, a read-only root filesystem where
possible, and explicit tests that verify the Docker command includes those
controls.

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
