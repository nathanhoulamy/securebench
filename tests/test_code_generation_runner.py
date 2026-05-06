import pytest

from securebench.runners import CodeGenerationRunner
from securebench.runners.code_generation import build_python_test_script
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import MultipleChoiceTask, task_from_spec


class FakeSandbox(Sandbox):
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.files = {}
        self.commands = []
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((tuple(command), workdir, timeout))
        return CommandResult(tuple(command), self.exit_code, self.stdout, self.stderr)

    def write_file(self, path, content):
        self.files[str(path)] = content

    def read_file(self, path):
        return self.files[str(path)]

    def extract_file(self, path):
        return self.files[str(path)].encode()


def make_task():
    return task_from_spec(
        {
            "id": "HumanEval/0",
            "benchmark_id": "humaneval",
            "task_type": "code_generation",
            "resources": {
                "prompt": {"value": "def add(a, b):\n", "visibility": "public"},
                "entry_point": {"value": "add", "visibility": "public"},
                "tests": {
                    "value": "def check(candidate):\n    assert candidate(1, 2) == 3\n",
                    "visibility": "hidden",
                },
            },
        }
    )


def test_build_python_test_script_combines_prompt_candidate_tests_and_check_call():
    script = build_python_test_script(make_task(), "    return a + b\n")

    assert script == (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def check(candidate):\n"
        "    assert candidate(1, 2) == 3\n"
        "\n"
        "check(add)\n"
    )


def test_code_generation_runner_writes_and_runs_hidden_test_script():
    sandbox = FakeSandbox(stdout="ok")
    result = CodeGenerationRunner(sandbox=sandbox, timeout=3).run(make_task(), "    return a + b\n")

    assert sandbox.files["solution_test.py"].endswith("check(add)\n")
    assert sandbox.commands == [(("python", "solution_test.py"), None, 3)]
    assert result.passed is True
    assert result.score == 1.0
    assert result.stdout == "ok"
    assert result.metadata["exit_code"] == 0


def test_code_generation_runner_reports_failure():
    sandbox = FakeSandbox(exit_code=1, stderr="assertion failed")
    result = CodeGenerationRunner(sandbox=sandbox).run(make_task(), "    return a - b\n")

    assert result.passed is False
    assert result.score == 0.0
    assert result.stderr == "assertion failed"


def test_code_generation_runner_requires_code_generation_task():
    task = MultipleChoiceTask(
        id="mmlu/math/test/7",
        benchmark_id="mmlu",
        task_type="multiple_choice",
    )

    with pytest.raises(TypeError, match="CodeGenerationRunner requires CodeGenerationTask"):
        CodeGenerationRunner(sandbox=FakeSandbox()).run(task, "C")
