"""Runner skeleton for GitHub patch tasks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from securebench.runners.base import Runner, RunnerResult
from securebench.sandboxes import DockerSandbox, Sandbox
from securebench.tasks import GitHubPatchTask, SecureBenchTask


class GitHubPatchRunner(Runner):
    """Clone a repository, apply a candidate patch, run tests, and collect a diff."""

    def __init__(self, *, sandbox: Sandbox | None = None, timeout: float = 120.0) -> None:
        self.sandbox = sandbox
        self.timeout = timeout

    def run(self, task: SecureBenchTask, candidate: Any, **context: Any) -> RunnerResult:
        if not isinstance(task, GitHubPatchTask):
            raise TypeError(f"GitHubPatchRunner requires GitHubPatchTask, got {type(task).__name__}")

        sandbox = self.sandbox or DockerSandbox(image=context.get("image", "python:3.11-slim"))
        repo_dir = context.get("repo_dir", "repo")
        test_commands = tuple(context.get("test_commands", ()))
        candidate_patch = "" if candidate is None else str(candidate)

        setup_results = [
            sandbox.run(["git", "clone", _repo_url(task.repo), repo_dir], timeout=self.timeout),
            sandbox.run(["git", "checkout", task.base_commit], workdir=repo_dir, timeout=self.timeout),
        ]
        sandbox.write_file(f"{repo_dir}/SECUREBENCH_TASK.md", task.instructions)

        patch_result = None
        if candidate_patch.strip():
            sandbox.write_file("candidate.patch", candidate_patch)
            patch_result = sandbox.run(["git", "apply", "/workspace/candidate.patch"], workdir=repo_dir, timeout=self.timeout)

        test_results = [
            sandbox.run(command, workdir=repo_dir, timeout=self.timeout)
            for command in test_commands
        ]
        diff_result = sandbox.run(["git", "diff", "--binary"], workdir=repo_dir, timeout=self.timeout)

        command_results = [*setup_results]
        if patch_result is not None:
            command_results.append(patch_result)
        command_results.extend(test_results)

        all_results = [*command_results, diff_result]
        passed = all(result.exit_code == 0 for result in all_results)

        return RunnerResult(
            task_id=task.id,
            passed=passed,
            score=1.0 if passed else 0.0,
            stdout=_join_streams(result.stdout for result in all_results),
            stderr=_join_streams(result.stderr for result in all_results),
            metadata={
                "model_patch": diff_result.stdout,
                "repo_dir": repo_dir,
                "exit_codes": [result.exit_code for result in all_results],
            },
        )


def _repo_url(repo: str) -> str:
    if repo.startswith(("http://", "https://", "git@")):
        return repo
    return f"https://github.com/{repo}.git"


def _join_streams(streams: Iterable[str]) -> str:
    return "\n".join(stream for stream in streams if stream)
