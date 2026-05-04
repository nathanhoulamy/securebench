"""Sandboxed candidate production for command and workspace-agent workflows."""

from __future__ import annotations

import json
from typing import Any, Callable

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
        sandbox: Sandbox | None = None,
        sandbox_factory: Callable[[], Sandbox] | None = None,
        agent_command: str | list[str] | tuple[str, ...],
        repo_dir: str = "repo",
        task_file: str = "SECUREBENCH_TASK.md",
        setup_commands: tuple[str, ...] = (),
        timeout: float | None = None,
    ) -> None:
        if sandbox is not None and sandbox_factory is not None:
            raise ValueError("SandboxedPatchProducer accepts either sandbox or sandbox_factory, not both")
        if sandbox is None and sandbox_factory is None:
            raise ValueError("SandboxedPatchProducer requires sandbox or sandbox_factory")
        self.sandbox = sandbox
        self.sandbox_factory = sandbox_factory
        self.agent_command = agent_command
        self.repo_dir = repo_dir
        self.task_file = task_file
        self.setup_commands = tuple(setup_commands)
        self.timeout = timeout

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        if not isinstance(task, GitHubPatchTask):
            raise TypeError(f"SandboxedPatchProducer requires GitHubPatchTask, got {type(task).__name__}")

        sandbox = self._new_sandbox()
        timeout = context.get("timeout", self.timeout)
        try:
            clone_result = sandbox.run(["git", "clone", _repo_url(task.repo), self.repo_dir], timeout=timeout)
            checkout_result = sandbox.run(["git", "checkout", task.base_commit], workdir=self.repo_dir, timeout=timeout)
            setup_results = [
                sandbox.run(command, workdir=self.repo_dir, timeout=timeout)
                for command in self.setup_commands
            ]
            sandbox.write_file(f"{self.repo_dir}/{self.task_file}", _task_markdown(task))

            agent_result = sandbox.run(self.agent_command, workdir=self.repo_dir, timeout=timeout)
            diff_result = sandbox.run(["git", "diff", "--binary"], workdir=self.repo_dir, timeout=timeout)

            return CandidateArtifact(
                patch=diff_result.stdout,
                stdout=_join_streams(
                    (
                        clone_result.stdout,
                        checkout_result.stdout,
                        *[result.stdout for result in setup_results],
                        agent_result.stdout,
                        diff_result.stdout,
                    )
                ),
                stderr=_join_streams(
                    (
                        clone_result.stderr,
                        checkout_result.stderr,
                        *[result.stderr for result in setup_results],
                        agent_result.stderr,
                        diff_result.stderr,
                    )
                ),
                metadata={
                    "repo_dir": self.repo_dir,
                    "task_file": self.task_file,
                    "exit_codes": [
                        clone_result.exit_code,
                        checkout_result.exit_code,
                        *[result.exit_code for result in setup_results],
                        agent_result.exit_code,
                        diff_result.exit_code,
                    ],
                    "setup_command_count": len(self.setup_commands),
                    "agent_exit_code": agent_result.exit_code,
                },
            )
        finally:
            if self.sandbox is None:
                _close_sandbox(sandbox)

    def _new_sandbox(self) -> Sandbox:
        if self.sandbox is not None:
            return self.sandbox
        if self.sandbox_factory is None:
            raise ValueError("SandboxedPatchProducer requires sandbox or sandbox_factory")
        return self.sandbox_factory()


class WorkspaceAgentPatchProducer(SandboxedPatchProducer):
    """Run SecureBench's built-in workspace agent and collect its git diff."""

    def __init__(
        self,
        *,
        sandbox: Sandbox | None = None,
        sandbox_factory: Callable[[], Sandbox] | None = None,
        model: str | None = None,
        replay_file: str | None = None,
        repo_dir: str = "repo",
        task_file: str = "SECUREBENCH_TASK.md",
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        max_steps: int = 40,
        max_tool_output: int = 12_000,
        command_timeout: float = 60.0,
        request_timeout: float | None = 60.0,
        temperature: float | None = 0.0,
        allow_commands: tuple[str, ...] = (),
        deny_commands: tuple[str, ...] = (),
        setup_commands: tuple[str, ...] = (),
        timeout: float | None = None,
    ) -> None:
        super().__init__(
            sandbox=sandbox,
            sandbox_factory=sandbox_factory,
            agent_command=_agent_command(
                task_file=task_file,
                model=model,
                replay_file=replay_file,
                base_url=base_url,
                api_key_env=api_key_env,
                max_steps=max_steps,
                max_tool_output=max_tool_output,
                command_timeout=command_timeout,
                request_timeout=request_timeout,
                temperature=temperature,
                allow_commands=allow_commands,
                deny_commands=deny_commands,
            ),
            repo_dir=repo_dir,
            task_file=task_file,
            setup_commands=setup_commands,
            timeout=timeout,
        )


def _repo_url(repo: str) -> str:
    if repo.startswith(("http://", "https://", "git@")):
        return repo
    return f"https://github.com/{repo}.git"


def _task_markdown(task: GitHubPatchTask) -> str:
    payload = task.agent_payload()
    lines = [
        "# SecureBench Task",
        "",
        "## Repository",
        "",
        f"- repo: {payload['repo']}",
        f"- base_commit: {payload['base_commit']}",
    ]
    if "version" in payload:
        lines.append(f"- version: {payload['version']}")

    lines.extend(["", "## Instructions", "", payload["instructions"]])
    if "hints_text" in payload:
        lines.extend(["", "## Hints", "", payload["hints_text"]])
    return "\n".join(lines) + "\n"


def _join_streams(streams: tuple[str, ...]) -> str:
    return "\n".join(stream for stream in streams if stream)


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()


def _agent_command(
    *,
    task_file: str,
    model: str | None,
    replay_file: str | None,
    base_url: str,
    api_key_env: str,
    max_steps: int,
    max_tool_output: int,
    command_timeout: float,
    request_timeout: float | None,
    temperature: float | None,
    allow_commands: tuple[str, ...],
    deny_commands: tuple[str, ...],
) -> list[str]:
    command = [
        "python",
        "-m",
        "securebench.agent.run",
        "--repo-root",
        ".",
        "--task-file",
        task_file,
        "--max-steps",
        str(max_steps),
        "--max-tool-output",
        str(max_tool_output),
        "--command-timeout",
        str(command_timeout),
    ]
    if replay_file is not None:
        command.extend(["--replay-file", replay_file])
    elif model is not None:
        command.extend(
            [
                "--model",
                model,
                "--base-url",
                base_url,
                "--api-key-env",
                api_key_env,
            ]
        )
    else:
        raise ValueError("WorkspaceAgentPatchProducer requires either model or replay_file")
    if request_timeout is not None:
        command.extend(["--timeout", str(request_timeout)])
    if temperature is not None:
        command.extend(["--temperature", str(temperature)])
    for allowed in allow_commands:
        command.extend(["--allow-command", allowed])
    for denied in deny_commands:
        command.extend(["--deny-command", denied])
    return command
