# SecureBench Security Notes

SecureBench treats benchmark execution as adversarial. The active benchmark
families are `repo_patch` and `terminal_task`; both involve candidate-controlled
workspace state and must be verified from trusted evaluator inputs.

## Data Separation

- Public resources are visible to the agent and may be materialized into the
  agent workspace.
- Evaluation inputs are available only to the verification sandbox.
- Hidden resources are retained for trusted reporting or analysis and are
  redacted from result records.
- Named provider harness credentials are host-side only. Codex and Claude Code
  receive dummy provider credentials inside the untrusted agent container and
  route API requests through a SecureBench provider relay sidecar, which injects
  the real API key or Claude subscription bearer token outside the sandbox.

## Provider Relay

The provider relay is enabled for the `codex` and `claude_code` harnesses. It
terminates plain HTTP from the internal Docker network, forwards to the provider
over HTTPS, strips dummy auth, injects the real host credential, and writes
redacted decision logs outside the agent workspace.

Provider-hosted external tools are blocked by default. Tester YAML may opt in
with `harness.config.allow_external_tools: true`; otherwise requests that enable
server-side tools such as web search, remote MCP, hosted code execution, or file
search are rejected before they reach the provider. Local/client tool definitions
used by the CLIs remain allowed.

The relay is not a general guarantee for custom commands. The `command` harness
still passes tester-selected environment variables directly into its container,
so testers should not expose secrets to untrusted command harnesses unless that
is part of the experiment.

`allowed_domains` controls generic agent-container egress, not provider-hosted
web search. Provider-hosted web tools remain blocked by default and, if enabled,
run inside the provider rather than through SecureBench's generic egress proxy.
Claude Code `allowed_domains` relies on the CLI honoring its documented
`NO_PROXY` behavior so provider relay traffic to `securebench-provider-relay`
bypasses the generic egress proxy. Re-run an integration check with a real
Anthropic key when changing Claude Code networking or proxy handling.

## Repo Patch

Repo-patch candidates are collected as git diffs. The verifier checks declared
base commits, applies optional setup and test patches, enforces candidate path
policy, then runs benchmark-authored command checks in the benchmark image with
network disabled by default.

The default policy blocks common test infrastructure, dependency, CI, and
SecureBench-owned paths. Benchmark authors should still declare
`eval.candidate_policy.allow_paths` for the intended implementation edit surface.

## Terminal Task

Terminal-task candidates are final workspace directories. Trusted checker files
come from benchmark eval assets and are mounted read-only under
`/opt/securebench/evaluator` before running against the produced workspace.

Supported checker sources are `pytest` and `script`. Checker code must treat all
workspace files as untrusted input and should avoid importing candidate-controlled
modules unless that is the explicit behavior under test.

## Auditing

`securebench audit-self` runs static visibility checks, repo-patch path-policy
checks, and dynamic smoke probes for repo-patch and terminal-task tampering
patterns. Passing the built-in audit suite means the current implementation
resisted those probes; it is not a proof that every benchmark-authored checker is
secure or meaningful.

## Known Gaps

- Result records are not signed.
- `--resume` trusts existing `candidates.jsonl` records for completed task IDs.
- Result records do not yet include full benchmark pack digests or verifier code
  version identifiers.
- Producer and verifier stdout/stderr can contain sensitive information if a
  harness or checker prints it.

## Hardening Priorities

- Add manifest, task-row, verifier, and benchmark-pack digests to result records.
- Add optional result signing or append-only audit logs.
- Treat resumed records as untrusted unless their digest or signature matches the
  current benchmark pack and verifier.
- Expand malicious audit packs for repository and terminal workflows.
