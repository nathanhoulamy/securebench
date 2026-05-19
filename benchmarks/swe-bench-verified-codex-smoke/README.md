# SWE-bench Verified (Codex Smoke)

This benchmark pack is derived from `benchmarks/swe-bench-verified-smoke/` but is intended to **test an actual agent run** via the `codex` harness.

Differences vs the original smoke pack:

- Uses 10 SWE-bench Verified tasks: the original 3 smoke rows plus 7 additional randomly sampled rows.
- **Removes the public `assets` mounts** that included gold solution patches (to avoid leaking the answer to the agent).
- Provides a `tester-codex.yaml` run config targeting model `gpt-5.5`.
- Records each source row index in task metadata for reproducibility.

Run it with SecureBench’s CLI the same way you run other `tester-*.yaml` configs in `benchmarks/`.
