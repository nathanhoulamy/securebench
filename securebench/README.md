# SecureBench Source Layout

The active package is organized around agentic benchmark execution for two
families:

- `repo_patch`: repository edits collected as git diffs.
- `terminal_task`: terminal workspace state verified by trusted checkers.

## Core

- `benchmark_pack.py`: loads benchmark manifests and JSONL task rows.
- `benchmark_compiler.py`: validates rows and compiles resources into tasks.
- `tasks.py`: defines normalized `SecureBenchTask` objects and resource helpers.
- `resources.py`: defines resource visibility, redaction, and component views.
- `tester_config.py`, `tester_run.py`, `cli.py`: run tester YAML end to end.

## Candidates

- `candidates/base.py`: defines patch/workspace candidate artifacts.
- `candidates/extraction.py`: extracts repo diffs or workspace paths after harness runs.

## Families

- `families/repo_patch.py`: validates repo-patch row schemas.
- `families/terminal_task.py`: validates terminal-task row schemas.
- `families/registry.py`: exposes the supported family contracts.

## Harnesses

- `harnesses/command.py`: runs a configured command in a benchmark image.
- `harnesses/codex.py`: runs Codex CLI with a mounted overlay.
- `harnesses/claude_code.py`: runs Claude Code with a mounted overlay.
- `harnesses/shared.py`: shared workspace, image, timeout, and materialization helpers.

## Verifiers

- `verifiers/repo_patch.py`: applies candidate patches and runs command checks.
- `verifiers/terminal_task.py`: runs trusted pytest/script checkers against final workspace state.
- `verifiers/registry.py`: returns verifiers for supported families only.

## Execution Support

- `sandboxes/`: host/Docker execution and command policy wrappers.
- `workspaces/`: visibility-aware materialization and workspace path policy.
- `audit/`: built-in static and dynamic robustness checks for the supported families.
