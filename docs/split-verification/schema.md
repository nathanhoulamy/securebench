# Split-verification benchmark schema

Status: author-facing design target for SecureBench v2

The executable source of truth is
[`securebench/schemas/benchmark.py`](../../securebench/schemas/benchmark.py).
The generated JSON Schemas in [`schemas/`](../../schemas/) are the
machine-readable validation artifacts. This guide documents both the supported
runtime slice and schema-valid target architecture; it is not a second schema
implementation.

## Recommendation

Use a check-centric schema built around one replayable candidate, two check
types, and three centrally enforced visibility lanes.

- The candidate is exactly one durable handoff: `git_patch`,
  `file_bundle`, or `filesystem_overlay`.
- An `artifact` check inspects bounded candidate data without executing
  candidate code.
- A `protocol` check runs the candidate through a public, assertion-free
  adapter against one current host-selected case.
- Trusted Helpers are declared inside the protocol check that
  uses them.
- Public, Evaluation-runtime-only, and host-only resources are separated
  structurally and compiled into SecureBench visibility lanes.
- The host Oracle owns expectations, evidence correlation, scoring, and the
  final verdict.

The schema retains the useful benchmark-pack envelope and resource-routing
model already implemented by SecureBench. It replaces family-specific
verification with a common split-verification engine.

Examples are separated into an
[`executable`](examples/executable.yaml) row and
[`target-architecture`](examples/target-architecture.yaml) rows whose runtime
engines are not implemented yet.

## Core model

The row has four distinct concerns:

1. `family`, `input`, `assets`, and `environment` define how the agent
   receives and works on the task.
2. `verification.candidate` defines the single durable result collected from
   the Agent VM.
3. `verification.checks` defines how that result is observed.
4. `verification.oracle` identifies the only component allowed to determine
   correctness.

The verification patterns used during review are derived from the checks:

| Row configuration | Derived review pattern |
|---|---|
| `artifact` check | passive artifact verification |
| `protocol` check | black-box challenge/response |
| protocol check with `trusted_helpers` | trusted external state |
| protocol check with `output_artifacts` | black-box plus passive artifact inspection |

Pattern labels are therefore review and reporting data, not author-written
runtime fields.

## What is retained from SecureBench

- Manifest-plus-row benchmark packs and manifest defaults.
- The outer row fields `id`, `family`, `input`, `assets`,
  `environment`, and `metadata`.
- Families as Agent-workflow and public-input contracts.
- The centralized `public`, `evaluation_inputs`, and `hidden`
  information-flow model.
- Agent harnesses, digest-pinned images, workspace setup, and sandbox
  infrastructure.
- Git-diff candidate extraction as the basis of `git_patch`.

The current family-specific verifier implementations are not retained as an
alternative mode. The new verification section always describes split
verification.

## Design decisions

### Preserve families, but narrow their role

A family selects Agent VM preparation and validates family-specific public
input. It does not select a verifier or an evidence strategy.

The initial compatibility rules are:

| Family | Required public input | Allowed candidate type |
|---|---|---|
| `repo_patch` | `repo`, `base_commit`, `instructions` | `git_patch` |
| `terminal_task` | `instructions`, optional `context` | `file_bundle`, `filesystem_overlay` |

These are documentation and semantic-validation rules. They do not require
another row field. Future families should be added only when the Agent
workflow materially differs, not when verification differs.

For `repo_patch`, `base_commit` is a full lowercase 40- or 64-hex Git object ID.
The digest-pinned image's `environment.workdir` supplies the baseline repository
and must be clean with `HEAD` exactly at that commit.

### Require one replayable candidate

Every admitted row must produce one durable candidate that can be
materialized in a clean environment.

- `git_patch` represents repository changes.
- `file_bundle` represents selected files or bounded directory trees.
- `filesystem_overlay` represents bounded system configuration and durable
  filesystem state.

Candidate capture never includes live processes, open connections, mounts,
in-memory state, credentials, Agent VM interaction history, or a remote
service modified only during solving. A task whose solution cannot be
replayed must be redesigned or excluded.

The candidate capture policy is orchestration data and is not automatically
shown to the agent. The public prompt must already define every deliverable
that matters to solving. Admission review must ensure that candidate capture
preserves every valid solution allowed by that prompt.

### Use only two check types

`artifact` and `protocol` are the only core scheduler distinctions.

- `artifact` gives bounded hostile candidate bytes to a registered parser
  and then gives the typed parser result to the host Oracle. It creates no
  candidate-execution runtime, although patch or overlay materialization may
  still use a hardened non-executing materializer.
- `protocol` materializes the candidate in an Evaluation runtime and uses a
  public adapter protocol to exchange one current challenge and bounded
  observations.

CLI, compiler, HTTP service, browser, lifecycle, and multi-peer behavior are
adapter protocols, not row-schema check types.

### Keep correlated evidence inside one check

A protocol check may return bounded Output Artifacts and use Trusted Helpers.
Every Observation, Output Artifact, helper record, and supervisor fact from one
attempt is bound by SecureBench to the same check ID, Challenge ID, Challenge
digest, and Evaluation ID.

This represents black-box, passive, trusted-state, and hybrid verification
without separate evidence modules.

### Preserve centrally enforced visibility lanes

The author-facing schema uses structural placement:

- `input` and `assets` contain public material.
- `verification.resources.runtime` contains Evaluation-runtime-only
  material.
- `verification.resources.host` contains host-only material.

The compiler maps those locations to SecureBench's internal visibility
classes:

| Author-facing location | Internal visibility | Agent VM | Evaluation runtime | Host orchestrator / Oracle |
|---|---|---:|---:|---:|
| `input`, `assets` | `public` | yes | yes | yes |
| `resources.runtime` | `evaluation_inputs` | no | yes | orchestrator only unless explicitly required |
| `resources.host` | `hidden` | no | no | yes |

This is a routing guarantee, not only a naming convention. Materialization
must continue to use centralized component-safe views. Rows do not repeat a
`visibility` property because their structural location already fixes it.

Public assets are declared once and are made available at the same declared
mount in the Agent VM and relevant Evaluation runtimes. They are not
duplicated under `resources.runtime`.

The current challenge is derived from a host resource and released one case
at a time. It is not a static fourth visibility class.

### Treat external state as Trusted Helpers

Trusted Helpers have a candidate-facing data plane and a host-only control
and evidence plane. Their registered component profiles fix those
capabilities; row authors cannot add capabilities.

The row supplies only:

- a check-local name;
- a registered helper type;
- an optional host-only settings resource;
- component-specific reduced bounds.

Examples include HTTP request ledgers, controlled origins, SMTP sinks, probe
models, byte relays, databases, clocks, and process supervisors.

Helper instances, credentials, and state are fresh for every Evaluation under
the strict execution profile. Multi-phase persistence within one Evaluation is
allowed when it is part of that Challenge's declared protocol.

### Keep scoring and admission validation outside the row

The Oracle owns expected values, normalization, thresholds, evidence
correlation, scoring, and the final verdict.

Base/gold/mutant/adversarial qualification belongs in a separate admission
manifest and pipeline. Conversion status and fidelity remain optional
metadata and dossier material.

## Full author-facing row shape

The following is structural notation. Conditional fields are described in the
field reference.

Every pack starts with a v2 manifest whose three non-overlapping source roots
make structural row placement enforceable at the filesystem boundary:

~~~yaml
schema_version: "2.0"
id: benchmark-pack-id
defaults:
  family: terminal_task
  environment: {}
resource_roots:
  public: assets/
  runtime: evaluation_inputs/
  host: hidden/
asset_defaults:
  read_only: true
~~~

Roots are pack-relative, symlink-safe, and may not overlap. A resource under
one root cannot be routed through a different lane merely by changing its row
placement.

~~~yaml
id: benchmark/task-id
family: repo_patch | terminal_task

input:
  instructions: string
  repo: string
  base_commit: immutable-commit
  context: optional-public-context

assets:
  - path: pack-relative-path
    mount: absolute-shared-path
    read_only: true

environment:
  image: immutable-image-reference
  workdir: absolute-path
  timeout_seconds: positive-number
  agent_network: none | restricted | internet

verification:
  execution_profile: strict-split/v1

  candidate:
    type: git_patch | file_bundle | filesystem_overlay

  resources:
    runtime:
      resource_id:
        path: pack-relative-path
        mount: absolute-runtime-path
    host:
      resource_id:
        path: pack-relative-path

  checks:
    - id: stable-check-id
      type: artifact | protocol

  oracle: host.oracle-resource-id

metadata:
  source_dataset: string
  source_revision: immutable-revision
  conversion:
    verdict: clean | semantic_change | major_redesign
    intelligence_impact: none | low | medium | high
    dossier: pack-relative-path
~~~

`environment.timeout_seconds` and `environment.agent_network` apply only
to candidate production. Verification time and networking are controlled by
checks, trusted components, and the execution profile.

## Candidate branches

### Git patch

~~~yaml
candidate:
  type: git_patch
  max_patch_bytes: 16777216
  max_changed_files: 2048
  max_changed_bytes: 134217728
  allow_paths:
    - "**"
  exclude_paths:
    - tests/**
    - securebench/**
    - "**/test-results/**"
~~~

`allow_paths` is optional. SecureBench also applies a framework-owned
protected-path policy that rows cannot weaken. The candidate patch is derived
from the stopped Agent worktree in a trusted clone; Agent-authored patches and
Git metadata are ignored. Bounds are checked on both the canonical full-index,
binary-capable patch and its materialized result.

### File bundle

~~~yaml
candidate:
  type: file_bundle
  max_total_files: 10000
  max_total_bytes: 268435456
  files:
    - id: result
      path: /app/result.json
      kind: regular_file
      max_bytes: 1048576
    - id: repository
      path: /app/repository
      kind: directory_tree
      max_files: 9999
      max_total_bytes: 267386880
~~~

Every entry is either a `regular_file` with `max_bytes` or a
`directory_tree` with `max_files` and `max_total_bytes`. Entry bounds
must fit within the bundle-wide bounds. Special files and escaping symlinks
are rejected. Safe internal symlinks are accepted only when the relevant
registered contract permits them.

### Filesystem overlay

~~~yaml
candidate:
  type: filesystem_overlay
  include_roots:
    - /app
    - /etc/example-service
  max_files: 20000
  max_total_bytes: 536870912
~~~

The overlay contains a bounded diff against the declared digest-pinned
baseline. It may contain regular files, directories, deletions, and safe
internal symlinks according to the canonical overlay specification. Devices,
sockets, FIFOs, mounts, processes, credentials, and in-memory state are
rejected. The overlay may be applied only to the same pinned baseline.

## Check branches

### Artifact check

~~~yaml
checks:
  - id: result_artifact
    type: artifact
    artifacts:
      - id: result
        source:
          entry: result
        parser: securebench.strict-json/v1
        limits:
          max_bytes: 1048576
~~~

For a path inside a materialized patch or overlay:

~~~yaml
source:
  path: relative/or/absolute/materialized-path
~~~

Exactly one of `source.entry` or `source.path` is required. `source.entry`
references either a regular-file or directory-tree entry in a `file_bundle`.
For a directory tree, parser limits use both `max_files` and
`max_total_bytes`. For `git_patch`, `source.path` is repository-relative and
observation happens passively after replay onto a fresh clean baseline. For
overlays, detailed path semantics remain part of the future materializer
specification.

### Protocol check

~~~yaml
checks:
  - id: public_behavior
    type: protocol
    adapter: runtime.public_adapter
    protocol: securebench.example/v1
    challenge:
      source: host.challenge_cases
      max_cases: 64
      max_case_bytes: 1048576
    trusted_helpers:
      - name: request_recorder
        type: securebench.http-request-recorder/v1
        settings: host.request_recorder_settings
        limits:
          max_requests: 128
          max_body_bytes: 65536
    output_artifacts:
      - name: generated_result
        parser: securebench.strict-json/v1
        limits:
          max_bytes: 1048576
    limits:
      seconds_per_case: 30
      observation_bytes_per_case: 1048576
~~~

`trusted_helpers` and `output_artifacts` are optional. The referenced Adapter
resource contains a reviewed public manifest and implementation. Its
`securebench.adapter/v2` manifest defines the command, typed Challenge and
Observation schemas, Evaluation Participants, required Trusted Helpers,
Helper Access, Output Artifacts, and hard maximums that the row may only
reduce.

Under the current `strict-split/v1` backend, requested Output Artifact limits
must total at most 16 MiB and 4,096 filesystem entries per Evaluation. Paths
are relative to `environment.workdir`, may not use `.git` or the framework's
`securebench/` materialization area, overlap an Evaluation resource mount, or
traverse symlinked parents.
Collection happens only after the one-shot Evaluation process exits. Missing,
wrong-type, oversized, unsafe, or parser-rejected artifacts become Candidate
evidence; collector or registered-parser contract failures are framework
infrastructure errors.

Under `strict-split/v1`, every Challenge receives a fresh Evaluation, helper
instances, credentials, and Evaluation ID. A bounded multi-step lifecycle is
one Challenge, not cross-Challenge persistence.

## Execution profiles

An execution profile selects framework isolation and information-flow
semantics. It does not select cases, expected answers, scoring, or task
behavior.

### Strict split

`strict-split/v1` requires:

- host resources never enter candidate-controlled VMs;
- one current challenge is delivered at a time;
- fresh Evaluation Participants and Trusted Helpers per Challenge;
- fresh credentials and an Evaluation ID per Evaluation;
- capability-restricted Evaluation networking;
- read-only runtime resources;
- candidate code executing only in Evaluation runtimes;
- bounded Challenge, Observation, Output Artifact, helper, time, and resource
  channels;
- only the host Oracle emitting a score or verdict.

A challenge-free prepare, seal, and clone optimization is compatible with
this profile:

1. Materialize and perform declared challenge-independent setup.
2. Seal an immutable candidate snapshot.
3. Clone a fresh runtime from it for every case.
4. Inject the current challenge and credentials only after cloning.

### Batched split fallback

A separately specified `batched-split/v1` profile may reuse one candidate
runtime across several cases when strict isolation is operationally
prohibitive. It must still reset Trusted Helpers and credentials and must
report runtime reuse explicitly. It is weaker because candidate state may
cross case boundaries and must not be presented as equivalent to strict split
verification.

## Component contracts

The row schema references four component classes. Their contracts are
versioned separately from rows.

### Adapter format

The versioned `securebench.adapter/v2` manifest defines:

- the public protocol identifier and closed, typed Challenge and Observation schemas;
- the bounded command and Evaluation Participants;
- each required Trusted Helper and its type;
- each Output Artifact's name, path, kind, and hard maximums;
- hard Challenge, Observation, and time maximums.

~~~yaml
format: securebench.adapter/v2
protocol: securebench.example/v1
command: [python3, ./adapter.py]
challenge_schema:
  type: object
  properties:
    value: {type: integer}
  required: [value]
  max_fields: 1
observation_schema:
  type: object
  properties:
    answer: {type: integer}
  required: [answer]
  max_fields: 1
evaluation_participants:
  - {name: candidate, type: candidate, instances: 1}
uses_trusted_helpers:
  - {name: request_recorder, type: securebench.http-request-recorder/v1}
output_artifacts:
  - name: generated_result
    path: results/result.json
    kind: regular_file
    maximum_limits: {max_bytes: 1048576}
maximums:
  seconds_per_challenge: 30
  challenge_bytes: 1048576
  observation_bytes: 1048576
~~~

For each Evaluation, SecureBench sends a `securebench.adapter-request/v2`
object containing the host-generated Challenge ID, Evaluation ID, current
Challenge, and scoped Helper Access. The Adapter returns exactly one
`securebench.adapter-response/v2`: either an Observation or a Candidate
failure. It cannot return a pass/fail verdict.

Adapters run only in Evaluation runtimes, contain no hidden expectations or
scoring logic, and return observations rather than authoritative verdicts.

### Parser contract

A parser profile defines accepted bytes, normalization, typed output,
hardening, output bounds, and whether it runs in an isolated observer.
Parsers never import or activate candidate content as a language object.

### Trusted Helper contract and catalog

A versioned `securebench.trusted-helper-contract/v1` catalog entry fixes the
helper type, capabilities, candidate-facing Helper Access method, host-only
control plane, settings and evidence schemas, reset behavior, credential
lifetime, and component-specific maximums. Rows may select settings and reduce
limits; they cannot add capabilities or raise maximums.

The first executable catalog entry is
`securebench.http-request-recorder/v1`. It provides an authenticated HTTP data
plane on a fresh internal Evaluation network and returns bounded, host-collected
request evidence. Its optional settings are `path` (default `/`),
`response_status` (default `204`), and `response_body` (default empty). Rows
must bound `max_requests` and `max_body_bytes`, and may reduce
`max_header_bytes` from the catalog maximum. Other helper types remain
non-executable until a reviewed contract and runtime are registered together.

### Oracle contract

The Oracle resource contains a reviewed manifest and implementation conforming
to the standard Oracle ABI:

1. `initialize(row, run_seed)` starts a deterministic host-only session;
2. `evaluate_artifact(check_id, evidence)` consumes passive-check evidence;
3. `next_challenge(check_id, challenge_source, bounds)` returns one bounded
   current Challenge plus opaque host-only context, or reports exhaustion;
4. `evaluate_challenge(check_id, challenge_context, evidence)` consumes one
   correlated Challenge Evidence record; and
5. `finalize()` returns the final structured score, verdict, and bounded public
   diagnostics.

This lifecycle supports static corpora, generated and adaptive cases, private
case context, and final aggregation. The Oracle never executes or dynamically
loads candidate-controlled content.

The `securebench.oracle/v1` JSON-lines wire format retains the method names
`next_case` and `evaluate_case` for compatibility; the host API exposes the
clearer Challenge-oriented names above.

Central parsers and Trusted Helpers with reviewed pack-local Adapters and
Oracles are the recommended initial registry policy.

## Challenge Evidence

Challenge Evidence is an internal SecureBench-to-Oracle interface, not an
author-written row section. A representative record is:

~~~yaml
format: securebench.challenge-evidence/v1
check_id: public_behavior
challenge:
  id: challenge-0042
  index: 41
  digest: sha256:...
evaluation_id: evaluation-9f1c...
status: observed
process:
  exit_status: 0
  timed_out: false
  duration_ms: 821
observation: {}
observation_bytes: 128
output_artifacts:
  generated_result:
    challenge_id: challenge-0042
    evaluation_id: evaluation-9f1c...
    digest: sha256:...
    parser: securebench.strict-json/v1
    parsed_value: {}
trusted_helper_evidence:
  request_recorder:
    type: securebench.http-request-recorder/v1
    challenge_id: challenge-0042
    evaluation_id: evaluation-9f1c...
    value: {requests: []}
    truncated: false
failure: null
~~~

SecureBench, not the Candidate, assigns Challenge IDs, Evaluation IDs, digests,
timing, and truncation markers. Every nested helper and artifact item must
repeat the same IDs or the record is rejected. A failure records its source as
`candidate`, `adapter`, `trusted_helper`, or `framework`; Candidate errors are
evidence, while the other sources are infrastructure failures.

## Field reference

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Stable row identifier, unique within the pack. |
| `family` | yes unless supplied by manifest default | Selects Agent workflow and family-specific public-input validation. |
| `input` | yes | Public task contract. `instructions` is always required. |
| `assets` | no | Public task material mounted read-only by default into Agent and relevant Evaluation runtimes. |
| `environment` | yes unless supplied by manifest defaults | Digest-pinned solving image, workdir, timeout, and Agent network policy. |
| `environment.agent_network` | yes unless defaulted | Solving-phase network policy only. |
| `verification.execution_profile` | yes | Registered framework security and isolation profile. |
| `verification.candidate` | yes | Discriminated union defining the single durable handoff. |
| `candidate.type` | yes | `git_patch`, `file_bundle`, or `filesystem_overlay`. |
| `candidate.max_patch_bytes` | Git patch only | Maximum canonical patch bytes. |
| `candidate.max_changed_files` | Git patch only | Maximum changed paths after materialization. |
| `candidate.max_changed_bytes` | Git patch only | Maximum summed final logical sizes of added and modified files after materialization. |
| `candidate.allow_paths` | no, Git patch only | Optional path allowlist that cannot weaken protected paths. |
| `candidate.exclude_paths` | no, Git patch only | Additional excluded paths. |
| `candidate.max_total_files` | File bundle only | Aggregate number of exported filesystem entries, including directories and permitted symlinks. |
| `candidate.max_total_bytes` | File bundle only | Aggregate logical bytes across entries. |
| `candidate.files` | File bundle only | Exact exported regular files or bounded directory trees. |
| `candidate.files[].allow_internal_symlinks` | no, directory tree only | Row-level opt-in, defaulting to `false`, for symlinks whose targets resolve inside the same captured tree. Symlink entries and target bytes count toward candidate bounds; absolute, escaping, and oversized targets remain rejected. |
| `candidate.include_roots` | Overlay only | Absolute roots whose durable changes may be captured. |
| `candidate.max_files` | Overlay only | Maximum overlay entries. |
| `candidate.max_total_bytes` | Overlay only | Maximum logical overlay bytes. |
| `verification.resources.runtime` | Protocol checks only | Read-only Evaluation-runtime resources compiled as `evaluation_inputs`. |
| `verification.resources.host` | yes | Host-only challenge, configuration, and Oracle resources compiled as `hidden`. |
| `resource.path` | yes | Pack-relative file or directory that may not escape the pack. |
| `runtime.<id>.mount` | yes | Absolute, collision-free Evaluation-runtime mount. |
| `verification.checks` | yes | Non-empty list of identified verification units. |
| `check.id` | yes | Stable ID included in evidence and results. |
| `check.type` | yes | `artifact` or `protocol`. |
| `artifact.artifacts` | Artifact check only | Non-empty list of artifact sources and parser profiles. |
| `artifact.source.entry` | conditional | References a regular-file or directory-tree `file_bundle` entry ID. |
| `artifact.source.path` | conditional | References a bounded materialized path; repository-relative for `git_patch`, absolute within an include root for overlays. |
| `artifact.parser` | yes | Registered parser profile. |
| `artifact.limits` | yes | Either `max_bytes` for a regular file or `max_files` (all filesystem entries) plus `max_total_bytes` for a tree. |
| `protocol.adapter` | Protocol check only | Runtime-resource reference containing adapter manifest and implementation. |
| `protocol.protocol` | Protocol check only | Public versioned protocol ID validated against the adapter manifest. |
| `protocol.challenge` | Protocol check only | Host source and current-case bounds. |
| `challenge.source` | yes | Host resource containing a case generator or corpus. |
| `challenge.max_cases` | yes | Maximum cases selected for this check. |
| `challenge.max_case_bytes` | yes | Maximum serialized current-case bytes. |
| `protocol.trusted_helpers` | no | Check-local Trusted Helpers required during Evaluation. |
| `trusted_helpers[].name` | conditional | Clear check-local name used by the Adapter. |
| `trusted_helpers[].type` | conditional | Registered Trusted Helper type with fixed capabilities. |
| `trusted_helpers[].settings` | no | Host-only, contract-validated helper settings. |
| `trusted_helpers[].limits` | conditional | Component-specific bounds that may only reduce catalog maximums. |
| `protocol.output_artifacts` | no | Candidate-generated Output Artifacts captured after an Evaluation. |
| `output_artifacts[].name` | conditional | Output Artifact name declared by the Adapter. |
| `output_artifacts[].parser` | conditional | Registered passive parser profile. |
| `output_artifacts[].limits` | conditional | Byte or tree input bounds for an Output Artifact. |
| `protocol.limits` | Protocol check only | Universal per-case time and observation bounds. |
| `verification.oracle` | yes | Host-resource reference implementing the standard Oracle ABI. |
| `metadata` | no | Provenance and conversion-review information with no runtime authority. |

## Stress test against representative rows

| Requirement | Representative row | Representation |
|---|---|---|
| Passive-only output | `constraints-scheduling` | File bundle and one artifact check |
| Hidden CLI cases | `circuit-fibsqrt` | File bundle and one protocol check |
| System configuration and protocols | `configure-git-webserver` | Overlay and protocol check |
| Timing, signals, independent records | `cancel-async-tasks` | Protocol check with recorder and supervisor Trusted Helpers |
| Separate checks over one candidate | `overfull-hbox` | Artifact and protocol checks |
| All three review patterns | `install-windows-3.11` | Overlay, artifact check, protocol check, launch Trusted Helper |
| Two public interfaces | `boa-hierarchical-evaluation-cancellation` | Two protocol checks over one patch |
| Runtime-generated structured artifact | `oxvg-structural-selector-preservation` | Protocol check with returned SVG artifact |
| Multi-phase persistence and probe calls | `igel-persist-feature-schema` | One lifecycle Challenge with probe Trusted Helper and Output Artifacts |
| Two candidate peers | `kcp-go-multiplexed-kcp-streams` | Adapter with two Evaluation Participants and a byte-relay Trusted Helper |
| Restartable mail system | `mailman` | Overlay, SMTP/API protocol, SMTP sink |
| One-time Agent VM action only | Unsupported | Redesign to a replayable candidate or exclude |

## Validation invariants

1. A row has exactly one candidate type and at least one check.
2. Unknown fields are rejected and unions reject fields from other branches.
3. IDs are unique in their namespace and all references resolve.
4. Family input and candidate type satisfy the initial compatibility matrix.
5. Public input and assets are the only row resources visible to the Agent VM.
6. Runtime resources compile as `evaluation_inputs`, are read-only, and never
   enter the Agent VM.
7. Host resources compile as `hidden` and never enter candidate-controlled
   VMs.
8. Only one bounded current challenge derived from a host resource enters a
   runtime at a time under the strict profile.
9. Candidate capture is durable and replayable and contains no process,
   socket, mount, credential, memory state, or Agent VM interaction log.
10. Git patches are canonical, apply to the declared base commit, satisfy
    materialized bounds, and cannot modify protected paths.
11. File bundles and overlays satisfy entry, aggregate, path, and file-type
    policies.
12. Candidate capture, Challenges, Observations, Output Artifacts, Helper Access,
    and runtime execution are bounded.
13. Under strict split, every Challenge receives a fresh Evaluation and Trusted Helper state.
14. Adapter protocols are public, versioned, typed, bounded, and
    assertion-free.
15. Trusted Helper contracts fix least-privilege interfaces; rows may reduce limits
    but cannot add capabilities.
16. Candidate code executes only in Evaluation runtimes.
17. The Oracle never imports, links, executes, unpickles, or dynamically loads
    candidate-controlled content.
18. Registered parsers treat candidate bytes as hostile data.
19. SecureBench binds every evidence item to host-owned Challenge and Evaluation
    metadata before Oracle correlation.
20. Candidate-provided pass/fail values, scores, test reports, and guest-local
    counters have no authoritative meaning.
21. Only the Oracle computes expectations, applies thresholds, aggregates
    checks, and emits the final score.
22. Admission separately establishes base failure, reference success,
    targeted-mutant rejection, malicious-candidate rejection, and recorded
    semantic changes.

Use JSON Schema Draft 2020-12 discriminated `oneOf` branches with
`unevaluatedProperties: false`, followed by semantic validation for
references, paths, bounds, component manifests, and information flow.
Semantic component properties such as assertion-freedom and parser hardening
are enforced by registry review and admission testing rather than JSON Schema
alone.

## Deferred implementation decisions

### Component registry governance

Finalize governance for Adapter, parser, Trusted Helper, execution-profile,
and Oracle publication. The recommended initial policy is central parsers and
Trusted Helpers with reviewed pack-local Adapters and Oracles.

### Case-isolation optimization and fallback

The first implementation constructs every case from a clean baseline.
Prepare/seal/clone may be added later without changing strict semantics.
`batched-split/v1` remains a separately reported weaker fallback for rows where
fresh-case execution proves prohibitively expensive.

### Filesystem overlay format

Specify the canonical diff representation, baseline identity, deletions,
ownership and mode normalization, safe symlinks, path length and depth,
hardlinks, extended attributes, package-manager state, and protected
filesystem regions. This remains the highest-risk candidate transport.

### Oracle publication policy

Decide whether Oracle and challenge source code become public after benchmark
runs or remain private. They remain host-only during evaluation either way.

### Scoring disclosure

If high-level capability weights should be public, place them in a benchmark
methodology manifest rather than duplicating exact thresholds in rows.

### Host-resource path overlap

Overlapping host-resource paths are permitted initially. Authors should avoid
them when separate non-overlapping resources are equally clear. This may
become a validation rule or named-export mechanism if real packs show
ambiguity.
