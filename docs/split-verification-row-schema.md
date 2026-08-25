# Proposed split-verification benchmark row schema

This document proposes an author-facing row shape for the converted
TerminalBench and DeepSWE tasks. It is a schema-design artifact only: the
current SecureBench implementation does not parse or execute these fields yet.

Concrete examples for twelve reviewed rows are in
[`examples/split-verification-rows.yaml`](examples/split-verification-rows.yaml).

## Design constraints

The proposal deliberately preserves SecureBench's current high-level shape:

- `family` still determines how an agent works (`repo_patch` or
  `terminal_task`);
- `input`, `assets`, `environment`, `eval`, and `metadata` remain the main row
  sections;
- resources still use `public`, `evaluation_inputs`, and `hidden` visibility;
- candidate production and evaluation remain separate sandbox phases.

There is no legacy or non-split evaluation mode. In this schema, `eval` always
means full split verification: the Evaluation VM may receive candidate state,
assertion-free runtime components, and one current challenge, while expected
answers and scoring remain on the host Oracle.

## Selected rows

| Row | Family | Evidence exercised | Main schema pressure |
|---|---|---|---|
| `constraints-scheduling` | TerminalBench | passive | one bounded output file, no Evaluation VM |
| `circuit-fibsqrt` | TerminalBench | black-box | immutable CLI adapter and per-case integers |
| `configure-git-webserver` | TerminalBench | black-box | restartable system overlay and two protocols |
| `cancel-async-tasks` | TerminalBench | black-box + external state | signals, timing, and a host event ledger |
| `overfull-hbox` | TerminalBench | passive + black-box | multiple checks over the same file bundle |
| `install-windows-3.11` | TerminalBench | all three | VNC/HTTP, disk bytes, and supervised QEMU launch |
| `boa-hierarchical-evaluation-cancellation` | DeepSWE | black-box | separate compile-time and runtime adapters |
| `oxvg-structural-selector-preservation` | DeepSWE | black-box + passive | candidate execution producing a hostile SVG artifact |
| `igel-persist-feature-schema` | DeepSWE | all three | lifecycle restarts, probe-model ledger, exported artifacts |
| `prometheus-transactional-reload-status` | DeepSWE | black-box + passive | service restarts and persisted state |
| `updo-policy-alerting` | DeepSWE | black-box + external state | deterministic state machine and webhook ledger |
| `arcane-drift-detection-baselines` | DeepSWE | all three | HTTP lifecycle, migrations, and host container state |

## Common row shape

```yaml
id: benchmark/task
family: repo_patch | terminal_task

input:                         # public, as today
  instructions: ...
  repo: ...                    # repo_patch only
  base_commit: ...             # repo_patch only

assets: []                     # public task assets, as today

environment:                   # agent environment, as today
  image: ...
  workdir: ...
  timeout_seconds: ...

eval:
  candidate:
    capture:
      type: git_patch | file_bundle | filesystem_overlay
      # type-specific bounds and path rules

  resources:
    resource_name:
      visibility: evaluation_inputs | hidden
      path: pack-relative/path
      kind: file | directory
      mount: /optional/evaluation/vm/path
      read_only: true

  checks:
    - id: stable_check_id
      patterns:
        - passive_artifact
        - black_box
        - trusted_external_state
      driver:
        type: artifact | cli | network_service | compile | scenario | service
        adapter: evaluation_input_resource_name
        protocol: public-versioned-protocol
      challenge:
        source: hidden_resource_name
        delivery: one_at_a_time
      external_state: []
      observe: {}
      isolation: {}

  oracle: hidden_resource_name

metadata:                      # source and conversion provenance
  source_dataset: ...
  source_revision: ...
  conversion:
    verdict: clean | semantic_change | major_redesign
    dossier: ...
```

Only fields needed by a row should be present. A passive artifact row, for
example, needs no adapter, challenge, external service, or Evaluation VM.

## Candidate handoff

`eval.candidate.capture` defines the only candidate-controlled state that may
cross from the Agent VM to evaluation.

### `git_patch`

Used by `repo_patch`. SecureBench extracts a canonical patch and applies it to
the declared base commit in a fresh Evaluation VM. Test files, runner scripts,
reports, and SecureBench-owned paths can be excluded before application.

### `file_bundle`

Used by most `terminal_task` conversions. Each exported path declares its
type, size, and count bounds. Symlinks, devices, sockets, and undeclared paths
are rejected unless a task explicitly requires another policy.

### `filesystem_overlay`

Used only for terminal tasks whose result is system configuration rather than
a few files. It captures a bounded allowlisted filesystem diff, never live
processes. A fresh Evaluation VM applies the overlay and starts services under
an external supervisor. This transport needs substantially more auditing than
`file_bundle`, so it should not become the default terminal candidate shape.

Candidate capture is orchestration policy, not an evaluation input. Its public
contract should be shown to the agent so the agent knows what will survive the
handoff.

## Resource routing

`eval.resources` makes the existing visibility boundary explicit instead of
inferring it from names such as `checker` or `tests`.

| Visibility | Agent VM | Evaluation VM | Host Oracle | Typical contents |
|---|---:|---:|---:|---|
| `public` | yes | yes | yes | prompt, repository, public task assets |
| `evaluation_inputs` | no | yes | yes | assertion-free adapter/runtime files |
| `hidden` | no | no | yes | case generators, corpora, expected values, Oracle code |

The current challenge is ephemeral rather than a fourth static visibility:

```text
hidden case source --host selects/derives one case--> ephemeral evaluation_input
```

The Evaluation VM receives only that current case. The complete case source,
expected result, thresholds, and aggregation logic remain `hidden`.

## Checks and patterns

Patterns are declared per check, not only once per row. This matters because a
single row may use different evidence paths for different properties.

- `passive_artifact`: the host retrieves bounded hostile bytes or metadata and
  verifies them without executing candidate-controlled content.
- `black_box`: candidate-controlled code runs only in the Evaluation VM on a
  current challenge, producing bounded observations for the host.
- `trusted_external_state`: the candidate interacts with a capability-scoped,
  host-owned service or supervisor whose state the host inspects directly.

The row's effective pattern set is the union of its checks. This is more exact
than a single dossier label. For example, an optimizer patch that must execute
to produce an SVG is a black-box transformation; independently parsing the
returned SVG is passive verification. The concrete OXVG example therefore
declares both patterns even though its review dashboard uses the shorter
"Passive artifact verification" label.

## Drivers and adapters

`driver.type` selects a small SecureBench-controlled orchestration primitive.
An optional `adapter` names an `evaluation_inputs` resource. The adapter must:

1. be public, versioned, reusable, and assertion-free;
2. contain no expected values, scoring rules, thresholds, or case whitelist;
3. return observations rather than `passed`, `score`, or another verdict;
4. accept only typed, bounded current-case inputs;
5. run only in the Evaluation VM when it processes candidate-controlled code.

The adapter's executable need not be placed in the Agent VM. Its protocol and
candidate-facing contract must nevertheless be public.

## Challenges

`challenge.source` references a `hidden` resource. `delivery: one_at_a_time`
means the host derives one bounded case and materializes only that case in the
Evaluation VM. A challenge may contain inputs, actions, schedules, source
programs, configuration, or opaque capability endpoints. It must not contain
an expected answer or assertion.

`isolation.scope` controls case state:

- `case`: fresh Evaluation VM for each case;
- `scenario`: one fresh VM for a bounded multi-step scenario, allowing
  supervisor-controlled restarts inside it;
- `task`: only when cross-case persistence is itself the declared property.

`task` should be rare because it increases special-casing and leakage risk.

## Trusted external state

An external-state declaration names a trusted service type and grants the
Evaluation VM only the capability it needs. Examples include append-only HTTP
or callback ledgers, SMTP sinks, probe-model services, controlled origins, and
process launch supervisors.

```yaml
external_state:
  - id: events
    service: append_only_event_ledger
    evaluation_capabilities: [append]
    oracle_capabilities: [inspect]
    reset: per_case
    limits:
      events: 128
      body_bytes: 4096
```

The service configuration and inspection credential never enter the Evaluation
VM. The VM receives a per-case endpoint or token restricted to the declared
capability.

## Oracle and scoring

`eval.oracle` must reference a `hidden` resource. The Oracle owns case
selection/generation, expected values, normalization, thresholds, evidence
correlation, scoring, and the final verdict. Keeping aggregation inside this
host-only resource avoids duplicating secret scoring rules in row fields or
adapters.

Oracle code may parse bounded hostile artifacts using hardened parsers. It must
never import, link, execute, deserialize as a language object, or otherwise
activate candidate-controlled code.

## Required validation invariants

A future schema validator should reject a row when:

- an adapter or static challenge resource is not explicitly routed;
- a referenced adapter is not `evaluation_inputs`;
- a referenced case source or Oracle is not `hidden`;
- `challenge.delivery` exposes a corpus as a whole without a reviewed reason;
- a candidate export lacks a size/count/type bound;
- an observation channel lacks byte/count/time bounds;
- a trusted service grants broader Evaluation VM capabilities than declared;
- an adapter observation schema contains an authoritative verdict;
- `checker`, `tests`, `test_patch`, or another assertion-bearing verifier is
  mounted into the Evaluation VM;
- a passive check requires executing or dangerously deserializing the candidate
  on the host;
- case isolation is absent for a stateful driver.

## What the examples reveal

The twelve concrete rows exercise three candidate handoffs, six driver types,
all three verification patterns, multiple checks per row, scenario-local
restarts, and host-owned ledgers/supervisors. They also reveal two design issues
that should be resolved before implementation:

1. Some dossier-level pattern labels describe only the authoritative returned
   artifact and omit the black-box execution needed to create it. Check-level
   declarations remove that ambiguity.
2. A few TerminalBench system-administration tasks need bounded filesystem
   overlays. Treating the retained agent workspace as the complete candidate
   would silently lose `/etc`, service, or installation state.

Neither issue requires replacing SecureBench's resource visibility model or
its two-sandbox architecture.
