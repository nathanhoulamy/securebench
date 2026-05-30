# Berkeley Benchmark Security Alignment

This document maps SecureBench's current security posture to the benchmark
failure patterns described by Berkeley RDI's "Trustworthy Benchmarks"
write-up. It is a status document, not a proof of security.

## Summary

SecureBench now has first-party controls and an adversarial audit suite for the
main Berkeley-style benchmark failure classes:

- Hidden and evaluation-only data are separated from public agent payloads.
- Candidate artifacts are treated as untrusted input to verifiers.
- Terminal-task checker code is mounted from trusted read-only evaluator paths,
  not executed from candidate-controlled workspaces.
- Code-completion candidates run behind a trusted parent/worker protocol rather
  than sharing the hidden-test interpreter directly.
- Repo-patch candidates are path-policy checked before application.
- `securebench audit-self` runs static checks and malicious smoke probes.

The current audit suite passes, but SecureBench should still avoid claiming that
all benchmark tasks are unexploitable. Benchmark authors can still write weak
tests or overly broad rubrics.

## Berkeley Pattern Coverage

| Berkeley issue class | SecureBench status | Current controls |
| --- | --- | --- |
| No isolation between agent and evaluator | Strong for trusted data and checker code | Public/evaluation/hidden resource lanes; agent payloads use public views only; terminal checker files mount read-only under `/opt/securebench/evaluator`; verifier sandboxes run with network disabled by default. |
| Answers shipped with tests | Strong for implemented families | Answers, rubrics, gold patches, canonical solutions, and checker data are hidden or evaluation-only; result summaries redact non-public values. |
| `eval()` on untrusted input | Covered for current framework code | Verifiers do not evaluate candidate strings with Python `eval`; code-completion execution is isolated behind a worker protocol and tested with process-control probes. |
| Unsanitized LLM judges | Not currently applicable | Current implemented verifiers are deterministic. Any future LLM judge family needs a dedicated prompt-injection-resistant judge interface and audit probes. |
| Weak string matching | Partially covered | Multiple-choice, short-answer, and free-response have deterministic scorers and answer-spray/overlap smoke probes. Short/free-response scoring remains benchmark-policy-sensitive and needs stricter modes. |
| Evaluation logic that does not evaluate | Framework guardrails only | SecureBench can run tests securely and probe obvious output-only bypasses, but it cannot prove that benchmark-authored tests measure the intended skill. This is a benchmark quality risk. |
| Trusting output of untrusted code | Stronger, still task-dependent | Code-completion, repo-patch, and terminal-task probes cover hidden-runner reads, stack introspection, sentinel forgery, test/config tampering, fake wrappers, and output-only bypasses. Trusted checkers must still treat workspace files as untrusted data. |

## Current Audit Coverage

Run:

```bash
.venv/bin/python -m securebench.cli audit-self --output-dir /tmp/securebench-audit
```

The audit suite includes:

- Static visibility checks for agent payloads, materialization, and result
  redaction.
- Static repo-patch policy checks for tests, CI, dependency files, shell
  scripts, path traversal, and SecureBench-owned paths.
- Malicious benchmark packs under `benchmarks/audit/`.
- Dynamic probes for answer spraying, rejected/accepted overlap, code-completion
  process and introspection attacks, repo-patch test infrastructure tampering,
  terminal-task fake wrappers, verifier input overwrite attempts, and output-only
  bypasses.

Passing the suite means SecureBench resisted those known probes. It does not
mean every future benchmark or custom checker is safe.

## Family Notes

### Multiple Choice

SecureBench hides the expected answer from the agent and redacts it from result
metadata. The current risk is dataset design: answer distributions or public
prompts can still leak patterns if benchmark authors include them.

### Short Answer

Accepted answers and tolerances are hidden, but the scorer permits normalized
exact, span, and numeric-tolerance matches. This is intentionally simple and can
be too permissive for high-assurance benchmarks. We should add stricter final
answer modes and better authoring guidance.

### Free Response

Current scoring is deterministic and avoids LLM judge prompt-injection risk, but
the rubric model is weak for broad quality judgments. Rubrics should move toward
explicit required and forbidden concepts instead of loose sentence overlap.

### Code Completion

Candidate code is no longer concatenated with hidden tests or executed in the
same hidden-test interpreter. Hidden tests run in a trusted parent process that
proxies candidate calls into an isolated worker subprocess. Remaining risk is
Python sandboxing depth: candidate code still executes in the verifier container.

### Repo Patch

The default path policy blocks common test-infrastructure tampering paths before
candidate patches are applied. This is good enough for current smoke coverage.
The remaining risk is semantic: an allowed implementation file could still
monkeypatch a test framework if hidden tests import it with too much authority.

### Terminal Task

Terminal checkers now use structured trusted checker modes:

```json
{
  "checker": {
    "source": "pytest",
    "path": "task-name/tests"
  }
}
```

or:

```json
{
  "checker": {
    "source": "script",
    "path": "task-name/run-tests.sh"
  }
}
```

SecureBench mounts these checker files read-only from the benchmark's eval asset
root under `/opt/securebench/evaluator` and runs them against the candidate
workspace as untrusted state. This removes the main class of attacks where a
candidate replaces or shadows the checker inside the workspace.

## Remaining Work

- Add stricter short-answer and free-response scoring modes.
- Add benchmark pack and task digests to result metadata.
- Add optional author-facing audit explanations for weak terminal/repo-patch
  tests.
- Add dedicated LLM judge controls before introducing any judge-based family.
- Continue expanding malicious audit packs as new families are implemented.
