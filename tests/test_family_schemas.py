import pytest

from securebench.benchmark_compiler import compile_task_row
from securebench.benchmark_pack import BenchmarkPackManifest, BenchmarkTaskRow
from securebench.errors import ConfigError
from securebench.families import validate_task_row_family


def manifest():
    return BenchmarkPackManifest(id="pack", version=1)


def row_for(family, *, input=None, eval=None):
    return BenchmarkTaskRow(
        id=f"{family}-1",
        family=family,
        input={} if input is None else input,
        eval={} if eval is None else eval,
    )


@pytest.mark.parametrize(
    "row",
    [
        row_for(
            "multiple_choice",
            input={"question": "2 + 2?", "choices": ["1", "2", "4"]},
            eval={"answer": 2},
        ),
        row_for(
            "short_answer",
            input={"question": "Name a primary color.", "answer_format": "lowercase"},
            eval={"accepted_answers": ["red", "blue"], "tolerance": 0},
        ),
        row_for(
            "free_response",
            input={"prompt": "Explain the tradeoff.", "context": {"domain": "security"}},
            eval={"rubric": {"criteria": ["correctness"]}, "reference_answer": "A good answer..."},
        ),
        row_for(
            "code_generation",
            input={
                "prompt": "Write add(a, b).",
                "language": "python",
                "starter_code": "def add(a, b):\n",
            },
            eval={
                "tests": {"source": "inline", "code": "assert candidate(2, 3) == 5"},
                "reference_solution": "def add(a, b): return a + b",
            },
        ),
        row_for(
            "repo_patch",
            input={
                "repo": "repo/",
                "base_commit": "abc123",
                "instructions": "Fix the failing test.",
                "hints": "Look at parser.py",
            },
            eval={"tests": {"path": "tests/test_parser.py"}, "gold_patch": "diff --git ..."},
        ),
    ],
)
def test_active_family_valid_rows_pass_schema_validation(row):
    validate_task_row_family(row)


@pytest.mark.parametrize(
    "row, match",
    [
        (
            row_for("multiple_choice", input={"choices": ["A"]}, eval={"answer": "A"}),
            "input.question is required",
        ),
        (
            row_for("short_answer", input={"question": "Q"}, eval={}),
            "eval.accepted_answers is required",
        ),
        (
            row_for("free_response", input={"prompt": "Q"}, eval={}),
            "eval.rubric is required",
        ),
        (
            row_for("code_generation", input={"prompt": "Q"}, eval={}),
            "eval.tests is required",
        ),
        (
            row_for(
                "repo_patch",
                input={"repo": "repo/", "instructions": "Fix"},
                eval={"tests": {}},
            ),
            "input.base_commit is required",
        ),
    ],
)
def test_active_family_missing_required_fields_raise(row, match):
    with pytest.raises(ConfigError, match=match):
        validate_task_row_family(row)


@pytest.mark.parametrize(
    "row, match",
    [
        (
            row_for("multiple_choice", input={"question": "Q", "choices": ["A", 2]}, eval={"answer": "A"}),
            "input.choices must contain only non-empty strings",
        ),
        (
            row_for(
                "short_answer",
                input={"question": "Q"},
                eval={"accepted_answers": ["42"], "tolerance": True},
            ),
            "eval.tolerance must be a non-negative number",
        ),
        (
            row_for(
                "short_answer",
                input={"question": "Q"},
                eval={"accepted_answers": ["42"], "tolerance": -1},
            ),
            "eval.tolerance must be a non-negative number",
        ),
        (
            row_for("free_response", input={"prompt": "Q", "context": []}, eval={"rubric": "Grade it"}),
            "input.context must be a non-empty string or object",
        ),
        (
            row_for("code_generation", input={"prompt": "Q"}, eval={"tests": "assert True"}),
            "eval.tests must be an object",
        ),
        (
            row_for(
                "repo_patch",
                input={"repo": "repo/", "base_commit": "abc", "instructions": ""},
                eval={"tests": {}},
            ),
            "input.instructions must be a non-empty string",
        ),
    ],
)
def test_active_family_malformed_fields_raise(row, match):
    with pytest.raises(ConfigError, match=match):
        validate_task_row_family(row)


@pytest.mark.parametrize(
    "row, match",
    [
        (
            row_for(
                "multiple_choice",
                input={"question": "Q", "choices": ["A"], "extra": "no"},
                eval={"answer": "A"},
            ),
            "input has unknown field",
        ),
        (
            row_for(
                "code_generation",
                input={"prompt": "Q"},
                eval={"tests": {}, "timeout_seconds": 30},
            ),
            "eval has unknown field",
        ),
    ],
)
def test_active_family_unknown_input_or_eval_keys_raise(row, match):
    with pytest.raises(ConfigError, match=match):
        validate_task_row_family(row)


def test_unknown_or_deferred_family_rows_do_not_fail_schema_validation():
    validate_task_row_family(
        row_for(
            "terminal_task",
            input={"arbitrary": []},
            eval={"private": object()},
        )
    )
    validate_task_row_family(
        row_for(
            "custom_family",
            input={"whatever": {"shape": "later"}},
            eval={"secret": True},
        )
    )


def test_reference_solution_is_accepted_and_hidden_after_compilation():
    task = compile_task_row(
        row_for(
            "code_generation",
            input={"prompt": "Write add(a, b)."},
            eval={
                "tests": {"source": "inline", "code": "assert candidate(2, 3) == 5"},
                "reference_solution": "def add(a, b): return a + b",
            },
        ),
        manifest=manifest(),
    )

    assert task.evaluation_payload()["tests"] == {
        "source": "inline",
        "code": "assert candidate(2, 3) == 5",
    }
    assert task.hidden_payload()["reference_solution"] == "def add(a, b): return a + b"
    assert "reference_solution" not in task.agent_payload()


def test_canonical_solution_remains_accepted_and_hidden_after_compilation():
    task = compile_task_row(
        row_for(
            "code_generation",
            input={"prompt": "Write add(a, b)."},
            eval={
                "tests": {"source": "inline", "code": "assert candidate(2, 3) == 5"},
                "canonical_solution": "def add(a, b): return a + b",
            },
        ),
        manifest=manifest(),
    )

    assert task.hidden_payload()["canonical_solution"] == "def add(a, b): return a + b"
    assert "canonical_solution" not in task.agent_payload()


def test_code_generation_timeout_seconds_is_rejected_in_eval():
    with pytest.raises(ConfigError, match="eval has unknown field"):
        compile_task_row(
            row_for(
                "code_generation",
                input={"prompt": "Write add(a, b)."},
                eval={"tests": {}, "timeout_seconds": 30},
            ),
            manifest=manifest(),
        )


def test_compiled_active_family_rows_keep_expected_resource_visibility():
    task = compile_task_row(
        row_for(
            "repo_patch",
            input={
                "repo": "repo/",
                "base_commit": "abc123",
                "instructions": "Fix the bug.",
            },
            eval={"tests": {"path": "tests/test_bug.py"}, "gold_patch": "diff --git ..."},
        ),
        manifest=manifest(),
    )

    assert task.agent_payload() == {
        "repo": "repo/",
        "base_commit": "abc123",
        "instructions": "Fix the bug.",
    }
    assert task.evaluation_payload()["tests"] == {"path": "tests/test_bug.py"}
    assert task.hidden_payload()["gold_patch"] == "diff --git ..."
