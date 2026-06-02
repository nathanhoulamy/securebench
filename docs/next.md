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
- Continue hardening `repo_patch` toward separate candidate runtimes for tasks
  that need strong hidden-test secrecy. Canonical patches, stdin application,
  post-apply path checks, and containment metadata are now enforced, but the
  check command still runs in the candidate-mutated repository.
- Prefer task-specific implementation-file allowlists for future `repo_patch`
  benchmark standards. The current default deny policy is useful as a safety
  net, but benchmark-authored allowlists such as `src/**` make the intended
  candidate edit surface clearer and easier to audit.
- Consider adapter-based Python-call, CLI-case, and HTTP-case protocols that
  keep hidden evaluators in a separate container and send only bounded inputs
  to a no-egress candidate runtime.

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
- If harnesses eventually need internal services, add an explicit
  tester-controlled private-egress policy. Keep public-only DNS resolution and
  address pinning as the default.
- Persist compact sanitized harness traces when useful, without storing secrets,
  hidden tests, hidden patches, or full sensitive artifacts.
- Add provider-key isolation for CLI harnesses. `OPENAI_API_KEY` and
  `ANTHROPIC_API_KEY` are currently passed into the harness container, so
  untrusted agent execution can potentially inspect environment or process
  state, print keys, reuse quota, or persist secrets into artifacts. Randomized
  environment variable names are not a meaningful security boundary because the
  key must eventually be mapped back to the provider variable or a readable
  provider config path. Read-only provider config protects integrity rather than
  secrecy unless paired with real user/process separation, and it may break CLIs
  that expect writable home/config state. Prefer a SecureBench-owned provider
  broker sidecar: the harness receives no raw provider key, the broker owns the
  credential, the harness points the provider CLI at the broker endpoint if the
  CLI supports custom API base URLs, and the broker injects provider auth while
  enforcing provider-domain, path, rate, and body-size policy without logging
  secrets. First verify whether current Codex and Claude Code CLIs support
  custom provider base URLs; if not, avoid fake hiding and defer to a larger
  adapter or broker-compatible design.
- Consider subscription-auth support as an optional CLI harness auth mode, not
  as the provider-key isolation fix. Codex and Claude Code can authenticate via
  browser or matching-code flows for eligible subscription plans, which may help
  users who have subscriptions rather than manually managed API keys. A future
  implementation should add an explicit auth mode, avoid passing API key env
  vars in subscription mode, and run from pre-authenticated CLI state created
  outside benchmark execution. The likely compatibility path is to mount source
  auth state read-only, copy it into a per-run temporary writable home, run the
  CLI non-interactively, and delete the copy afterward. This protects the
  user's original auth state from mutation, but it does not hide the copied
  session credential from the agent container. Before implementing, verify
  stable credential locations, macOS Keychain versus file-backed behavior,
  token refresh expectations, and whether Codex/Claude can run non-interactively
  in Docker from the copied state. For Claude Code, ensure `ANTHROPIC_API_KEY`
  is unset in subscription mode because it takes precedence over subscription
  login.
