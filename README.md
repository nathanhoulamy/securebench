# SecureBench

SecureBench is a benchmark execution framework for evaluating AI systems while
keeping benchmark data, answer keys, tests, and grading logic separate from
untrusted model or agent execution.

The current MVP supports:

- Hugging Face dataset loading
- MMLU multiple-choice evaluation
- OpenAI-compatible Chat Completions endpoints
- Static candidate producers for smoke tests
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
  kind: openai_compatible
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

## Status

This is an early MVP. The current working path is MMLU multiple-choice
evaluation. Code-generation and GitHub patch task abstractions exist, but their
full production run flows still need hardening.
