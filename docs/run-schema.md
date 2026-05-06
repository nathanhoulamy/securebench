# Run Schema

This is the first executable SecureBench run schema. It describes a benchmark
run independently of any one benchmark family: where rows come from, which
adapter normalizes them, which producer creates candidate outputs, which runner
scores them, and where results are written.

The parser accepts YAML.

The MVP implementation supports Hugging Face datasets, built-in adapters,
static and OpenAI-compatible text producers, a workspace-agent patch producer,
and runners for multiple-choice, HumanEval-style code generation, and generic
GitHub patch evaluation.

Adapters normalize rows through a plain task spec. Custom Python adapters,
future declarative adapters, and native normalized datasets should all target
this shape:

```yaml
id: task-id
benchmark_id: benchmark-name
task_type: multiple_choice
metadata: {}
resources:
  question:
    value: "2 + 2?"
    visibility: public
  choices:
    value: ["1", "2", "4", "5"]
    visibility: public
  answer:
    value: 2
    visibility: hidden
```

`visibility` must be one of `public`, `evaluation_inputs`, or `hidden`.
SecureBench converts this plain spec into internal task and resource objects.

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
  type: openai_compatible
  config:
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    temperature: 0
    system_prompt: Answer with only one of A, B, C, or D. Do not return the choice text.

runner:
  type: multiple_choice
```

## HumanEval Example

```yaml
schema_version: "0.1"

run:
  id: humaneval-openai-smoke
  limit: 3
  output_path: runs/humaneval-openai-smoke/results.jsonl

dataset:
  provider: huggingface
  name: openai/openai_humaneval
  config: openai_humaneval
  split: test
  streaming: true

adapter:
  id: humaneval

producer:
  type: openai_compatible
  config:
    model: gpt-5.4-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    temperature: 0
    system_prompt: You are completing a Python function. Return only the indented function body that should be appended after the provided prompt. Do not repeat imports, decorators, the function signature, Markdown fences, or explanation.

runner:
  type: code_generation
```

## SWE-bench Verified Smoke Example

```yaml
schema_version: "0.1"

run:
  id: swebench-verified-agent-smoke
  limit: 1
  output_path: runs/swebench-verified-agent-smoke/results.jsonl

dataset:
  provider: huggingface
  name: princeton-nlp/SWE-bench_Verified
  split: test
  streaming: true

adapter:
  id: swebench_verified

producer:
  type: workspace_agent_patch
  config:
    image: securebench-agent:latest
    model: gpt-5.4-mini
    api_key_env: OPENAI_API_KEY
    timeout: 1800

runner:
  type: github_patch
  config:
    image: securebench-agent:latest
    apply_hidden_patches:
      - tests
    test_group_names:
      - fail_to_pass
      - pass_to_pass
    test_command_template: "python -m pytest {tests}"
    timeout: 1800
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

`producer.type`
: Required. Supported values:

- `"openai_compatible"`: calls a Chat Completions compatible endpoint.
- `"static"`: returns fixed text, useful for tests and smoke checks.
- `"workspace_agent_patch"`: checks out a GitHub repository, runs the built-in
  workspace agent in a Docker sandbox, and returns the resulting git diff as a
  patch artifact.

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

For `"workspace_agent_patch"`:

- `image`: optional Docker image. Defaults to `"python:3.11-slim"`, but
  practical runs should use an image containing SecureBench and repo tools,
  such as `securebench-agent:latest`.
- `model` or `replay_file`: one is required. `model` uses the OpenAI-compatible
  tool-calling agent; `replay_file` uses deterministic recorded actions.
- `base_url`: optional OpenAI-compatible endpoint base URL.
- `api_key_env`: optional environment variable containing the API key.
- `repo_dir`: optional checkout directory inside `/workspace`.
- `task_file`: optional public task file name written into the repo.
- `setup_commands`: optional list of setup commands run before the agent.
- `allow_commands` / `deny_commands`: optional command policy lists for the
  agent's `run_command` tool.
- `max_steps`, `max_tool_output`, `command_timeout`, `request_timeout`,
  `temperature`, `timeout`: optional agent and sandbox controls.

`runner.type`
: Required runner type. Built-in values are `"multiple_choice"`,
`"code_generation"`, and `"github_patch"`.

For `runner.type: github_patch`, optional `runner.config` fields include:

- `image`: Docker image for evaluation.
- `repo_dir`: checkout directory inside `/workspace`.
- `setup_commands`: setup commands run before tests.
- `test_commands`: explicit test commands.
- `apply_hidden_patches`: names of hidden patch groups to apply during
  evaluation.
- `test_group_names`: names of task test groups to select.
- `test_command_template`: command template that receives selected tests through
  `{tests}`.
- `timeout`: per-command timeout in seconds.

## Security Invariant

The producer receives only `task.agent_payload()`, never the full normalized
task object. For MMLU, that means the hidden `answer` field remains evaluator
data and is not sent to the model. For HumanEval, hidden tests and canonical
solutions remain evaluator data and are not sent to the model. For GitHub patch
tasks, hidden patches and hidden test groups stay runner-only and are not
written into the workspace-agent task file.

## Running

Static smoke run:

```bash
.venv/bin/python -m securebench.cli run --config configs/mmlu-static-smoke.yaml
```

OpenAI-compatible smoke run:

```bash
.venv/bin/python -m securebench.cli run --config configs/mmlu-openai-smoke.yaml
```

HumanEval static smoke run:

```bash
.venv/bin/python -m securebench.cli run --config configs/humaneval-static-smoke.yaml
```

HumanEval OpenAI-compatible smoke run:

```bash
.venv/bin/python -m securebench.cli run --config configs/humaneval-openai-smoke.yaml
```

SWE-bench Verified workspace-agent smoke run:

```bash
docker build -f docker/agent.Dockerfile -t securebench-agent:latest .
.venv/bin/python -m securebench.cli run --config configs/swebench-verified-agent-smoke.yaml --limit 1
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
