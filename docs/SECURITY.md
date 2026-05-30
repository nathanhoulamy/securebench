# Security

SecureBench exists to let benchmark makers evaluate agents in an environment where benchmark data, scoring logic, and result integrity are protected from the candidate-producing agent. The security goal is not just to run tasks in a container; it is to make benchmark tampering, answer leakage, and verifier gaming hard by default.

This document describes the current controls for each benchmark family, what is already implemented, and what still needs to be hardened.

## Core Security Model

SecureBench separates benchmark data by visibility:

- `public`: visible to the agent.
- `evaluation_inputs`: visible to test-sandbox style execution, but not to the agent.
- `hidden`: visible only to trusted evaluators/verifiers.

The compiler maps each family field into one of those visibility lanes. Harnesses should only receive the task's public payload. Verifiers run after candidate production and may access trusted evaluation or hidden data.

Common controls already in place:

- Agent payloads are derived from `task.public_payload()`, not from the full task object.
- `ResourceBundle` exposes component-specific views for `agent`, `test_sandbox`, `evaluator`, and `result`.
- Result summaries redact non-public resources.
- Materialized resource paths reject absolute paths, `..`, backslashes, reserved roots, and duplicate parent/child mounts.
- File-backed assets must resolve under benchmark package asset roots and may not be symlinks.
- Docker sandboxes default to no network, dropped capabilities, no-new-privileges, memory and PID limits, and a read-only root filesystem unless a caller explicitly changes those settings.
- Candidate records redact exact hidden verifier metadata values where the framework knows them.

Important limitation: SecureBench is still an active implementation. Some families have stronger isolation than others, and the Codex/repo-patch paths still need additional hardening before they should be treated as adversarial-agent safe.

## Multiple Choice

Data split:

- Public: question and choices.
- Hidden: expected answer.
- Candidate kind: text.

Current protections:

- The answer is compiled as hidden data and is not included in the agent payload.
- Verification compares candidate text against normalized hidden answer labels and answer text.
- Verifier metadata records the expected answer, but `tester_run` redacts the `expected_answer` field before writing result records.
- The agent cannot affect verifier code execution because the candidate is plain text, not executable code.

Known gaps:

- The candidate text is persisted in result records. This is expected, but benchmark operators should avoid including sensitive data in public prompts that could be copied into answers.
- Multiple-choice scoring is deterministic and simple. It can still be gamed statistically if choices or benchmark construction leak patterns; this is a dataset-design risk rather than a runtime isolation failure.
- There is no cryptographic integrity record tying a result to the exact benchmark pack contents yet.

Needed hardening:

- Add optional benchmark pack hashing in result metadata.
- Add audit metadata for manifest path, tasks path, and task row digest.
- Consider stricter answer extraction rules for benchmarks that require one unambiguous final answer.

## Short Answer

Data split:

- Public: question, optional context, optional answer format.
- Hidden: accepted answers and optional tolerance.
- Candidate kind: text.

Current protections:

- Accepted answers and tolerance are hidden from the agent payload.
- Verification is deterministic and does not execute candidate-controlled code.
- Result metadata records match index and strategy, not the full accepted answer set.
- Non-public resources are redacted from result summaries.

Known gaps:

- The verifier uses normalized exact, span, and numeric-tolerance matching. A loose accepted answer can make false positives easier.
- Hidden answers can still leak through operator-authored prompts or public context if benchmark makers duplicate answer information.
- No benchmark pack integrity digest is emitted with results yet.

Needed hardening:

- Add pack/task digests to result metadata.
- Provide authoring guidance for avoiding answer leakage in public context.
- Add optional stricter match modes for benchmark makers who want exact final-answer formats.

## Free Response

Data split:

- Public: prompt and optional context.
- Hidden: rubric and optional reference answer.
- Candidate kind: text.

Current protections:

- Rubric and reference answer are hidden from the agent payload.
- Verification does not execute candidate code.
- The current verifier uses deterministic rubric fields instead of exposing hidden rubric text to the agent.

Known gaps:

- The current deterministic scorer is intentionally weak for broad free-response quality judgments.
- Rubrics that rely on accepted/rejected sentence containment can be gamed by answers that include many overlapping concepts.
- Free-response scoring is not yet a strong judge model or formally specified rubric engine.

Needed hardening:

- Replace the temporary scorer with a stronger rubric representation or a dedicated trusted judge interface.
- Add explicit required and forbidden concepts instead of full-sentence overlap where possible.
- Add result metadata that explains which rubric criteria were evaluated without leaking hidden rubric contents.

## Code Completion

Data split:

- Public: prompt, language, optional starter code.
- Evaluation inputs: hidden tests.
- Hidden: reference or canonical solution.
- Candidate kind: code.

Current protections:

- The agent only receives public prompt/source context.
- Candidate code is written separately from the trusted test runner.
- Hidden tests are no longer concatenated after candidate code in the same top-level script.
- Hidden tests run in a trusted parent process that proxies candidate function calls into a separate Python worker subprocess.
- The candidate worker script does not embed hidden test source, and the worker runs from an isolated temporary working directory containing only copied worker and candidate files.
- When the verifier runs with root privileges, the candidate worker drops to the unprivileged `nobody` user while trusted runner files are marked owner-only.
- The verifier runs a trusted supervisor that fails if hidden tests do not complete.
- `SystemExit` during candidate import is treated as failure.
- Simple `os._exit(0)` during candidate import cannot mark tests as complete because the trusted parent requires an explicit completion sentinel.
- Import-time modifications to worker builtins are restored before hidden tests issue candidate calls.
- Python verifier execution uses Docker with network disabled by default.

Known gaps:

- Candidate code and hidden tests still run in the same container.
- Python is not a strong sandbox. Malicious candidate code may still mutate process state in ways not covered by the current restoration logic.
- Hidden test source still exists in the trusted runner file inside the verifier workspace while verification runs; the current file-permission control depends on a root-run verifier environment.
- The framework currently supports Python code-completion only.

Needed hardening:

- Move toward stronger container or process boundaries where hidden tests are never present in a candidate-readable filesystem.
- Continue narrowing the parent-driven candidate API beyond basic function and top-level value access.
- Add stricter controls for filesystem reads, imports, monkeypatching, process termination, and environment access during verification.
- Add regression tests for additional process-control and introspection attacks.

## Terminal Task Verifiers

Terminal task checkers run in a fresh verifier sandbox with network disabled and
trusted checker files mounted read-only under `/opt/securebench/evaluator`.
Some benchmark checkers execute or inspect agent-produced workspace artifacts as
part of the test, so verifier sandbox hardening still matters even though the
checker itself is trusted.

Current protections:

- The agent sandbox does not receive dangerous verifier command allowances.
- Checker code is resolved from the benchmark pack's eval asset root and mounted
  outside the candidate workspace.
- Terminal tasks use structured `pytest` or `script` checker modes instead of
  raw candidate-workspace commands.
- Benchmark authors may declare verifier-only `eval.needed_commands` when a
  checker needs a known dangerous command such as `chroot`.
- Tester policy is fail-closed by default with
  `verification.disallow_dangerous_commands: true`.
- Tester `verification.deny_commands` overrides benchmark declarations and any
  opt-in.
- Allowed dangerous commands are implemented as narrowly mapped Docker
  privileges, not as a general nested command interceptor.

Known gaps and guidance:

- A verifier allowance applies while verifier tests may run candidate-produced
  code. Benchmark authors should avoid dangerous commands where practical.
- Current command support is intentionally small; `chroot` maps to
  `SYS_CHROOT`.
- Denials fail the verifier before tests run and include the denied command and
  reason in result metadata.

## Repo Patch

Data split:

- Public: repository identifier, base commit, instructions, optional hints.
- Evaluation inputs: candidate patch policy, command tests, setup patch, test patch.
- Hidden: gold patch.
- Candidate kind: patch.

Current protections:

- The agent receives only public task instructions and public workspace data.
- Candidate production for repo-patch tasks collects a git diff rather than trusting arbitrary result text.
- Repo-patch verification runs in Docker with network disabled by default.
- Test patches are stored under an evaluation-input path before application.
- Empty candidate patches fail.
- Candidate patches are checked against `eval.candidate_policy` before they are written or applied.
- By default, candidate patches are denied when they touch test directories, hidden/evaluation paths, CI configuration, build/dependency configuration, lockfiles, test runners, shell scripts, or unsafe paths.
- Benchmark authors can explicitly override the default path policy with `eval.candidate_policy.allow_sensitive_paths` when a task intentionally requires editing an otherwise-denied path.
- Benchmark authors can mark public verifier-supporting files with `eval.candidate_policy.patch_preserved_paths`; candidate edits to those files are stripped at whole-file diff granularity before verification.
- Framework trust-boundary paths such as `securebench/`, absolute paths, and paths containing `..` are non-overridable and fail verification rather than being stripped.

Known gaps:

- The verifier still applies the candidate patch before applying hidden tests and running the trusted command, so the path policy is the main protection against test-infrastructure tampering.
- The default deny list is conservative but not a complete semantic model of every benchmark image's test trust base.
- Public tests can still be part of the verifier trust base when hidden/evaluation tests import, patch, or extend them; `patch_preserved_paths` is intended for those visible-but-immutable support files, not for hidden-test secrecy.
- The verifier does not yet verify that command targets and imported test helpers remain unchanged after candidate application beyond the configured path policy.
- The check command runs in the candidate-mutated repository, so candidate changes can tamper with the command's trust base.

Needed hardening:

- Expand path policy configuration as real repo-patch benchmarks need narrower implementation-file allowlists.
- Apply hidden tests from a protected location after candidate patching.
- Run trusted check orchestration from a read-only harness path outside the candidate-controlled repository.
- Add post-apply integrity checks for command targets, test runners, and trusted helper files.
- Add regression tests for malicious patches that alter test infrastructure rather than implementation code.

## Deferred And Planned Families

The compiler already has visibility mappings for additional families, but these are not fully implemented verifier surfaces yet:

- `terminal_task`
- `tool_call`
- `browser_task`
- `desktop_task`
- `artifact_task`
- `multimodal_qa`
- `preference_pair`

Current protections:

- Known eval fields for these families are mapped to `evaluation_inputs` or `hidden` when rows are compiled.
- Unknown or deferred families can remain pending when no verifier is registered.

Known gaps:

- These families do not yet have complete active verifier isolation stories.
- Tool, browser, desktop, and terminal tasks will need stronger controls than text-only families because they naturally involve stateful environments and side effects.
- Artifact and multimodal tasks need clear rules for reference artifact storage, media redaction, and result handling.
- Preference-pair tasks need hidden preference/rubric handling that avoids leaking evaluator criteria.

Needed hardening:

- Define a family-specific threat model before enabling each verifier.
- Specify which files, services, credentials, and environment state the agent may read or mutate.
- Add per-family result integrity metadata.
- Add tamper tests before each family is marked safe for adversarial benchmark runs.

## Harness Security

SecureBench currently has command and provider CLI harness styles.

Command harness:

- Runs tester-provided commands in Docker.
- Materializes only agent-visible resources for the agent workspace.
- Mounts file-backed public assets read-only by default.
- Should be considered trusted-tester configuration, not an untrusted-agent-selected command surface.

Provider CLI harnesses:

- Run Codex or Claude Code in the benchmark image with a tooling overlay.
- Materializes only public task data for the agent.
- Use separate temporary tool home directories.
- Currently forward provider API keys into the same container where agent tool
  commands can run.
- Runs on an isolated Docker network with egress routed through a
  framework-owned allowlisting HTTP(S) proxy. The default egress allowlist is
  the provider API domain required by the harness, plus any tester-configured
  `harness.config.allowed_domains`.
- Invoke provider CLIs with approval and sandbox bypass flags.

Needed provider CLI hardening:

- Do not expose long-lived API keys to the same environment where an evaluated agent can run shell commands.
- Prefer a brokered model-client design or short-lived scoped credentials.
- Redact known secret values from producer stdout, stderr, progress, and metadata.

## Result And Audit Integrity

Current protections:

- Result records include candidate artifacts, verifier status, scores, resource summaries, and selected metadata.
- Hidden resource values are redacted in summaries.
- Exact hidden metadata values are redacted when they match known hidden resource values.

Known gaps:

- Result records are not signed.
- `--resume` trusts existing `candidates.jsonl` records for completed task IDs.
- Result records do not yet include full benchmark pack digests or verifier code version identifiers.
- Producer stdout/stderr and verifier stdout/stderr can contain sensitive information if a harness or verifier prints it.

Needed hardening:

- Add task-row, manifest, verifier, and benchmark-pack digests to result records.
- Add optional result signing or append-only audit logs.
- Treat resumed records as untrusted unless their digest/signature matches the current benchmark pack and verifier.
- Add secret redaction for configured environment variables and known sensitive resource values across stdout/stderr/progress.

## Safe-By-Default Release Criteria

Before SecureBench should claim a family is safe for adversarial benchmark runs, that family should satisfy these criteria:

- The agent receives only public data.
- Hidden and evaluation inputs are not readable by candidate code or candidate-controlled files.
- The candidate cannot skip, replace, or weaken trusted verification logic.
- The verifier runs from a trusted path outside candidate control.
- Candidate writes are constrained to explicitly allowed outputs or implementation files.
- Network and credentials are denied by default unless the family explicitly requires them.
- Result records include enough integrity metadata to reproduce and audit the score.
- Regression tests cover realistic tampering attempts for that family.

Today, the text-only families are closest to this bar. `code_completion` has improved but still needs stronger process isolation. `repo_patch` and Codex harness runs need the most hardening before they should be treated as safe against actively malicious agents.
