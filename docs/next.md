# Next Work

This file tracks current engineering follow-ups only. The canonical benchmark
and tester YAML references are the HTML standards in this directory.

## Harnesses

- Add smoke benchmark tester YAML examples for `claude_code`.
- Keep `command` as the containerized custom-command harness for tests and
  advanced integrations.
- Do not reintroduce harness `mode` or host execution for candidate production.

## Verifiers

- Replace the current `free_response` mini-benchmark scorer with a stronger
  rubric representation before treating TruthfulQA-style pass rates as model
  quality. The temporary deterministic scorer uses accepted/rejected sentence
  containment plus token overlap, which can falsely reject correct contrastive
  answers when accepted and rejected explanations share many words. Prefer
  explicit required/forbidden concepts, or a dedicated judge interface, over
  full-sentence overlap.
- Continue hardening `repo_patch` verification around protected hidden-test
  execution, read-only trusted harness files, post-apply integrity checks, and
  audit metadata. Candidate patches now have a pre-apply path policy, but the
  check command still runs in the candidate-mutated repository.
- Prefer task-specific implementation-file allowlists for future `repo_patch`
  benchmark standards. The current default deny policy is useful as a safety
  net, but benchmark-authored allowlists such as `src/**` make the intended
  candidate edit surface clearer and easier to audit.
- Consider optional post-apply integrity checks for `repo_patch` trust-base
  paths such as tests, test runners, dependency/build configuration, and
  framework-owned paths. This needs explicit standard support because some
  benchmarks may legitimately require edits to otherwise sensitive files.

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
