# SecureBench documentation

This documentation covers the split-verification architecture and the reviewed
TerminalBench and DeepSWE conversion portfolio. Legacy family-specific verifier
designs are intentionally not retained.

## Split verification

- [`split-verification/schema.md`](split-verification/schema.md) — author-facing
  v2 row design and field reference.
- [`split-verification/security-model.md`](split-verification/security-model.md)
  — trust boundaries, candidate capture, evaluation isolation, and known limits.
- [`split-verification/examples/executable.yaml`](split-verification/examples/executable.yaml)
  — row shape supported end to end today.
- [`split-verification/examples/target-architecture.yaml`](split-verification/examples/target-architecture.yaml)
  — schema-valid examples that require planned runtime capabilities.

The executable schema authority is
[`securebench/schemas/benchmark.py`](../securebench/schemas/benchmark.py). The
generated JSON Schemas are in [`schemas/`](../schemas/).

## Benchmark conversions

- [`benchmark-conversions/README.md`](benchmark-conversions/README.md) — scope,
  decisions, patterns, and conversion rules.
- [`benchmark-conversions/inventory.csv`](benchmark-conversions/inventory.csv)
  — authoritative machine-readable status for all 202 reviewed rows.
- [`benchmark-conversions/action-queue.md`](benchmark-conversions/action-queue.md)
  — all excluded rows and approved major-redesign work.
- [`benchmark-conversions/DeepSWE/`](benchmark-conversions/DeepSWE/) — 113
  DeepSWE dossiers.
- [`benchmark-conversions/TerminalBench/`](benchmark-conversions/TerminalBench/)
  — 89 TerminalBench dossiers.

The dossiers are implementation plans and fidelity records. They are not
executable benchmark rows until their required runtime capabilities exist and
their conversions pass admission testing.
