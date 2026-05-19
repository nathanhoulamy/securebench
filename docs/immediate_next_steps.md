# Immediate Next Steps

This document collects the deferred work from the implemented refactoring
steps and orders the next engineering passes. It is meant as the restart point
after the current pause.

## 1. Step 7: Family Verifier Integration

Implement the standardized scoring loop for the active families:

1. load tester YAML;
2. load and compile benchmark-pack rows;
3. build the command harness producer;
4. create/materialize the public harness workspace;
5. collect a family-shaped candidate artifact;
6. create a fresh test sandbox for scoring;
7. materialize public resources plus `evaluation_inputs` into the test
   sandbox;
8. run the family verifier while keeping hidden resources evaluator-side only.

Start with `multiple_choice`, `short_answer`, `code_completion`, and
`repo_patch`. Treat `free_response` as structurally valid but not fully
automated unless a concrete scorer is chosen.

Key decisions to preserve:

- verifier dispatch uses standard family names.
- `repo_patch` remains the public repository-editing family name.
- hidden resources may be read by trusted evaluator code, but are not mounted
  into harness or ordinary test-sandbox workspaces.
- tests that execute candidate code with hidden/evaluation files present should
  use read-only mounts or explicit audit metadata where confidentiality cannot
  be guaranteed.

## 2. Test Sandbox and Candidate Injection

Make the working/test sandbox split concrete:

- harness working sandbox: public task payload and public assets only.
- test sandbox: fresh per task or attempt, with public resources,
  `evaluation_inputs`, and the candidate artifact.
- evaluator side: hidden answers, rubrics, reference solutions, gold patches,
  and expected states.

Add helper APIs for building the test-sandbox materialization plan and for
placing candidate artifacts at verifier-specific paths. Avoid exposing a generic
global artifact section in the benchmark row; verifier expectations remain
family-specific.

## 3. Active Family Verifiers

Implement verifiers for the active families:

- `multiple_choice`: compare normalized text candidate to hidden
  `eval.answer`.
- `short_answer`: compare normalized candidate to hidden
  `accepted_answers`, with optional numeric `tolerance`.
- `code_completion`: run candidate code against `eval.tests` in a fresh
  sandbox. Avoid assuming the current HumanEval-only concatenation mode is the
  whole standard.
- `repo_patch`: apply a patch candidate in a fresh workspace and run
  `eval.tests`. Use public assets/repo inputs and evaluation-input tests, not
  legacy SWE-bench field names.
- `free_response`: leave as pending or implement only once the scorer shape is
  decided.

The legacy runner path has been removed; new work should target these
standard-family verifiers directly.

## 4. Deferred Harness Work

After command harness integration is exercised end to end, continue the
remaining harness work:

- `submission`: read task-id-keyed candidate records, reject missing or
  duplicate task ids, preserve metadata, and validate candidate value shape
  against family contracts.
- `codex`: mounted container execution is the first named-agent preset;
  `code_completion` extraction reads `candidate.py`, and `repo_patch`
  extraction collects `git diff --binary`.
- `claude_code`: same as `codex`; avoid exposing raw commands for named common
  harnesses.
- optional future `acp`: keep outside the parser until a real adapter path is
  chosen.

Until additional named wrappers exist, use `harness.type: command` for custom
installed or containerized agentic systems.

## 5. Schema and Materialization Tightening

Finish deferred validation work that is not needed for the first end-to-end
loop but should land before public use:

- add shared asset-object validation for `path`, `mount`, and `read_only`.
- decide which active-family `eval.*` fields may be file references versus
  ordinary JSON objects.
- consider declarative schema descriptors if hand-written validators grow
  beyond the current active families.
- add an explicit direct-call guard for `parse_benchmark_row(...)` if external code
  starts using it outside the JSONL loader.
- decide whether `evaluation_inputs` should eventually be renamed to a clearer
  term such as `sandbox_input`.

## 6. CLI and Examples

The standardized candidate-production and verification path is wired into the
command line:

- `securebench run --config <tester.yaml>` loads tester YAML.
- the code-completion smoke pack exercises tester YAML, benchmark-pack loading,
  compilation, Codex mounted harness execution, candidate extraction, and
  code-completion verification.

## 7. Security and Audit Follow-Ups

Carry forward these hardening items while integrating verifiers:

- keep Docker as the secure/reproducible path; host mode remains convenience
  only.
- verify hidden/evaluation files that must be present during tests are
  read-only where possible.
- record audit metadata when a benchmark design necessarily lets candidate code
  execute while evaluation files are present.
- keep command allow/deny policy as guidance and audit logging, not isolation.
- persist compact sanitized harness/agent traces when useful, without storing
  secrets, hidden tests, hidden patches, or full sensitive artifacts.
