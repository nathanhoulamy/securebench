import pytest

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import task_from_spec
from securebench.verifiers.code_completion import (
    CodeCompletionVerifier,
    build_code_completion_script,
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


def test_build_code_completion_script_combines_candidate_and_tests_only():
    script = build_code_completion_script(make_task(), "def add_numbers(a, b):\n    return a + b\n")

    assert script == (
        "def add_numbers(a, b):\n"
        "    return a + b\n"
        "\n"
        "def check():\n"
        "    assert add_numbers(2, 3) == 5\n"
        "\n"
        "check()\n"
    )


def test_environment_image_for_task_requires_benchmark_environment_image():
    assert environment_image_for_task(make_task(image="node:22-bookworm")) == "node:22-bookworm"

    task = make_task(image="")
    with pytest.raises(ConfigError, match="environment.image"):
        environment_image_for_task(task)


def test_code_completion_verifier_runs_candidate_in_benchmark_environment_image():
    sandbox = FakeSandbox(stdout="ok")
    verifier = CodeCompletionVerifier(sandbox_factory=lambda **kwargs: sandbox, timeout_seconds=7)

    result = verifier.verify(make_task(image="node:22-bookworm"), "def add_numbers(a, b):\n    return a + b\n")

    assert sandbox.files["solution_test.py"].startswith("def add_numbers")
    assert sandbox.commands == [(("python3", "solution_test.py"), None, 7.0)]
    assert result.status == "passed"
    assert result.passed is True
    assert result.score == 1.0
    assert result.stdout == "ok"
    assert result.metadata["image"] == "node:22-bookworm"
    assert result.metadata["exit_code"] == 0


def test_code_completion_verifier_reports_failed_tests():
    sandbox = FakeSandbox(exit_code=1, stderr="assertion failed")
    verifier = CodeCompletionVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "def add_numbers(a, b):\n    return a - b\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0
    assert result.stderr == "assertion failed"
