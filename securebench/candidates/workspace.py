"""Sandboxed candidate production for command and workspace-agent workflows."""

from __future__ import annotations

import json
from typing import Any

from securebench.candidates.base import CandidateArtifact, CandidateProducer
from securebench.sandboxes import Sandbox
from securebench.tasks import GitHubPatchTask, SecureBenchTask


class SandboxedCommandProducer(CandidateProducer):
    """Run a command in a sandbox and read text output from a file or stdout."""

    def __init__(
        self,
        *,
        sandbox: Sandbox,
        command: str | list[str] | tuple[str, ...],
        artifact_path: str | None = None,
        task_file: str = "securebench_task.json",
        timeout: float | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.command = command
        self.artifact_path = artifact_path
        self.task_file = task_file
        self.timeout = timeout

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        self.sandbox.write_file(self.task_file, json.dumps(task.agent_payload(), indent=2, sort_keys=True))
        result = self.sandbox.run(self.command, timeout=context.get("timeout", self.timeout))

        text = result.stdout
        if self.artifact_path is not None:
            text = self.sandbox.read_file(self.artifact_path)

        return CandidateArtifact(
            text=text,
            stdout=result.stdout,
            stderr=result.stderr,
            metadata={
                "exit_code": result.exit_code,
                "task_file": self.task_file,
                "artifact_path": self.artifact_path,
            },
        )


class SandboxedPatchProducer(CandidateProducer):
    """Let a sandboxed agent edit a checked-out repo, then collect git diff."""

    def __init__(
        self,
        *,
        sandbox: Sandbox,
        agent_command: str | list[str] | tuple[str, ...],
        repo_dir: str = "repo",
        task_file: str = "SECUREBENCH_TASK.md",
        timeout: float | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.agent_command = agent_command
        self.repo_dir = repo_dir
        self.task_file = task_file
        self.timeout = timeout

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        if not isinstance(task, GitHubPatchTask):
            raise TypeError(f"SandboxedPatchProducer requires GitHubPatchTask, got {type(task).__name__}")

        timeout = context.get("timeout", self.timeout)
        clone_result = self.sandbox.run(["git", "clone", _repo_url(task.repo), self.repo_dir], timeout=timeout)
        checkout_result = self.sandbox.run(["git", "checkout", task.base_commit], workdir=self.repo_dir, timeout=timeout)
        self.sandbox.write_file(f"{self.repo_dir}/{self.task_file}", _task_markdown(task))

        agent_result = self.sandbox.run(self.agent_command, workdir=self.repo_dir, timeout=timeout)
        diff_result = self.sandbox.run(["git", "diff", "--binary"], workdir=self.repo_dir, timeout=timeout)

        return CandidateArtifact(
            patch=diff_result.stdout,
            stdout=_join_streams((clone_result.stdout, checkout_result.stdout, agent_result.stdout, diff_result.stdout)),
            stderr=_join_streams((clone_result.stderr, checkout_result.stderr, agent_result.stderr, diff_result.stderr)),
            metadata={
                "repo_dir": self.repo_dir,
                "task_file": self.task_file,
                "exit_codes": [
                    clone_result.exit_code,
                    checkout_result.exit_code,
                    agent_result.exit_code,
                    diff_result.exit_code,
                ],
                "agent_exit_code": agent_result.exit_code,
            },
        )


def _repo_url(repo: str) -> str:
    if repo.startswith(("http://", "https://", "git@")):
        return repo
    return f"https://github.com/{repo}.git"


def _task_markdown(task: GitHubPatchTask) -> str:
    payload = task.agent_payload()
    lines = [f"# {task.id}", "", payload["instructions"]]
    if "hints_text" in payload:
        lines.extend(["", "## Hints", "", payload["hints_text"]])
    return "\n".join(lines) + "\n"


def _join_streams(streams: tuple[str, ...]) -> str:
    return "\n".join(stream for stream in streams if stream)
