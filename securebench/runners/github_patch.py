"""Runner skeleton for GitHub patch tasks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from securebench.repositories import (
    RepositoryPreparationError,
    RepositoryPreparer,
    TrustedGitRepositoryPreparer,
)
from securebench.runners.base import Runner, RunnerResult
from securebench.sandboxes import CommandResult, DockerSandbox, Sandbox
from securebench.tasks import GitHubPatchTask, SecureBenchTask


class GitHubPatchRunner(Runner):
    """Apply a candidate patch in a prepared repository and run tests."""

    def __init__(
        self,
        *,
        sandbox: Sandbox | None = None,
        sandbox_factory: Callable[[], Sandbox] | None = None,
        image: str = "python:3.11-slim",
        sandbox_kwargs: dict[str, Any] | None = None,
        repository_preparer: RepositoryPreparer | None = None,
        repo_dir: str = "repo",
        setup_commands: Iterable[str] = (),
        test_commands: Iterable[str] = (),
        apply_hidden_patches: Iterable[str] = (),
        test_group_names: Iterable[str] = (),
        test_command_template: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        if sandbox is not None and sandbox_factory is not None:
            raise ValueError("GitHubPatchRunner accepts either sandbox or sandbox_factory, not both")
        self.sandbox = sandbox
        self.sandbox_factory = sandbox_factory
        self.image = image
        self.sandbox_kwargs = dict(sandbox_kwargs or {})
        self.repository_preparer = repository_preparer or TrustedGitRepositoryPreparer()
        self.repo_dir = repo_dir
        self.setup_commands = tuple(setup_commands)
        self.test_commands = tuple(test_commands)
        self.apply_hidden_patches = tuple(apply_hidden_patches)
        self.test_group_names = tuple(test_group_names)
        self.test_command_template = test_command_template
        self.timeout = timeout

    def run(self, task: SecureBenchTask, candidate: Any, **context: Any) -> RunnerResult:
        if not isinstance(task, GitHubPatchTask):
            raise TypeError(f"GitHubPatchRunner requires GitHubPatchTask, got {type(task).__name__}")

        timeout = context.get("timeout", self.timeout)
        sandbox = self._new_sandbox(context)
        repo_dir = context.get("repo_dir", self.repo_dir)
        setup_commands = tuple(context.get("setup_commands", self.setup_commands))
        test_group_names = tuple(context.get("test_group_names", self.test_group_names))
        test_command_template = context.get("test_command_template", self.test_command_template)
        selected_tests = _select_tests(task, test_group_names)
        generated_test_commands = _build_test_commands(test_command_template, selected_tests)
        test_commands = (
            *tuple(context.get("test_commands", self.test_commands)),
            *generated_test_commands,
        )
        apply_hidden_patches = tuple(context.get("apply_hidden_patches", self.apply_hidden_patches))
        candidate_patch = "" if candidate is None else str(candidate)

        try:
            try:
                self.repository_preparer.prepare(task, sandbox, repo_dir=repo_dir, timeout=timeout)
            except RepositoryPreparationError as exc:
                return RunnerResult(
                    task_id=task.id,
                    passed=False,
                    score=0.0,
                    stderr=str(exc),
                    metadata={
                        "model_patch": candidate_patch,
                        "repo_dir": repo_dir,
                        "exit_codes": [],
                        "repository_preparation_error": str(exc),
                    },
                )
            sandbox.write_file(f"{repo_dir}/SECUREBENCH_TASK.md", task.instructions)

            patch_result = None
            if candidate_patch.strip():
                sandbox.write_file("candidate.patch", candidate_patch)
                patch_result = sandbox.run(["git", "apply", "/workspace/candidate.patch"], workdir=repo_dir, timeout=timeout)

            hidden_patch_results = []
            applied_hidden_patch_names = []
            for patch_name in apply_hidden_patches:
                patch = task.hidden_patches.get(patch_name)
                if patch is None:
                    hidden_patch_results.append(
                        _missing_patch_result(patch_name)
                    )
                    continue
                patch_path = f"hidden-{_safe_patch_name(patch_name)}.patch"
                sandbox.write_file(patch_path, patch)
                hidden_patch_results.append(
                    sandbox.run(["git", "apply", f"/workspace/{patch_path}"], workdir=repo_dir, timeout=timeout)
                )
                applied_hidden_patch_names.append(patch_name)

            command_setup_results = [
                sandbox.run(command, workdir=repo_dir, timeout=timeout)
                for command in setup_commands
            ]
            test_results = [
                sandbox.run(command, workdir=repo_dir, timeout=timeout)
                for command in test_commands
            ]

            command_results = []
            if patch_result is not None:
                command_results.append(patch_result)
            command_results.extend(hidden_patch_results)
            command_results.extend(command_setup_results)
            command_results.extend(test_results)

            all_results = command_results
            if not all_results:
                return RunnerResult(
                    task_id=task.id,
                    passed=False,
                    score=0.0,
                    stderr="No patch, setup, hidden patch, or test commands were run.",
                    metadata={
                        "model_patch": candidate_patch,
                        "repo_dir": repo_dir,
                        "exit_codes": [],
                        "setup_command_count": len(setup_commands),
                        "test_command_count": len(test_commands),
                        "selected_test_count": len(selected_tests),
                        "test_group_names": list(test_group_names),
                        "applied_hidden_patch_names": applied_hidden_patch_names,
                        "error": "no_commands_run",
                    },
                )
            passed = all(result.exit_code == 0 for result in all_results)

            return RunnerResult(
                task_id=task.id,
                passed=passed,
                score=1.0 if passed else 0.0,
                stdout=_join_streams(result.stdout for result in all_results),
                stderr=_join_streams(result.stderr for result in all_results),
                metadata={
                    "model_patch": candidate_patch,
                    "repo_dir": repo_dir,
                    "exit_codes": [result.exit_code for result in all_results],
                    "setup_command_count": len(setup_commands),
                    "test_command_count": len(test_commands),
                    "selected_test_count": len(selected_tests),
                    "test_group_names": list(test_group_names),
                    "applied_hidden_patch_names": applied_hidden_patch_names,
                },
            )
        finally:
            if self.sandbox is None:
                _close_sandbox(sandbox)

    def _new_sandbox(self, context: dict[str, Any]) -> Sandbox:
        if self.sandbox is not None:
            return self.sandbox
        if self.sandbox_factory is not None:
            return self.sandbox_factory()
        return DockerSandbox(image=context.get("image", self.image), **self.sandbox_kwargs)


def _join_streams(streams: Iterable[str]) -> str:
    return "\n".join(stream for stream in streams if stream)


def _select_tests(task: GitHubPatchTask, group_names: tuple[str, ...]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for group_name in group_names:
        for test_name in task.test_groups.get(group_name, ()):
            if test_name not in seen:
                selected.append(test_name)
                seen.add(test_name)
    return tuple(selected)


def _build_test_commands(template: str | None, selected_tests: tuple[str, ...]) -> tuple[str, ...]:
    if template is None:
        return ()
    tests = " ".join(selected_tests)
    return (template.format(tests=tests),)


def _safe_patch_name(name: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in name)
    return safe or "patch"


def _missing_patch_result(name: str) -> CommandResult:
    return CommandResult(
        command=("apply-hidden-patch", name),
        exit_code=1,
        stderr=f"Hidden patch {name!r} is not available for task",
    )


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()
