import pytest

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import task_from_spec
from securebench.verifiers.code_completion import (
    CodeCompletionVerifier,
    build_candidate_module,
    build_code_completion_runner,
    build_code_completion_script,
    build_code_completion_supervisor,
    environment_image_for_task,
    inline_tests,
)


class FakeSandbox(Sandbox):
    def __init__(self, *, image=None, root=None, exit_code=0, stdout="", stderr=""):
        self.image = image
        self.root = root
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.files = {}
        self.commands = []

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((tuple(command), workdir, timeout))
        return CommandResult(tuple(command), self.exit_code, self.stdout, self.stderr)

    def write_file(self, path, content):
        self.files[str(path)] = content

    def read_file(self, path):
        return self.files[str(path)]

    def extract_file(self, path):
        return self.files[str(path)].encode()


def make_task(*, image="python:3.12-slim", tests=None):
    return task_from_spec(
        {
            "id": "code-completion-smoke/add_numbers",
            "benchmark_id": "code-completion-smoke",
            "task_type": "code_completion",
            "metadata": {
                "environment": {"image": image},
            },
            "resources": {
                "language": {"value": "python", "visibility": "public"},
                "prompt": {"value": "# define add_numbers\n", "visibility": "public"},
                "tests": {
                    "value": tests
                    if tests is not None
                    else {
                        "source": "inline",
                        "code": "def check():\n    assert add_numbers(2, 3) == 5\n\ncheck()\n",
                    },
                    "visibility": "evaluation_inputs",
                },
            },
        }
    )


def test_inline_tests_requires_structured_inline_tests():
    assert inline_tests(make_task()) == "def check():\n    assert add_numbers(2, 3) == 5\n\ncheck()\n"

    with pytest.raises(ConfigError, match="requires structured inline tests"):
        inline_tests(make_task(tests="assert False"))


def test_build_code_completion_script_does_not_concatenate_candidate_and_tests():
    script = build_code_completion_script(make_task(), "def add_numbers(a, b):\n    return a + b\n")

    assert "def add_numbers(a, b)" not in script
    assert "TEST_SOURCE =" in script
    assert "spec.loader.exec_module(module)" in script


def test_build_code_completion_runner_imports_candidate_module():
    runner = build_code_completion_runner(make_task())

    assert "TEST_SOURCE =" in runner
    assert "spec.loader.exec_module(module)" in runner
    assert "<securebench-hidden-tests>" in runner
    assert "candidate attempted to exit during import" in runner


def test_build_code_completion_supervisor_requires_success_sentinel():
    supervisor = build_code_completion_supervisor(
        "solution_test.py",
        "candidate.py",
        "securebench/code_completion_success",
    )

    assert "subprocess.run" in supervisor
    assert "hidden tests did not complete" in supervisor
    assert "sentinel.exists()" in supervisor


def test_build_candidate_module_rejects_empty_candidate():
    with pytest.raises(ConfigError, match="empty candidate text"):
        build_candidate_module("")


def test_environment_image_for_task_requires_benchmark_environment_image():
    assert environment_image_for_task(make_task(image="node:22-bookworm")) == "node:22-bookworm"

    task = make_task(image="")
    with pytest.raises(ConfigError, match="environment.image"):
        environment_image_for_task(task)


def test_code_completion_verifier_runs_candidate_in_benchmark_environment_image():
    sandbox = FakeSandbox(stdout="ok")
    verifier = CodeCompletionVerifier(sandbox_factory=lambda **kwargs: sandbox, timeout_seconds=7)

    result = verifier.verify(make_task(image="node:22-bookworm"), "def add_numbers(a, b):\n    return a + b\n")

    assert sandbox.files["candidate.py"] == "def add_numbers(a, b):\n    return a + b\n"
    assert "TEST_SOURCE =" in sandbox.files["solution_test.py"]
    assert "subprocess.run" in sandbox.files["solution_supervisor.py"]
    assert sandbox.commands == [(("python3", "solution_supervisor.py"), None, 7.0)]
    assert result.status == "passed"
    assert result.passed is True
    assert result.score == 1.0
    assert result.stdout == "ok"
    assert result.metadata["image"] == "node:22-bookworm"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["candidate_file"] == "candidate.py"
    assert result.metadata["supervisor_file"] == "solution_supervisor.py"


def test_code_completion_verifier_reports_failed_tests():
    sandbox = FakeSandbox(exit_code=1, stderr="assertion failed")
    verifier = CodeCompletionVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "def add_numbers(a, b):\n    return a - b\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0
    assert result.stderr == "assertion failed"


def test_code_completion_runner_treats_system_exit_as_failure(tmp_path):
    task = make_task(tests={"source": "inline", "code": "assert True\n"})
    candidate = tmp_path / "candidate.py"
    runner = tmp_path / "solution_test.py"
    sentinel = tmp_path / "success"
    candidate.write_text("import sys\nsys.exit(0)\n")
    runner.write_text(build_code_completion_runner(task))

    import subprocess

    result = subprocess.run(
        ["python3", str(runner), str(candidate), str(sentinel)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "candidate attempted to exit during import" in result.stderr
    assert not sentinel.exists()


def test_code_completion_supervisor_treats_os_exit_as_failure(tmp_path):
    task = make_task(tests={"source": "inline", "code": "assert True\n"})
    candidate = tmp_path / "candidate.py"
    runner = tmp_path / "solution_test.py"
    supervisor = tmp_path / "solution_supervisor.py"
    sentinel = tmp_path / "success"
    candidate.write_text("import os\nos._exit(0)\n")
    runner.write_text(build_code_completion_runner(task))
    supervisor.write_text(
        build_code_completion_supervisor(
            str(runner),
            str(candidate),
            str(sentinel),
        )
    )

    import subprocess

    result = subprocess.run(
        ["python3", str(supervisor)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "candidate attempted to terminate process with os._exit(0)" in result.stderr
    assert not sentinel.exists()


def test_candidate_file_dunder_file_does_not_expose_hidden_tests(tmp_path):
    task = make_task(
        tests={
            "source": "inline",
            "code": "assert 'add_numbers(2, 3)' not in leaked_file_text\n",
        }
    )
    candidate = tmp_path / "candidate.py"
    runner = tmp_path / "solution_test.py"
    sentinel = tmp_path / "success"
    candidate.write_text("leaked_file_text = open(__file__).read()\n")
    runner.write_text(build_code_completion_runner(task))

    import subprocess

    result = subprocess.run(
        ["python3", str(runner), str(candidate), str(sentinel)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert sentinel.exists()


def test_code_completion_runner_restores_import_time_builtin_monkeypatch(tmp_path):
    task = make_task(
        tests={
            "source": "inline",
            "code": "assert len([1, 2, 3]) == 3\nassert add_numbers(2, 3) == 5\n",
        }
    )
    candidate = tmp_path / "candidate.py"
    runner = tmp_path / "solution_test.py"
    sentinel = tmp_path / "success"
    candidate.write_text(
        "import builtins\n"
        "builtins.len = lambda value: 999\n"
        "def add_numbers(a, b):\n"
        "    return a + b\n"
    )
    runner.write_text(build_code_completion_runner(task))

    import subprocess

    result = subprocess.run(
        ["python3", str(runner), str(candidate), str(sentinel)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert sentinel.exists()
