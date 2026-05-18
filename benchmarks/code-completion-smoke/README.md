# Code Completion Smoke Pack

This benchmark pack is for testing the benchmark-pack plus Codex mounted harness
path through candidate extraction. It is intentionally small and uses
`code_completion` rows where Codex should write a `candidate.py` file.

The current goal is to exercise:

- tester YAML loading
- benchmark manifest and row loading
- public task materialization
- Codex mounted harness execution
- shared candidate extraction from `candidate.py`

Verifier work is intentionally out of scope for this smoke pack step.
