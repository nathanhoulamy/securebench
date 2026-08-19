# Terminal-Bench conversion source and v2 reference

This directory has two deliberately distinct parts:

- `manifest-v2.yaml` and `tasks-v2.jsonl` contain the executable
  `constraints-scheduling` strict split-verification reference row.
- `manifest.yaml`, `tasks.jsonl`, `docker/`, and `hidden/` preserve the older
  Terminal-Bench 2.0 conversion as source material for further row redesign.
  The old manifest and rows use the pre-v2 format and the strict loader rejects
  them.

Run the v2 reference with:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench/tester-codex.yaml
```

The source material comes from `harbor-framework/terminal-bench-2` revision
`2fd12b88aafdd04a52c298e3940bcb189f9766d6`. Its obsolete-format importer was
removed; future conversions should emit reviewed v2 rows directly.
