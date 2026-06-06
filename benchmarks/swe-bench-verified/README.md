# SWE-bench Verified

This benchmark pack is intended to **test an actual agent run** via the `codex` harness.

Pack notes:

- Uses 5 deterministic random rows from the normalized SWE-bench Verified tasks in this repository.
- **Removes the public `assets` mounts** that included gold solution patches (to avoid leaking the answer to the agent).
- Provides a `tester-codex.yaml` run config targeting model `gpt-5.4-mini`.
- Records each source row index in task metadata for reproducibility.

Run it with SecureBench’s CLI the same way you run other `tester-*.yaml` configs in `benchmarks/`.
