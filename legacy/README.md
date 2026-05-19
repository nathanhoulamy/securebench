# Legacy SecureBench Code

This directory archives older experiments that no longer belong to the active
benchmark-pack pipeline.

The active pipeline is:

1. benchmark pack manifest plus JSONL rows;
2. tester YAML harness config;
3. row compilation into normalized tasks;
4. harness candidate production;
5. shared candidate extraction;
6. family verifier execution;
7. JSONL result output.

Archived code here is retained only for reference. Do not import it from active
`securebench` modules. If a concept is still useful, port it into the active
benchmark-pack, harness, candidate-extraction, or verifier layers.

Contents:

- `securebench/adapters/`: raw dataset adapters for MMLU, HumanEval, and
  SWE-bench Verified.
- `securebench/datasets.py`: Hugging Face dataset reference helpers.
- `securebench/candidates/`: direct static/text/OpenAI-compatible and
  workspace-agent producers.
- `securebench/repositories.py`: repository preparation helper used by the old
  workspace patch producer.
- `securebench_agent/`: built-in workspace agent prototype.
- `docker/agent.Dockerfile`: image scaffold for the built-in agent prototype.
- `test_snapshots/`: tests documenting moved behavior.
- `docs/`: older schema notes from the adapter/dataset era.
