# SecureBench source layout

- `schemas/benchmark.py`: closed Pydantic models for manifests and rows.
- `benchmark_pack.py`, `benchmark_compiler.py`, `tasks.py`: strict loading,
  source-root resolution, and the single compiled task type.
- `resources.py`, `workspaces/`: visibility views and materialization policy.
- `harnesses/`: Agent-only Codex, Claude Code, and command adapters.
- `candidates/`: ephemeral production output, bounded stopped-state capture,
  content-addressed storage, and replay.
- `verification/`: passive parsers, host Oracle ABI, artifact engine, and
  sanitized result models.
- `execution_profiles.py`: registered framework isolation/orchestration
  profiles and executable-capability preflight.
- `tester_config.py`, `tester_run.py`, `cli.py`: end-to-end orchestration.
- `audit/`: deterministic checks of visibility, materialization, provenance,
  and framework-owned candidate protections.

Families remain useful as prompt/input contracts in the schema. They no longer
select a verifier or dictate candidate extraction.
