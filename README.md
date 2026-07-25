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

For named provider harness runs, put the relevant provider credential in `.env`
on the host:

```bash
OPENAI_API_KEY=...
# ANTHROPIC_API_KEY=...
# CLAUDE_CODE_OAUTH_TOKEN=...
```

Claude Code supports either an Anthropic API key or a Claude subscription. To
use a Pro, Max, Team, or Enterprise subscription, generate a token with
`claude setup-token`, store it as `CLAUDE_CODE_OAUTH_TOKEN`, and set
`harness.config.auth: subscription`. API-key authentication remains the default.

Named provider harnesses keep the real credential on the host side. SecureBench
gives the agent container a dummy credential and routes model API traffic
through a SecureBench provider relay that injects the real credential outside
the untrusted sandbox; the `.env` file is not mounted into the agent container.
Provider-hosted external tools are blocked unless the tester YAML explicitly
sets `harness.config.allow_external_tools: true`.

Then run a repo-patch pack:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/deep-swe/tester-codex.yaml \
  --limit 1
```

Candidate records are written to `runs/<run-id>/candidates.jsonl`; per-task
workspaces are written under `runs/<run-id>/workspaces/`.

## Tester YAML

```yaml
schema_version: "0.2"

run:
  id: terminal-bench-codex-gpt-5.4-mini
  output_dir: ../../runs/terminal-bench-codex-gpt-5.4-mini

benchmark:
  manifest: manifest.yaml
  tasks: tasks.jsonl

harness:
  type: codex
  config:
    model: gpt-5.4-mini
    version: latest
    task_file: task.json
    timeout_seconds: 900
    allow_external_tools: false
```

The CLI loads `.env` by default. Use `--env-file path/to/.env` when needed.

For a Claude Code subscription run:

```yaml
harness:
  type: claude_code
  config:
    auth: subscription
    model: sonnet
```

Valid Claude Code authentication modes are `api_key` and `subscription`.
Provider credential names do not need to appear in `harness.env`; the harness
filters `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and
`CLAUDE_CODE_OAUTH_TOKEN` from agent-container pass-through.

## Development

```bash
.venv/bin/python -m pytest -q
```
