# Terminal-Bench First 5

First five `original-tasks` from `harbor-framework/terminal-bench`, converted to SecureBench `terminal_task` rows.

Converted task IDs:

- `path-tracing`
- `model-extraction-relu-logits`
- `video-processing`
- `dna-assembly`
- `gomoku-planner`

Build the local task images before running:

```bash
for d in benchmarks/terminal-bench-first5/docker/*; do
  task=$(basename "$d")
  docker build -t "securebench-terminal-bench-first5-${task}:latest" "$d"
done
```

Run with Codex:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench-first5/tester-codex.yaml \
  --limit 5
```
