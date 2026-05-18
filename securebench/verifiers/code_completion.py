"""Verifier for code-completion benchmark-pack tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from securebench.errors import ConfigError
from securebench.sandboxes import DockerSandbox, Sandbox
from securebench.tasks import CodeCompletionTask, SecureBenchTask, resource_text, resource_value
from securebench.verifiers.base import VerificationResult, Verifier


SandboxFactory = Callable[..., Sandbox]
DEFAULT_TEST_FILE = "solution_test.py"


class CodeCompletionVerifier(Verifier):
    """Run candidate Python code against structured inline hidden tests."""

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory | None = None,
        timeout_seconds: float = 30.0,
        test_file: str = DEFAULT_TEST_FILE,
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.timeout_seconds = timeout_seconds
        self.test_file = test_file

    def verify(self, task: SecureBenchTask, candidate: str, **context: Any) -> VerificationResult:
        if not isinstance(task, CodeCompletionTask):
            raise TypeError(f"CodeCompletionVerifier requires CodeCompletionTask, got {type(task).__name__}")
        language = resource_text(task, "language", "python")
        if language != "python":
            raise ConfigError(f"CodeCompletionVerifier only supports Python tasks, got {language!r}")

        image = environment_image_for_task(task)
        sandbox = self._sandbox(image, context.get("workspace_root"))
        close_sandbox = self.sandbox_factory is None
        test_file = str(context.get("test_file", self.test_file))
        timeout = float(context.get("timeout_seconds", self.timeout_seconds))

        try:
            sandbox.write_file(test_file, build_code_completion_script(task, candidate))
            result = sandbox.run(["python3", test_file], timeout=timeout)
            passed = result.exit_code == 0
            return VerificationResult(
                task_id=task.id,
                status="passed" if passed else "failed",
                passed=passed,
                score=1.0 if passed else 0.0,
                stdout=result.stdout,
                stderr=result.stderr,
                metadata={
                    "verifier": "code_completion",
                    "image": image,
                    "language": language,
                    "test_file": test_file,
                    "exit_code": result.exit_code,
                },
            )
        finally:
            if close_sandbox:
                _close_sandbox(sandbox)

    def _sandbox(self, image: str, workspace_root: Any) -> Sandbox:
        if self.sandbox_factory is not None:
            return self.sandbox_factory(image=image, root=workspace_root)
        return DockerSandbox(
            image=image,
            root=None if workspace_root is None else Path(workspace_root),
            network="none",
        )


def build_code_completion_script(task: CodeCompletionTask, candidate_code: str) -> str:
    """Build the script executed by the code-completion verifier."""
    tests = inline_tests(task)
    if not candidate_code.strip():
        raise ConfigError(f"CodeCompletionTask {task.id!r} has empty candidate text")
    return "\n".join(
        [
            _trim(candidate_code),
            "",
            _trim(tests),
            "",
        ]
    )


def inline_tests(task: CodeCompletionTask) -> str:
    """Return structured inline hidden tests for a code-completion task."""
    tests = resource_value(task, "tests")
    if not isinstance(tests, dict):
        raise ConfigError(f"CodeCompletionTask {task.id!r} requires structured inline tests")
    source = tests.get("source")
    code = tests.get("code")
    if source != "inline" or not isinstance(code, str) or not code.strip():
        raise ConfigError(f"CodeCompletionTask {task.id!r} requires tests.source='inline' and non-empty tests.code")
    return code


def environment_image_for_task(task: SecureBenchTask) -> str:
    """Return the benchmark environment image selected for verifier execution."""
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    environment = metadata.get("environment")
    image = environment.get("image") if isinstance(environment, dict) else None
    if not isinstance(image, str) or not image.strip():
        raise ConfigError(
            "code_completion verification requires benchmark environment.image; "
            "set defaults.environment.image in the manifest or environment.image on the benchmark row"
        )
    return image.strip()


def _trim(value: str) -> str:
    return value.rstrip("\n")


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()
