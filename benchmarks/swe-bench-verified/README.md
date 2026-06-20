# SWE-bench Verified

This benchmark pack is intended to **test an actual agent run** via the `codex` harness.

Pack notes:

- Uses all 500 rows from the official `SWE-bench/SWE-bench_Verified` test split.
- **Removes the public `assets` mounts** that included gold solution patches (to avoid leaking the answer to the agent).
- Provides a `tester-codex.yaml` run config targeting model `gpt-5.4-mini`.
- Records each source row index in task metadata for reproducibility.

Regenerate `tasks.jsonl` from Hugging Face with:

```bash
python3 tools/import_swe_bench_verified.py
```

Run it with SecureBench’s CLI the same way you run other `tester-*.yaml` configs in `benchmarks/`.
