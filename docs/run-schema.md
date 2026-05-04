# Run Schema

This is the first executable SecureBench run schema. It describes a benchmark
run independently of any one benchmark family: where rows come from, which
adapter normalizes them, which producer creates candidate outputs, which runner
scores them, and where results are written.

The parser accepts YAML.

The MVP implementation supports Hugging Face datasets, built-in adapters,
static and OpenAI-compatible producers, and the multiple-choice runner. The
schema is shaped so code-generation and repository patch tasks can add
runner/producer kinds without changing the top-level layout.

## MMLU Example

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
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    temperature: 0
    system_prompt: Answer with only one of A, B, C, or D. Do not return the choice text.

runner:
  type: multiple_choice
```

## Fields

`schema_version`
: Required. Currently `"0.1"`.

`run.id`
: Required stable identifier for this run.

`run.limit`
: Optional maximum number of dataset rows to evaluate.

`run.output_path`
: Required JSONL output path for per-row results.

`dataset.provider`
: Required. Currently only `"huggingface"` is valid for this schema.

`dataset.name`
: Required Hugging Face dataset name, such as `"cais/mmlu"`.

`dataset.config`
: Optional Hugging Face dataset config/subset. MMLU uses this for subject
subsets such as `"abstract_algebra"` or `"computer_security"`.

`dataset.split`
: Required split, usually `"test"`, `"validation"`, or `"dev"`.

`dataset.revision`
: Optional pinned Hugging Face dataset revision.

`dataset.streaming`
: Optional boolean. When true, rows are streamed instead of eagerly downloaded.

`adapter.id`
: Required built-in adapter ID, such as `"mmlu"`.

`producer.kind`
: Required. Supported MVP values:

- `"openai_compatible"`: calls a Chat Completions compatible endpoint.
- `"static"`: returns fixed text, useful for tests and smoke checks.

`producer.config`
: Required producer-specific configuration.

For `"openai_compatible"`:

- `model`: required model name.
- `base_url`: optional endpoint base URL. Defaults to
  `"https://api.openai.com/v1"`.
- `api_key_env`: optional environment variable containing the API key. Defaults
  to `"OPENAI_API_KEY"`.
- `timeout`: optional request timeout in seconds.
- `temperature`: optional sampling temperature.
- `system_prompt`: optional system prompt.
- `extra_body`: optional object merged into the request body.

For `"static"`:

- `text`: required fixed model output.

`runner.type`
: Required runner type. For MMLU this is `"multiple_choice"`.

## Security Invariant

The producer receives only `task.agent_payload()`, never the full normalized
task object. For MMLU, that means the hidden `answer` field remains evaluator
data and is not sent to the model.

## Running

Static smoke run:

```bash
.venv/bin/python -m securebench.cli run --config configs/mmlu-static-smoke.yaml
```

OpenAI-compatible smoke run:

```bash
.venv/bin/python -m securebench.cli run --config configs/mmlu-openai-smoke.yaml
```

The CLI loads `.env` by default before running. Store local secrets there:

```bash
OPENAI_API_KEY=...
```

Use a different environment file when needed:

```bash
.venv/bin/python -m securebench.cli run --config configs/mmlu-openai-smoke.yaml --env-file path/to/.env
```

Install Hugging Face dataset support before running configs that use
`dataset.provider: huggingface`:

```bash
.venv/bin/python -m pip install -e '.[hf]'
```
