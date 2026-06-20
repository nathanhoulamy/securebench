# Terminal-Bench 2.0

This benchmark pack ports all 89 tasks from `harbor-framework/terminal-bench-2`
to SecureBench `terminal_task` rows.

Pack notes:

- Uses the upstream Terminal-Bench 2.0 task order from commit
  `2fd12b88aafdd04a52c298e3940bcb189f9766d6`.
- Copies each upstream `environment/` directory to `docker/<task>/`.
- Copies upstream `tests/` into SecureBench hidden evaluator assets.
- Omits upstream `solution/` directories from the benchmark pack.
- Enables `environment.materialize_workdir_from_image` for every row, because
  Terminal-Bench task images place starter files in `/app`.

Regenerate the pack from a local checkout:

```bash
python3 tools/import_terminal_bench_2.py --source /path/to/terminal-bench-2
```

Or let the importer clone the pinned upstream revision:

```bash
python3 tools/import_terminal_bench_2.py
```

Build the local task images before running:

```bash
for d in benchmarks/terminal-bench/docker/*; do
  task=$(basename "$d")
  docker build -t "securebench-terminal-bench-${task}:latest" "$d"
done
```

Run with Codex:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench/tester-codex.yaml \
  --limit 10
```

Verifier note: upstream Terminal-Bench 2.0 `test.sh` scripts are adapted to use
SecureBench's hidden evaluator mount path and verifier log directory. Many
upstream scripts still use `uvx` to provision checker dependencies, so
`tester-codex.yaml` sets `verification.allow_network: true` for verifier-only
dependency downloads. Agent sandboxes remain governed by the harness network
policy.
