# SecureBench

SecureBench is a benchmark execution framework for agentic security evaluation.
It keeps public task data, candidate-producing harnesses, evaluation inputs, and
trusted verifier data separated.

The active benchmark families are:

- `repo_patch`: agents edit a repository checkout; SecureBench extracts a git diff and verifies it in the benchmark image.
- `terminal_task`: agents work in a terminal workspace; SecureBench verifies the final workspace state with trusted checkers.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Run the terminal-task smoke pack through the command harness:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-task-smoke/tester-command.yaml
```

For named provider harness runs, put the relevant provider key in `.env` on the
host:

```bash
OPENAI_API_KEY=...
# ANTHROPIC_API_KEY=...
```

Named provider harnesses keep the real key on the host side. SecureBench gives
the agent container a dummy key and routes model API traffic through a
SecureBench provider relay that injects the real credential outside the
untrusted sandbox; the `.env` file is not mounted into the agent container.
Provider-hosted external tools are blocked unless the tester YAML explicitly
sets `harness.config.allow_external_tools: true`.

Then run a repo-patch pack:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/deep-swe-first3/tester-codex.yaml \
  --limit 1
```

Candidate records are written to `runs/<run-id>/candidates.jsonl`; per-task
workspaces are written under `runs/<run-id>/workspaces/`.

## Tester YAML

```yaml
schema_version: "0.2"

run:
  id: terminal-task-smoke-command
  output_dir: ../../runs/terminal-task-smoke-command

benchmark:
  manifest: manifest.yaml
  tasks: tasks.jsonl

harness:
  type: command
  config:
    command: "python3 - <<'PY'\nfrom pathlib import Path\nPath('output.txt').write_text('securebench terminal task\\n')\nPY"
    task_file: task.json
    timeout_seconds: 300
```

The CLI loads `.env` by default. Use `--env-file path/to/.env` when needed.

## Development

```bash
.venv/bin/python -m pytest -q
```
