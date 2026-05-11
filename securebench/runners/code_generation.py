"""Runner for Python code-generation tasks."""

from __future__ import annotations

from typing import Any

from securebench.runners.base import Runner, RunnerResult
from securebench.sandboxes import DockerSandbox, Sandbox
from securebench.tasks import (
    CodeGenerationTask,
    SecureBenchTask,
    optional_resource_text,
    resource_text,
)


class CodeGenerationRunner(Runner):
    """Execute generated Python code against hidden tests in a sandbox."""

    def __init__(self, *, sandbox: Sandbox | None = None, timeout: float = 10.0) -> None:
        self.sandbox = sandbox
        self.timeout = timeout

    def run(self, task: SecureBenchTask, candidate: Any, **context: Any) -> RunnerResult:
        if not isinstance(task, CodeGenerationTask):
            raise TypeError(f"CodeGenerationRunner requires CodeGenerationTask, got {type(task).__name__}")
        language = resource_text(task, "language", "python")
        tests = optional_resource_text(task, "tests")
        if language != "python":
            raise ValueError(f"CodeGenerationRunner only supports Python tasks, got {language!r}")
        if tests is None:
            raise ValueError(f"CodeGenerationTask {task.id!r} has no hidden tests")

        sandbox = self.sandbox or DockerSandbox()
        test_file = str(context.get("test_file", "solution_test.py"))
        script = build_python_test_script(task, str(candidate))

        try:
            sandbox.write_file(test_file, script)
            result = sandbox.run(["python", test_file], timeout=self.timeout)
            passed = result.exit_code == 0

            return RunnerResult(
                task_id=task.id,
                passed=passed,
                score=1.0 if passed else 0.0,
                stdout=result.stdout,
                stderr=result.stderr,
                metadata={
                    "exit_code": result.exit_code,
                    "test_file": test_file,
                },
            )
        finally:
            if self.sandbox is None:
                _close_sandbox(sandbox)


def build_python_test_script(task: CodeGenerationTask, candidate_code: str) -> str:
    """Build a single Python script containing candidate code and hidden tests."""
    tests = optional_resource_text(task, "tests")
    if tests is None:
        raise ValueError(f"CodeGenerationTask {task.id!r} has no hidden tests")

    entry_point = optional_resource_text(task, "entry_point")
    parts = [
        _trim_trailing_newlines(resource_text(task, "prompt")),
        _trim_trailing_newlines(candidate_code),
        "",
        _trim_trailing_newlines(tests),
    ]
    if entry_point:
        parts.extend(["", f"check({entry_point})"])
    return "\n".join(parts) + "\n"


def _trim_trailing_newlines(value: str) -> str:
    return value.rstrip("\n")


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()
