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
DEFAULT_WORKER_FILE = "candidate_worker.py"
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
        worker_file: str = DEFAULT_WORKER_FILE,
        success_sentinel: str = DEFAULT_SUCCESS_SENTINEL,
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.timeout_seconds = timeout_seconds
        self.test_file = test_file
        self.candidate_file = candidate_file
        self.supervisor_file = supervisor_file
        self.worker_file = worker_file
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
            worker_file = str(context.get("worker_file", self.worker_file))
            success_sentinel = str(context.get("success_sentinel", self.success_sentinel))
            sandbox.write_file(candidate_file, build_candidate_module(candidate))
            sandbox.write_file(test_file, build_code_completion_runner(task))
            sandbox.write_file(worker_file, build_code_completion_worker())
            sandbox.write_file(
                supervisor_file,
                build_code_completion_supervisor(test_file, candidate_file, worker_file, success_sentinel),
            )
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
                    "worker_file": worker_file,
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
            cap_add=("SETGID", "SETUID"),
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
    """Build the trusted runner that executes tests through a candidate subprocess."""
    tests = inline_tests(task)
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import ast",
            "import builtins",
            "import os",
            "import pickle",
            "import pathlib",
            "import pwd",
            "import grp",
            "import shutil",
            "import struct",
            "import subprocess",
            "import sys",
            "import tempfile",
            "",
            f"TEST_SOURCE = {tests!r}",
            "",
            "",
            "class CandidateWorker:",
            "    def __init__(self, worker_path: str, candidate_path: str) -> None:",
            "        self._request_read, self._request_write = os.pipe()",
            "        self._response_read, self._response_write = os.pipe()",
            "        env = dict(os.environ)",
            "        env['SECUREBENCH_REQUEST_FD'] = str(self._request_read)",
            "        env['SECUREBENCH_RESPONSE_FD'] = str(self._response_write)",
            "        self._workdir = tempfile.TemporaryDirectory(prefix='securebench-candidate-')",
            "        os.chmod(self._workdir.name, 0o755)",
            "        isolated_worker = pathlib.Path(self._workdir.name) / 'candidate_worker.py'",
            "        isolated_candidate = pathlib.Path(self._workdir.name) / 'candidate.py'",
            "        shutil.copyfile(worker_path, isolated_worker)",
            "        shutil.copyfile(candidate_path, isolated_candidate)",
            "        os.chmod(isolated_worker, 0o644)",
            "        os.chmod(isolated_candidate, 0o644)",
            "        preexec_fn = _drop_privileges_fn()",
            "        self._process = subprocess.Popen(",
            "            [sys.executable, str(isolated_worker), str(isolated_candidate)],",
            "            cwd=self._workdir.name,",
            "            env=env,",
            "            pass_fds=(self._request_read, self._response_write),",
            "            preexec_fn=preexec_fn,",
            "        )",
            "        os.close(self._request_read)",
            "        os.close(self._response_write)",
            "        ready = _read_message(self._response_read)",
            "        if not ready.get('ok'):",
            "            self.close()",
            "            _raise_candidate_error(ready)",
            "",
            "    def call(self, name: str, args: tuple, kwargs: dict):",
            "        _write_message(self._request_write, {'op': 'call', 'name': name, 'args': args, 'kwargs': kwargs})",
            "        response = _read_message(self._response_read)",
            "        if response.get('ok'):",
            "            return response.get('value')",
            "        _raise_candidate_error(response)",
            "",
            "    def get(self, name: str):",
            "        _write_message(self._request_write, {'op': 'get', 'name': name})",
            "        response = _read_message(self._response_read)",
            "        if response.get('ok'):",
            "            return response.get('value')",
            "        _raise_candidate_error(response)",
            "",
            "    def close(self) -> None:",
            "        try:",
            "            _write_message(self._request_write, {'op': 'close'})",
            "        except Exception:",
            "            pass",
            "        for fd in (self._request_write, self._response_read):",
            "            try:",
            "                os.close(fd)",
            "            except OSError:",
            "                pass",
            "        try:",
            "            self._process.wait(timeout=2)",
            "        except subprocess.TimeoutExpired:",
            "            self._process.kill()",
            "            self._process.wait()",
            "        self._workdir.cleanup()",
            "",
            "",
            "def _write_message(fd: int, message: dict) -> None:",
            "    payload = pickle.dumps(message, protocol=4)",
            "    os.write(fd, struct.pack('!I', len(payload)) + payload)",
            "",
            "",
            "def _read_message(fd: int) -> dict:",
            "    header = _read_exact(fd, 4)",
            "    if not header:",
            "        raise RuntimeError('candidate worker exited before responding')",
            "    size = struct.unpack('!I', header)[0]",
            "    return pickle.loads(_read_exact(fd, size))",
            "",
            "",
            "def _read_exact(fd: int, size: int) -> bytes:",
            "    chunks = []",
            "    remaining = size",
            "    while remaining:",
            "        chunk = os.read(fd, remaining)",
            "        if not chunk:",
            "            raise RuntimeError('candidate worker protocol ended unexpectedly')",
            "        chunks.append(chunk)",
            "        remaining -= len(chunk)",
            "    return b''.join(chunks)",
            "",
            "",
            "def _raise_candidate_error(response: dict) -> None:",
            "    exc_type = response.get('exc_type') or 'RuntimeError'",
            "    message = response.get('message') or 'candidate operation failed'",
            "    exc_class = getattr(builtins, exc_type, RuntimeError)",
            "    if not isinstance(exc_class, type) or not issubclass(exc_class, BaseException):",
            "        exc_class = RuntimeError",
            "    raise exc_class(message)",
            "",
            "",
            "def _drop_privileges_fn():",
            "    if os.name != 'posix' or os.geteuid() != 0:",
            "        return None",
            "    try:",
            "        user = pwd.getpwnam('nobody')",
            "    except KeyError:",
            "        return None",
            "    try:",
            "        group = grp.getgrnam('nogroup')",
            "        gid = group.gr_gid",
            "    except KeyError:",
            "        gid = user.pw_gid",
            "",
            "    def drop() -> None:",
            "        try:",
            "            os.setgroups([])",
            "        except OSError:",
            "            pass",
            "        os.setgid(gid)",
            "        os.setuid(user.pw_uid)",
            "",
            "    return drop",
            "",
            "",
            "def _protect_trusted_file(path: str) -> None:",
            "    if os.name != 'posix':",
            "        return",
            "    try:",
            "        pathlib.Path(path).chmod(0o600)",
            "    except OSError:",
            "        pass",
            "",
            "",
            "def _candidate_exports(path: str) -> tuple[list[str], list[str]]:",
            "    tree = ast.parse(pathlib.Path(path).read_text(), filename=path)",
            "    functions = []",
            "    values = []",
            "    for node in tree.body:",
            "        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):",
            "            functions.append(node.name)",
            "        elif isinstance(node, ast.Assign):",
            "            values.extend(target.id for target in node.targets if isinstance(target, ast.Name))",
            "        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):",
            "            values.append(node.target.id)",
            "    return functions, values",
            "",
            "",
            "def _make_proxy(worker: CandidateWorker, name: str):",
            "    def proxy(*args, **kwargs):",
            "        return worker.call(name, args, kwargs)",
            "    proxy.__name__ = name",
            "    return proxy",
            "",
            "",
            "def main() -> int:",
            "    if len(sys.argv) != 4:",
            "        raise RuntimeError('usage: solution_test.py <candidate.py> <candidate_worker.py> <success-sentinel>')",
            "    candidate_path = str(pathlib.Path(sys.argv[1]).resolve())",
            "    worker_path = str(pathlib.Path(sys.argv[2]).resolve())",
            "    success_sentinel = sys.argv[3]",
            "    _protect_trusted_file(__file__)",
            "    worker = CandidateWorker(worker_path, candidate_path)",
            "    try:",
            "        test_globals = {'__builtins__': __builtins__, '__name__': '__securebench_tests__'}",
            "        function_names, value_names = _candidate_exports(candidate_path)",
            "        for name in function_names:",
            "            test_globals[name] = _make_proxy(worker, name)",
            "        for name in value_names:",
            "            if name not in test_globals:",
            "                test_globals[name] = worker.get(name)",
            "        exec(compile(TEST_SOURCE, '<securebench-hidden-tests>', 'exec'), test_globals)",
            "        pathlib.Path(success_sentinel).parent.mkdir(parents=True, exist_ok=True)",
            "        pathlib.Path(success_sentinel).write_text('ok\\n')",
            "        return 0",
            "    finally:",
            "        worker.close()",
            "",
            "",
            "if __name__ == '__main__':",
            "    raise SystemExit(main())",
            "",
        ]
    )


def build_code_completion_worker() -> str:
    """Build the untrusted candidate worker. Hidden tests are never embedded here."""
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import importlib.util",
            "import builtins",
            "import os",
            "import pickle",
            "import pathlib",
            "import struct",
            "import sys",
            "",
            "ORIGINAL_BUILTINS = dict(vars(builtins))",
            "",
            "",
            "def _restore_builtins() -> None:",
            "    for name in tuple(vars(builtins)):",
            "        if name not in ORIGINAL_BUILTINS:",
            "            delattr(builtins, name)",
            "    for name, value in ORIGINAL_BUILTINS.items():",
            "        setattr(builtins, name, value)",
            "",
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
            "        spec.loader.exec_module(module)",
            "    except SystemExit as exc:",
            "        raise RuntimeError(f'candidate attempted to exit during import: {exc}') from exc",
            "    return module",
            "",
            "",
            "def _write_message(fd: int, message: dict) -> None:",
            "    try:",
            "        payload = pickle.dumps(message, protocol=4)",
            "    except Exception as exc:",
            "        message = {'ok': False, 'exc_type': type(exc).__name__, 'message': str(exc)}",
            "        payload = pickle.dumps(message, protocol=4)",
            "    os.write(fd, struct.pack('!I', len(payload)) + payload)",
            "",
            "",
            "def _read_message(fd: int) -> dict | None:",
            "    header = _read_exact(fd, 4)",
            "    if not header:",
            "        return None",
            "    size = struct.unpack('!I', header)[0]",
            "    return pickle.loads(_read_exact(fd, size))",
            "",
            "",
            "def _read_exact(fd: int, size: int) -> bytes:",
            "    chunks = []",
            "    remaining = size",
            "    while remaining:",
            "        chunk = os.read(fd, remaining)",
            "        if not chunk:",
            "            if chunks:",
            "                raise RuntimeError('candidate worker protocol ended unexpectedly')",
            "            return b''",
            "        chunks.append(chunk)",
            "        remaining -= len(chunk)",
            "    return b''.join(chunks)",
            "",
            "",
            "def main() -> int:",
            "    if len(sys.argv) != 2:",
            "        raise RuntimeError('usage: candidate_worker.py <candidate.py>')",
            "    request_fd = int(os.environ['SECUREBENCH_REQUEST_FD'])",
            "    response_fd = int(os.environ['SECUREBENCH_RESPONSE_FD'])",
            "    try:",
            "        candidate = _load_candidate(sys.argv[1])",
            "    except BaseException as exc:",
            "        _write_message(response_fd, {'ok': False, 'exc_type': type(exc).__name__, 'message': str(exc)})",
            "        return 1",
            "    _restore_builtins()",
            "    _write_message(response_fd, {'ok': True})",
            "    while True:",
            "        request = _read_message(request_fd)",
            "        if request is None or request.get('op') == 'close':",
            "            return 0",
            "        try:",
            "            if request.get('op') == 'get':",
            "                value = getattr(candidate, request['name'])",
            "            else:",
            "                function = getattr(candidate, request['name'])",
            "                value = function(*request.get('args', ()), **request.get('kwargs', {}))",
            "        except BaseException as exc:",
            "            _restore_builtins()",
            "            _write_message(response_fd, {'ok': False, 'exc_type': type(exc).__name__, 'message': str(exc)})",
            "        else:",
            "            _restore_builtins()",
            "            _write_message(response_fd, {'ok': True, 'value': value})",
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
    worker_file: str,
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
            f"WORKER_FILE = {worker_file!r}",
            f"SUCCESS_SENTINEL = {success_sentinel!r}",
            "",
            "",
            "def main() -> int:",
            "    sentinel = pathlib.Path(SUCCESS_SENTINEL)",
            "    if sentinel.exists():",
            "        sentinel.unlink()",
            "    result = subprocess.run([sys.executable, TEST_FILE, CANDIDATE_FILE, WORKER_FILE, SUCCESS_SENTINEL], check=False)",
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
