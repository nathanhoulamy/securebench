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

Claude Code supports either an Anthropic API key or an eligible Claude
subscription. Generate a token with `claude setup-token`, store it as
`CLAUDE_CODE_OAUTH_TOKEN`, and set `harness.config.auth: subscription`.

Codex supports either an OpenAI API key or a ChatGPT subscription. Create an
isolated SecureBench login with:

```bash
.venv/bin/python -m securebench.cli auth codex login
.venv/bin/python -m securebench.cli auth codex status
```

This delegates the browser login to the installed Codex CLI and stores its
credentials separately under `~/.config/securebench/auth/codex`. SecureBench
refreshes the login as needed. It does not import or modify your normal Codex
login. Set `SECUREBENCH_AUTH_HOME` to override the SecureBench auth directory.

API-key authentication remains the default for both harnesses. See
[Provider Authentication](docs/provider-authentication.md) for complete setup,
benchmark commands, credential lifecycle, security behavior, and
troubleshooting for Claude and Codex subscription runs.

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
  # Optional: run multiple benchmark rows concurrently (default: 1).
  max_workers: 2

benchmark:
  manifest: manifest.yaml
  tasks: tasks.jsonl

docker:
  # Optional: remove exact benchmark image references in batches.
  max_cached_images: 2

harness:
  type: codex
  config:
    model: gpt-5.4-mini
    reasoning_effort: high
    version: latest
    task_file: task.json
    timeout_seconds: 900
    allow_external_tools: false
```

The CLI loads `.env` by default. Use `--env-file path/to/.env` when needed.

`run.max_workers` controls bounded row-level parallelism across candidate
production and verification. Override it for one run with `--workers N`.
Results are appended atomically as rows finish, so resume remains safe even
when completion order differs from task-file order.

`docker.max_cached_images` limits benchmark image accumulation without touching
unrelated Docker images. SecureBench removes each full batch after its tasks
finish and pulls an image again if a later task needs it. You can override the
YAML value with `--max-cached-images N`. A final partial batch remains cached.
With parallel workers, an image is not eligible for removal until every
scheduled row that uses it has finished. Size the worker count and cleanup
batch together for the available disk and memory.

For a Codex ChatGPT subscription run:

```yaml
harness:
  type: codex
  config:
    auth: subscription
    model: gpt-5.4-mini
```

Valid Codex authentication modes are `api_key` and `subscription`. API-key
authentication remains the default, so existing tester files do not change.
`reasoning_effort` is optional and accepts `minimal`, `low`, `medium`, `high`,
or `xhigh`; when omitted, Codex uses the selected model's default.

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

Complete runnable subscription examples are available at:

- [`docs/examples/tester-codex-subscription.yaml`](docs/examples/tester-codex-subscription.yaml)
- [`docs/examples/tester-claude-code-subscription.yaml`](docs/examples/tester-claude-code-subscription.yaml)

## Development

```bash
.venv/bin/python -m pytest -q
```
