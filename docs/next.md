# Next Work

This file tracks current engineering follow-ups only. The canonical benchmark
and tester YAML references are the HTML standards in this directory.

## Harnesses

- Implement `claude_code` as a named harness that runs inside the benchmark
  `environment.image` with a mounted tooling overlay, matching the Codex model.
- Keep `command` as the containerized custom-command harness for tests and
  advanced integrations.
- Do not reintroduce harness `mode` or host execution for candidate production.

## Verifiers

- Add a `short_answer` verifier using `eval.accepted_answers` and optional
  numeric `eval.tolerance`.
- Decide whether `free_response` should stay pending, use a rubric-only result,
  or gain a concrete scorer interface.
- Continue hardening `repo_patch` verification around hidden/evaluation file
  placement, read-only mounts, and audit metadata.

## Schema Tightening

- Add shared asset-object validation for `path`, `mount`, `read_only`, `type`,
  and placement `mode`.
- Decide which active-family `eval.*` fields may be file references instead of
  ordinary JSON objects.
- Consider declarative family schema descriptors if the hand-written validators
  grow beyond the current active families.
- Add an explicit direct-call guard for `parse_benchmark_row(...)` if external
  code starts using it outside the JSONL loader.

## Security And Audit

- Keep Docker as the harness execution path for untrusted candidate production.
- Record audit metadata when candidate code must execute while evaluation files
  are present.
- Treat command allow/deny policy as guidance and audit logging, not isolation.
- Persist compact sanitized harness traces when useful, without storing secrets,
  hidden tests, hidden patches, or full sensitive artifacts.
