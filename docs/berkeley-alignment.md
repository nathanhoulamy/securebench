# Berkeley Benchmark Security Alignment

This document maps SecureBench's current repo-patch and terminal-task security
posture to common trustworthy-benchmark failure classes.

| Issue class | Current controls |
| --- | --- |
| No isolation between agent and evaluator | Public/evaluation/hidden resource lanes; agent payloads use public views only; trusted terminal checkers mount read-only under `/opt/securebench/evaluator`; verifiers disable network by default. |
| Answers or checker data shipped with tasks | Evaluation inputs and hidden resources are excluded from agent payloads and redacted from result summaries. |
| Evaluation logic that does not evaluate | Static and smoke audits catch obvious output-only bypasses, but benchmark-authored tests still determine semantic quality. |
| Test infrastructure tampering | Repo-patch path policy blocks common test, dependency, CI, and SecureBench-owned paths; terminal-task checkers run from trusted read-only mounts. |
| Trusting untrusted workspace state | Verifiers treat produced repositories and workspaces as untrusted and run trusted checks from evaluator-controlled locations. |

## Audit Coverage

Run:

```bash
.venv/bin/python -m securebench.cli audit-self --output-dir /tmp/securebench-audit
```

The audit suite includes:

- Static visibility checks for agent payloads, materialization, and result redaction.
- Static repo-patch policy checks for tests, CI, dependency files, shell scripts,
  path traversal, and SecureBench-owned paths.
- Dynamic repo-patch probes for test infrastructure tampering.
- Dynamic terminal-task probes for network egress, evaluator tampering, fake
  wrappers, and output-only bypasses.

Passing the suite means SecureBench resisted those known probes. It does not
mean every future benchmark or custom checker is safe.

## Remaining Work

- Add benchmark pack and task digests to result metadata.
- Add optional author-facing audit explanations for weak terminal/repo-patch tests.
- Continue expanding malicious audit packs as new agentic workflows are added.
