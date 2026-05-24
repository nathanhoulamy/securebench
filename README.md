# SecureBench

SecureBench is a benchmark execution framework for evaluating AI systems while
keeping benchmark rows, public task data, candidate-producing harnesses, and
trusted verifier data separated.

The current implementation is centered on benchmark packs and tester YAML:

- benchmark-pack manifests and JSONL task rows
- visibility-aware public/evaluation/hidden resource compilation
- tester YAML harness configs
- containerized command harness smoke runs
- Codex CLI harness execution with a mounted tooling overlay
- shared candidate artifact extraction
- code-completion, repo-patch, and terminal-task verification with JSONL result output

Additional family verifiers are still being added.

## Quick Start

Create and install the project:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

For Codex harness runs, put your key in `.env`:

```bash
OPENAI_API_KEY=...
```

Run the code-completion smoke pack through candidate extraction and verification:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/code-completion-smoke/tester-codex.yaml \
  --limit 1
```

Run the terminal-task smoke pack through a command harness:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-task-smoke/tester-command.yaml
```

Candidate records are written to:

```text
runs/code-completion-smoke-codex/candidates.jsonl
```

Per-task harness workspaces are written under:

```text
runs/code-completion-smoke-codex/workspaces/
```

## Tester YAML

Tester YAML selects a benchmark pack and candidate-producing harness:

```yaml
schema_version: "0.2"

run:
  id: code-completion-smoke-codex
  output_dir: ../../runs/code-completion-smoke-codex

benchmark:
  manifest: manifest.yaml
  tasks: tasks.jsonl

harness:
  type: codex
  env:
    - OPENAI_API_KEY
  config:
    model: gpt-5.4-mini
    version: latest
    task_file: task.json
    timeout_seconds: 300
```

The CLI loads `.env` by default. Use another env file when needed:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/code-completion-smoke/tester-codex.yaml \
  --env-file path/to/.env
```

## Documentation

Canonical references live in `docs/`:

- `benchmark-family-standard.html`: benchmark pack and family schema standard.
- `benchmark-family-examples.html`: practical family examples.
- `tester-yaml-standard.html`: tester YAML and harness configuration.
- `security-presentation.html`: visual overview for presenting the system.
- `next.md`: current engineering follow-ups.
- `legacy.md`: where archived prototype code and notes live.

## Development

Run tests:

```bash
.venv/bin/python -m pytest -q
```

The old Hugging Face-oriented CLI path has been removed from the command line.
Legacy modules remain in the repository during the transition, but `securebench
run` now expects tester YAML.
