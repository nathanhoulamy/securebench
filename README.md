# SecureBench

SecureBench runs agent benchmarks with a hard boundary between candidate
production and correctness evaluation. Benchmark packs use the strict v2
schema: public Agent inputs, evaluation-runtime resources, and host-only Oracle
resources have separate source roots and component views.

The two current row families describe the Agent task, not its verification topology:

- `repo_patch` declares repository repair inputs and a `git_patch` candidate.
- `terminal_task` declares terminal instructions and a `file_bundle` or
  `filesystem_overlay` candidate.

Verification is composed independently from candidate capture, artifact or
protocol checks, parser profiles, and a host-only Oracle. The first executable
batch supports `strict-split/v1`, `file_bundle`, artifact checks, and the Oracle
process ABI. Git patches, overlays, protocol checks, and the weaker registered
batching profile remain schema-valid but fail preflight until their engines are
implemented.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pytest -q
```

The checked-in executable reference is the converted TerminalBench
`constraints-scheduling` row:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench/tester-codex.yaml
```

Set the relevant provider credential in `.env`. Named Codex and Claude Code
harnesses keep real credentials in host-side relays and expose dummy
credentials to the Agent container. Codex subscription login is managed with:

```bash
.venv/bin/python -m securebench.cli auth codex login
.venv/bin/python -m securebench.cli auth codex status
```

See [provider authentication](docs/provider-authentication.md) for details.

## Tester YAML

Tester configuration selects orchestration only; evaluation policy belongs to
the row schema.

```yaml
schema_version: "1.0"
run:
  id: terminal-bench-v2-codex
  output_dir: ../../runs/terminal-bench-v2-codex
  max_workers: 1
benchmark:
  manifest: manifest-v2.yaml
  tasks: tasks-v2.jsonl
harness:
  type: codex
  config:
    model: gpt-5.6-luna
    reasoning_effort: max
    task_file: task.json
    allow_external_tools: false
docker:
  max_cached_images: 2
```

Each run writes sanitized `results.jsonl`, immutable candidate manifests and
blobs under `artifacts/`, and ephemeral per-row Agent workspaces under
`workspaces/`. Resume accepts a prior row only when its run id and row digest
match the current pack.

The author-facing schema and examples are documented in
[the recommended row schema](docs/final-recommended-row-schema.md) and
[example rows](docs/examples/final-recommended-row-examples.yaml).
