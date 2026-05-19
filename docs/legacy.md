# Legacy Code

The active pipeline is benchmark-pack based:

1. load a benchmark pack manifest and JSONL rows;
2. parse tester YAML;
3. compile rows into normalized tasks;
4. run a harness such as `codex` or `command`;
5. extract a family-shaped candidate artifact;
6. verify supported families through `securebench/verifiers/`;
7. write JSONL result records.

The old run-config, raw-dataset adapter, direct-producer, and built-in-agent
experiments live under `legacy/` for reference only.

Archived locations:

- `legacy/securebench/adapters/`: MMLU, HumanEval, and SWE-bench row adapters.
- `legacy/securebench/datasets.py`: Hugging Face dataset loading helpers.
- `legacy/securebench/candidates/`: direct static/text/OpenAI-compatible and
  workspace-agent candidate producers.
- `legacy/securebench_agent/`: the old built-in workspace agent runtime.
- `legacy/docker/agent.Dockerfile`: image scaffold for the old built-in agent.
- `legacy/test_snapshots/`: tests that documented old behavior.
- `legacy/docs/`: older schema and implementation roadmap notes.

Future work should target the active benchmark-pack, harness, extraction, and
verifier modules directly. If legacy code contains a useful idea, port that idea
into the active pipeline instead of importing from `legacy/`.
