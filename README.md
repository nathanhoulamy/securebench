# SecureBench

SecureBench is a benchmark execution framework for evaluating AI systems while
keeping benchmark data, answer keys, tests, and grading logic separate from
untrusted model or agent execution.

The current MVP supports:

- Hugging Face dataset loading
- MMLU multiple-choice evaluation
- HumanEval-style Python completion evaluation
- SWE-bench Verified row normalization
- GitHub patch evaluation with hidden patch groups and named test groups
- A minimal built-in workspace agent for repository patch production
- OpenAI-compatible Chat Completions endpoints
- Static candidate producers for smoke tests
- Workspace-agent patch producers for GitHub repair tasks
- YAML run configs
- JSONL result output

## Quick Start

Create and install the project:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[hf]'
```

Run the offline/static smoke test against MMLU rows:

```bash
.venv/bin/python -m securebench.cli run --config configs/mmlu-static-smoke.yaml --limit 3
```

For an OpenAI-compatible endpoint, put your key in `.env`:

```bash
OPENAI_API_KEY=...
```

Then run:

```bash
.venv/bin/python -m securebench.cli run --config configs/mmlu-openai-smoke.yaml --limit 5
```

Run the HumanEval smoke configs:

```bash
.venv/bin/python -m securebench.cli run --config configs/humaneval-static-smoke.yaml --limit 3
.venv/bin/python -m securebench.cli run --config configs/humaneval-openai-smoke.yaml --limit 3
```

Results are written as JSONL under `runs/`.

## Configs

Run configs are YAML files. See [docs/run-schema.md](docs/run-schema.md).

Example:

```yaml
schema_version: "0.1"

run:
  id: mmlu-openai-smoke
  limit: 10
  output_path: runs/mmlu-openai-smoke/results.jsonl

dataset:
  provider: huggingface
  name: cais/mmlu
  config: abstract_algebra
  split: test
  streaming: true

adapter:
  id: mmlu

producer:
  type: openai_compatible
  config:
    model: gpt-5.4-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    temperature: 0
    system_prompt: Answer with only one of A, B, C, or D. Do not return the choice text.

runner:
  type: multiple_choice
```

## Development

Run tests:

```bash
.venv/bin/python -m pytest -q
```

Build the workspace-agent Docker image:

```bash
docker build -f docker/agent.Dockerfile -t securebench-agent:latest .
```

The image includes SecureBench's built-in agent module, so producer configs can
run `python -m securebench.agent.run` inside the sandbox.

Run the SWE-bench Verified smoke config after building the image:

```bash
.venv/bin/python -m securebench.cli run --config configs/swebench-verified-agent-smoke.yaml --limit 1
```

This path is intentionally still a smoke path: it exercises dataset loading,
the workspace agent, candidate patch collection, hidden patch application, and
test selection, but real pass rates depend on repo-specific dependency setup
and agent quality.

## Status

This is an early MVP. The current working paths are MMLU, HumanEval smoke
evaluation, and a generic GitHub patch pipeline aimed first at SWE-bench
Verified. The Docker sandbox now uses one persistent container per sandbox
instance, while producers and runners create fresh sandbox instances at task
boundaries. The GitHub patch path still needs stronger dependency strategy,
agent traceability, and Docker hardening before broad benchmark runs.
