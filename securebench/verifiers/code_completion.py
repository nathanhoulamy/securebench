"""Verifier for code-completion benchmark-pack tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from securebench.errors import ConfigError
from securebench.sandboxes import DockerSandbox, Sandbox
from securebench.tasks import CodeCompletionTask, SecureBenchTask, resource_text, resource_value
from securebench.verifiers.base import VerificationResult, Verifier, timeout_metadata


SandboxFactory = Callable[..., Sandbox]
DEFAULT_TEST_FILE = "solution_test.py"
DEFAULT_CANDIDATE_FILE = "candidate.py"
DEFAULT_SUPERVISOR_FILE = "solution_supervisor.py"
DEFAULT_SUCCESS_SENTINEL = "securebench/code_completion_success"


class CodeCompletionVerifier(Verifier):
    """Run candidate Python code against structured inline hidden tests."""

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory | None = None,
        timeout_seconds: float = 30.0,
        test_file: str = DEFAULT_TEST_FILE,
        candidate_file: str = DEFAULT_CANDIDATE_FILE,
        supervisor_file: str = DEFAULT_SUPERVISOR_FILE,
        success_sentinel: str = DEFAULT_SUCCESS_SENTINEL,
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.timeout_seconds = timeout_seconds
        self.test_file = test_file
        self.candidate_file = candidate_file
        self.supervisor_file = supervisor_file
        self.success_sentinel = success_sentinel

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
            candidate_file = str(context.get("candidate_file", self.candidate_file))
            supervisor_file = str(context.get("supervisor_file", self.supervisor_file))
            success_sentinel = str(context.get("success_sentinel", self.success_sentinel))
            sandbox.write_file(candidate_file, build_candidate_module(candidate))
            sandbox.write_file(test_file, build_code_completion_runner(task))
            sandbox.write_file(supervisor_file, build_code_completion_supervisor(test_file, candidate_file, success_sentinel))
            result = sandbox.run(["python3", supervisor_file], timeout=timeout)
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
                    "candidate_file": candidate_file,
                    "supervisor_file": supervisor_file,
                    "exit_code": result.exit_code,
                    **timeout_metadata(result),
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
    """Build the trusted test runner.

    The candidate source is accepted for compatibility with older callers, but
    it is intentionally not concatenated with hidden tests.
    """
    if not candidate_code.strip():
        raise ConfigError(f"CodeCompletionTask {task.id!r} has empty candidate text")
    return build_code_completion_runner(task)


def build_candidate_module(candidate_code: str) -> str:
    """Return the candidate module source written for verifier import."""
    if not candidate_code.strip():
        raise ConfigError("CodeCompletionTask has empty candidate text")
    return _trim(candidate_code) + "\n"


def build_code_completion_runner(task: CodeCompletionTask) -> str:
    """Build the trusted runner that imports the candidate and executes tests."""
    tests = inline_tests(task)
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import builtins",
            "import importlib.util",
            "import os",
            "import pathlib",
            "import sys",
            "",
            f"TEST_SOURCE = {tests!r}",
            "ORIGINAL_BUILTINS = dict(vars(builtins))",
            "ORIGINAL_META_PATH = tuple(sys.meta_path)",
            "ORIGINAL_OS_EXIT = os._exit",
            "ORIGINAL_PATH = tuple(sys.path)",
            "ORIGINAL_PATH_HOOKS = tuple(sys.path_hooks)",
            "",
            "",
            "def _blocked_os_exit(code: int = 0) -> None:",
            "    raise RuntimeError(f'candidate attempted to terminate process with os._exit({code})')",
            "",
            "",
            "def _load_candidate(path: str):",
            "    candidate_path = pathlib.Path(path)",
            "    spec = importlib.util.spec_from_file_location('securebench_candidate', candidate_path)",
            "    if spec is None or spec.loader is None:",
            "        raise RuntimeError(f'could not load candidate module: {candidate_path}')",
            "    module = importlib.util.module_from_spec(spec)",
            "    sys.modules[spec.name] = module",
            "    try:",
            "        os._exit = _blocked_os_exit",
            "        spec.loader.exec_module(module)",
            "    except SystemExit as exc:",
            "        raise RuntimeError(f'candidate attempted to exit during import: {exc}') from exc",
            "    finally:",
            "        os._exit = ORIGINAL_OS_EXIT",
            "    return module",
            "",
            "",
            "def _restore_process_import_state() -> None:",
            "    for name in tuple(vars(builtins)):",
            "        if name not in ORIGINAL_BUILTINS:",
            "            delattr(builtins, name)",
            "    for name, value in ORIGINAL_BUILTINS.items():",
            "        setattr(builtins, name, value)",
            "    sys.meta_path[:] = ORIGINAL_META_PATH",
            "    os._exit = ORIGINAL_OS_EXIT",
            "    sys.path[:] = ORIGINAL_PATH",
            "    sys.path_hooks[:] = ORIGINAL_PATH_HOOKS",
            "    sys.path_importer_cache.clear()",
            "",
            "",
            "def main() -> int:",
            "    if len(sys.argv) != 3:",
            "        raise RuntimeError('usage: solution_test.py <candidate.py> <success-sentinel>')",
            "    candidate = _load_candidate(sys.argv[1])",
            "    _restore_process_import_state()",
            "    test_globals = {",
            "        '__builtins__': __builtins__,",
            "        '__name__': '__securebench_tests__',",
            "    }",
            "    test_globals.update(",
            "        {name: value for name, value in vars(candidate).items() if not name.startswith('__')}",
            "    )",
            "    exec(compile(TEST_SOURCE, '<securebench-hidden-tests>', 'exec'), test_globals)",
            "    pathlib.Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True)",
            "    pathlib.Path(sys.argv[2]).write_text('ok\\n')",
            "    return 0",
            "",
            "",
            "if __name__ == '__main__':",
            "    raise SystemExit(main())",
            "",
        ]
    )


def build_code_completion_supervisor(
    test_file: str,
    candidate_file: str,
    success_sentinel: str,
) -> str:
    """Build a supervisor that fails if the test child exits before completion."""
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import pathlib",
            "import subprocess",
            "import sys",
            "",
            f"TEST_FILE = {test_file!r}",
            f"CANDIDATE_FILE = {candidate_file!r}",
            f"SUCCESS_SENTINEL = {success_sentinel!r}",
            "",
            "",
            "def main() -> int:",
            "    sentinel = pathlib.Path(SUCCESS_SENTINEL)",
            "    if sentinel.exists():",
            "        sentinel.unlink()",
            "    result = subprocess.run([sys.executable, TEST_FILE, CANDIDATE_FILE, SUCCESS_SENTINEL], check=False)",
            "    if result.returncode != 0:",
            "        return result.returncode",
            "    if not sentinel.exists():",
            "        print('securebench: hidden tests did not complete', file=sys.stderr)",
            "        return 1",
            "    return 0",
            "",
            "",
            "if __name__ == '__main__':",
            "    raise SystemExit(main())",
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

