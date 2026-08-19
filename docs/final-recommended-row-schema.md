# Final recommended split-verification row schema

Status: revised design recommendation for implementation and peer review

## Recommendation

Use a check-centric schema built around one replayable candidate, two check
types, and three centrally enforced visibility lanes.

- The candidate is exactly one durable handoff: `git_patch`,
  `file_bundle`, or `filesystem_overlay`.
- An `artifact` check inspects bounded candidate data without executing
  candidate code.
- A `protocol` check runs the candidate through a public, assertion-free
  adapter against one current host-selected case.
- Trusted evaluation services are declared inside the protocol check that
  uses them.
- Public, Evaluation-runtime-only, and host-only resources are separated
  structurally and compiled into SecureBench visibility lanes.
- The host Oracle owns expectations, evidence correlation, scoring, and the
  final verdict.

The schema retains the useful benchmark-pack envelope and resource-routing
model already implemented by SecureBench. It replaces family-specific
verification with a common split-verification engine.

Complete example rows are in
[`examples/final-recommended-row-examples.yaml`](examples/final-recommended-row-examples.yaml).

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
| protocol check with `services` | trusted external state |
| protocol check with returned `artifacts` | black-box plus passive artifact inspection |

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

A protocol check may return bounded artifacts and use trusted evaluation
services. All observations, artifacts, service records, and supervisor facts
from one execution are bound by SecureBench to the same check ID, case ID,
challenge digest, runtime, and host-generated correlation identifier.

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

### Treat external state as trusted evaluation infrastructure

Trusted services have a candidate-facing data plane and a host-only control
and evidence plane. Their registered component profiles fix those
capabilities; row authors cannot add capabilities.

The row supplies only:

- a check-local service ID;
- a registered component;
- an optional host-only configuration resource;
- component-specific reduced bounds.

Examples include HTTP request ledgers, controlled origins, SMTP sinks, probe
models, byte relays, databases, clocks, and process supervisors.

Service instances, credentials, and state are fresh for every case under the
strict execution profile. Multi-phase persistence within a case is allowed
when it is part of that case's declared protocol.

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
protected-path policy that rows cannot weaken. Bounds are checked on both the
canonical patch and its materialized result.

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
`max_total_bytes`. Detailed candidate-specific path semantics remain part of
the materializer specification.

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
    services:
      - id: request_ledger
        component: securebench.http-request-ledger/v1
        configuration: host.request_ledger_config
        limits:
          requests: 128
          request_body_bytes: 65536
    artifacts:
      - id: generated_result
        parser: securebench.strict-json/v1
        limits:
          max_bytes: 1048576
    limits:
      seconds_per_case: 30
      observation_bytes_per_case: 1048576
~~~

`services` and `artifacts` are optional. The referenced adapter resource
contains a reviewed public manifest and implementation. The manifest defines
the runtime command, typed request and observation schemas, topology,
endpoint exposure, output artifact IDs, and service-handle injection.

Under `strict-split/v1`, every protocol case receives a fresh runtime
topology, service instances, credentials, and host correlation identifier. A
bounded multi-step lifecycle is one case, not cross-case persistence.

## Execution profiles

An execution profile selects framework isolation and information-flow
semantics. It does not select cases, expected answers, scoring, or task
behavior.

### Strict split

`strict-split/v1` requires:

- host resources never enter candidate-controlled VMs;
- one current challenge is delivered at a time;
- a fresh Evaluation topology and fresh trusted services per case;
- fresh credentials and correlation identifiers per case;
- capability-restricted Evaluation networking;
- read-only runtime resources;
- candidate code executing only in Evaluation runtimes;
- bounded challenge, observation, artifact, service, time, and resource
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
prohibitive. It must still reset trusted services and credentials and must
report runtime reuse explicitly. It is weaker because candidate state may
cross case boundaries and must not be presented as equivalent to strict split
verification.

## Component contracts

The row schema references four component classes. Their contracts are
versioned separately from rows.

### Adapter contract

An adapter manifest defines:

- public protocol identifier and typed request/observation schemas;
- bounded command and runtime topology;
- service slots and handle-injection mechanism;
- declared output artifact IDs;
- restart or multi-peer behavior;
- protocol-specific limits.

Adapters run only in Evaluation runtimes, contain no hidden expectations or
scoring logic, and return observations rather than authoritative verdicts.

### Parser contract

A parser profile defines accepted bytes, normalization, typed output,
hardening, output bounds, and whether it runs in an isolated observer.
Parsers never import or activate candidate content as a language object.

### Trusted-service contract

A service profile defines its fixed candidate-facing data plane, host-only
control plane, evidence schema, reset behavior, credential handling, and
component-specific limit schema. Rows may reduce limits but cannot add
capabilities.

### Oracle contract

The Oracle resource contains a reviewed manifest and implementation conforming
to the standard Oracle ABI:

1. `initialize(row, run_seed)` starts a deterministic host-only session;
2. `evaluate_artifact(check_id, evidence)` consumes passive-check evidence;
3. `next_case(check_id, challenge_source, bounds)` returns one bounded current
   challenge plus opaque host-only case context, or reports exhaustion;
4. `evaluate_case(check_id, case_context, evidence)` consumes one correlated
   case envelope; and
5. `finalize()` returns the final structured score, verdict, and bounded public
   diagnostics.

This lifecycle supports static corpora, generated and adaptive cases, private
case context, and final aggregation. The Oracle never executes or dynamically
loads candidate-controlled content.

Central parsers and services with reviewed pack-local adapters and Oracles are
the recommended initial registry policy.

## Framework evidence envelope

The evidence envelope is an internal SecureBench-to-Oracle interface, not an
author-written row section. A representative record is:

~~~yaml
check_id: public_behavior
case:
  id: case-0042
  challenge_digest: sha256:...
  challenge: <host-side authoritative copy>
runtime:
  exit_status: 0
  timed_out: false
  duration_ms: 821
  resource_usage:
    peak_memory_bytes: 73400320
observation:
  schema: securebench.example-observation/v1
  value: {}
  truncated: false
artifacts:
  generated_result:
    digest: sha256:...
    parser: securebench.strict-json/v1
    parsed_value: {}
services:
  request_ledger:
    schema: securebench.http-request-ledger-evidence/v1
    records: []
    truncated: false
infrastructure:
  status: ok
~~~

SecureBench, not the candidate, assigns check IDs, case IDs, digests,
timestamps, truncation markers, and infrastructure status. The envelope must
distinguish candidate failures from adapter, parser, service, and framework
failures.

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
| `artifact.source.path` | conditional | References a bounded materialized patch or overlay path. |
| `artifact.parser` | yes | Registered parser profile. |
| `artifact.limits` | yes | Either `max_bytes` for a regular file or `max_files` (all filesystem entries) plus `max_total_bytes` for a tree. |
| `protocol.adapter` | Protocol check only | Runtime-resource reference containing adapter manifest and implementation. |
| `protocol.protocol` | Protocol check only | Public versioned protocol ID validated against the adapter manifest. |
| `protocol.challenge` | Protocol check only | Host source and current-case bounds. |
| `challenge.source` | yes | Host resource containing a case generator or corpus. |
| `challenge.max_cases` | yes | Maximum cases selected for this check. |
| `challenge.max_case_bytes` | yes | Maximum serialized current-case bytes. |
| `protocol.services` | no | Check-local trusted evaluation-service instances. |
| `service.id` | conditional | Check-local service ID visible to the adapter protocol. |
| `service.component` | conditional | Registered service profile with fixed capabilities. |
| `service.configuration` | no | Host-only, component-validated service configuration. |
| `service.limits` | conditional | Component-specific reduced bounds. |
| `protocol.artifacts` | no | Candidate-generated artifacts captured after a case. |
| `protocol.artifacts[].id` | conditional | Artifact ID declared by the adapter protocol. |
| `protocol.artifacts[].parser` | conditional | Registered parser profile. |
| `protocol.artifacts[].limits` | conditional | Byte or tree input bounds for a returned artifact. |
| `protocol.limits` | Protocol check only | Universal per-case time and observation bounds. |
| `verification.oracle` | yes | Host-resource reference implementing the standard Oracle ABI. |
| `metadata` | no | Provenance and conversion-review information with no runtime authority. |

## Stress test against representative rows

| Requirement | Representative row | Representation |
|---|---|---|
| Passive-only output | `constraints-scheduling` | File bundle and one artifact check |
| Hidden CLI cases | `circuit-fibsqrt` | File bundle and one protocol check |
| System configuration and protocols | `configure-git-webserver` | Overlay and protocol check |
| Timing, signals, independent ledger | `cancel-async-tasks` | Protocol check with ledger and supervisor services |
| Separate checks over one candidate | `overfull-hbox` | Artifact and protocol checks |
| All three review patterns | `install-windows-3.11` | Overlay, artifact check, protocol check, launch service |
| Two public interfaces | `boa-hierarchical-evaluation-cancellation` | Two protocol checks over one patch |
| Runtime-generated structured artifact | `oxvg-structural-selector-preservation` | Protocol check with returned SVG artifact |
| Multi-phase persistence and probe calls | `igel-persist-feature-schema` | One lifecycle case with probe service and artifacts |
| Two candidate peers | `kcp-go-multiplexed-kcp-streams` | Adapter topology with two peers and byte relay |
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
12. Candidate capture, challenges, observations, artifacts, service channels,
    and runtime execution are bounded.
13. Under strict split, every case receives fresh runtime and service state.
14. Adapter protocols are public, versioned, typed, bounded, and
    assertion-free.
15. Service profiles fix least-privilege interfaces; rows may reduce limits
    but cannot add capabilities.
16. Candidate code executes only in Evaluation runtimes.
17. The Oracle never imports, links, executes, unpickles, or dynamically loads
    candidate-controlled content.
18. Registered parsers treat candidate bytes as hostile data.
19. SecureBench binds every evidence item to host-owned check and case
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

Finalize adapter, parser, trusted-service, execution-profile, and Oracle
manifest schemas. The recommended initial policy is central parsers and
services with reviewed pack-local adapters and Oracles.

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
