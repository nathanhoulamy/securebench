# Terminal Task Smoke

Minimal terminal benchmark pack for verifying workspace-state tasks.

The candidate-producing harness receives only `input.instructions` and any public
assets. After the harness exits, SecureBench preserves the workspace and runs the
trusted `eval.checker.command` in the benchmark image.

Run:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-task-smoke/tester-command.yaml
```
