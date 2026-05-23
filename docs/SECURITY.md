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
- The verifier runs a trusted supervisor that fails if hidden tests do not complete.
- `SystemExit` during candidate import is treated as failure.
- Simple `os._exit(0)` during candidate import is blocked.
- Import-time modifications to builtins and import path state are restored before hidden tests execute.
- Python verifier execution uses Docker with network disabled by default.

Known gaps:

- Candidate code and hidden tests still run in the same container and, after import, the same Python interpreter.
- Python is not a strong sandbox. Malicious candidate code may still mutate process state in ways not covered by the current restoration logic.
- Hidden test source still exists in the trusted runner file inside the verifier workspace while verification runs.
- The framework currently supports Python code-completion only.

Needed hardening:

- Move toward a parent-driven black-box protocol where hidden tests are never readable by candidate code.
- Run candidate behavior in a separate subprocess with a narrow API, not in the same interpreter as hidden tests.
- Add stricter controls for filesystem reads, imports, monkeypatching, process termination, and environment access during verification.
- Add regression tests for additional process-control and introspection attacks.

## Repo Patch

Data split:

- Public: repository identifier, base commit, instructions, optional hints.
- Evaluation inputs: command tests, setup patch, test patch.
- Hidden: gold patch.
- Candidate kind: patch.

Current protections:

- The agent receives only public task instructions and public workspace data.
- Candidate production for repo-patch tasks collects a git diff rather than trusting arbitrary result text.
- Repo-patch verification runs in Docker with network disabled by default.
- Test patches are stored under an evaluation-input path before application.
- Empty candidate patches fail.
- Candidate patches are checked against a verifier-side path policy before they are written or applied.
- By default, candidate patches are denied when they touch test directories, hidden/evaluation paths, CI configuration, build/dependency configuration, lockfiles, test runners, shell scripts, or unsafe paths.
- Benchmark authors can explicitly override the default path policy with `tests.candidate_policy.allow_sensitive_paths` when a task intentionally requires editing an otherwise-denied path.

Known gaps:

- The verifier still applies the candidate patch before applying hidden tests and running the trusted command, so the path policy is the main protection against test-infrastructure tampering.
- The default deny list is conservative but not a complete semantic model of every benchmark image's test trust base.
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

SecureBench currently has two active harness styles.

Command harness:

- Runs tester-provided commands in Docker.
- Materializes only agent-visible resources for the agent workspace.
- Mounts file-backed public assets read-only by default.
- Should be considered trusted-tester configuration, not an untrusted-agent-selected command surface.

Codex harness:

- Runs Codex in the benchmark image with a tooling overlay.
- Materializes only public task data for the agent.
- Uses a separate temporary Codex home directory.
- Currently forwards `CODEX_API_KEY` into the same container where agent tool commands can run.
- Currently enables Docker bridge networking.
- Invokes Codex with approval and sandbox bypass flags.

Needed Codex hardening:

- Do not expose long-lived API keys to the same environment where an evaluated agent can run shell commands.
- Prefer a brokered model-client design or short-lived scoped credentials.
- Add a safe-by-default no-egress mode.
- Make unsafe credential/network behavior require explicit opt-in.
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
