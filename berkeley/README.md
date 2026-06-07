# Berkeley Agentic Adversarial Testing

This directory is a staging workspace for Berkeley-facing red-team runs. It is
kept outside the core `securebench` package for now so the interface can be
reviewed and moved into the proper modules later.

The runner executes adversarial agents as normal candidate producers: agents see
only public task data, produce an ordinary candidate, and SecureBench verifies
that candidate with the existing verifier path.

## Quick Start

Prerequisites:

- SecureBench development dependencies installed in `.venv`.
- Docker available for benchmark containers.
- `OPENAI_API_KEY` set on the host for `live_openai` runs.

Live OpenAI-backed adversarial agents use SecureBench's existing provider relay.
The real key remains host-side; the adversary container receives a dummy key and
`OPENAI_BASE_URL` pointing at the relay. The model receives the public task plus
one adversarial profile prompt, returns bounded JSON actions, and the local
executor runs those actions inside the sandbox.

```bash
OPENAI_API_KEY=... .venv/bin/python -m berkeley.run --config berkeley/configs/audit-terminal-live-openai.yaml
OPENAI_API_KEY=... .venv/bin/python -m berkeley.run --config berkeley/configs/audit-terminal-live-openai-leak-probe.yaml
OPENAI_API_KEY=... .venv/bin/python -m berkeley.run --config berkeley/configs/audit-repo-patch-live-openai-repo-tamper.yaml
```

Bundled prompt profiles are `auto`, `leak_probe`, `repo_tamper`,
`terminal_poison`, `network_exfil`, `output_only`, `evaluator_escape`, and
`artifact_forgery`. Each profile is a prompt objective sent to the model in
addition to the public benchmark task; the model then chooses actions at runtime.

The default configs target the audit benchmark packs because they are small and
exercise the implemented SecureBench families. Larger `repo_patch` and
`terminal_task` packs can be used by changing `benchmark.manifest` and
`benchmark.tasks` in a copied config.

## Config Shape

```yaml
run:
  id: berkeley-run-id
  output_dir: ../runs/berkeley-run-id

benchmark:
  manifest: ../../benchmarks/audit/terminal-task/manifest.yaml
  tasks: ../../benchmarks/audit/terminal-task/tasks.jsonl
  limit: 1

adversary:
  mode: live_openai
  profile: leak_probe
  timeout_seconds: 180
  max_steps: 4

provider:
  model: gpt-5.4-mini
  allow_external_tools: false
```

`adversary.mode` is either `live_openai` or `external`. For `external`, replace
the live fields with a `command` array or string. `provider.allow_external_tools`
defaults to `false`; keep it false for standard security evidence.

## Outputs

Each run writes:

- `results.jsonl`: SecureBench candidate records plus Berkeley adversary trace.
- `summary.json`: aggregate totals.
- `traces/*.json`: one adversary trace per task.

Interpretation:

- `summary.passed`: tasks where the adversarial candidate passed normal
  SecureBench verification.
- `summary.adversary_violations`: tasks where the adversary observed a
  framework-level security issue, such as hidden data or a real key.
- `trace.errors`: run/provider/model-format problems; these are not security
  violations by themselves.
- `trace.violations`: security evidence. Non-empty values should be investigated
  before claiming the benchmark is robust.

## Realism Pass

Audit configs are the canonical security-boundary probes. Realism configs use
selected SWE-bench Verified and Terminal-Bench tasks to show those boundaries
still hold on realistic task packaging.

Run a preflight image check before live realism runs:

```bash
.venv/bin/python -m berkeley.preflight
```

Then run one realism profile:

```bash
OPENAI_API_KEY=... .venv/bin/python -m berkeley.run --config berkeley/configs/realism-swe-repo-tamper.yaml
OPENAI_API_KEY=... .venv/bin/python -m berkeley.run --config berkeley/configs/realism-terminal-output-only.yaml
```

SWE-bench configs use the task-declared images. Terminal-Bench configs also use
the task-declared image names, so images such as
`securebench-terminal-bench-jsonl-aggregator:latest` must exist locally before
the run. Build missing Terminal-Bench images from the checked-in Dockerfiles:

```bash
docker build -t securebench-terminal-bench-jsonl-aggregator:latest benchmarks/terminal-bench/docker/jsonl-aggregator
docker build -t securebench-terminal-bench-model-extraction-relu-logits:latest benchmarks/terminal-bench/docker/model-extraction-relu-logits
docker build -t securebench-terminal-bench-gomoku-planner:latest benchmarks/terminal-bench/docker/gomoku-planner
```

## External Agents

Berkeley can replace the bundled adversary with an external command:

```bash
.venv/bin/python -m berkeley.run --config berkeley/configs/external-agent-example.yaml
```

See [agents/external_contract.md](agents/external_contract.md) for the runtime
contract.

The external command runs inside the benchmark image with the same public
workspace and, when provider access is enabled, the same relay-backed dummy-key
provider environment. It should leave an ordinary SecureBench candidate: a git
diff for `repo_patch`, or final workspace state for `terminal_task`.
