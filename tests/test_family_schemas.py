import pytest

from securebench.benchmark_pack import BenchmarkRow
from securebench.errors import ConfigError
from securebench.families import validate_benchmark_row_family


def row_for(family, *, input=None, eval=None):
    return BenchmarkRow(
        id=f"{family}-1",
        family=family,
        input={} if input is None else input,
        eval={} if eval is None else eval,
    )


@pytest.mark.parametrize(
    "row",
    [
        row_for(
            "repo_patch",
            input={
                "repo": "repo/",
                "base_commit": "abc123",
                "instructions": "Fix the failing test.",
                "hints": "Look at parser.py",
            },
            eval={
                "candidate_policy": {
                    "allow_paths": ["src/"],
                    "allow_sensitive_paths": ["tests/fixtures/"],
                    "patch_preserved_paths": ["tests/public_test.py"],
                },
                "tests": {
                    "source": "command",
                    "command": ["python", "-m", "pytest", "tests/test_parser.py"],
                },
                "gold_patch": "diff --git ...",
            },
        ),
        row_for(
            "terminal_task",
            input={"instructions": "Create output.txt", "context": {"cwd": "/workspace"}},
            eval={
                "checker": {
                    "source": "pytest",
                    "path": "checks",
                    "timeout_seconds": 30,
                },
                "expected_state": {"file": "output.txt"},
            },
        ),
    ],
)
def test_supported_family_valid_rows_pass_schema_validation(row):
    validate_benchmark_row_family(row)


@pytest.mark.parametrize(
    "row, match",
    [
        (
            row_for(
                "repo_patch",
                input={"repo": "repo/", "instructions": "Fix"},
                eval={"tests": {"source": "command", "command": ["pytest", "-q"]}},
            ),
            "input.base_commit is required",
        ),
        (
            row_for("terminal_task", input={}, eval={"checker": {"source": "pytest", "path": "checks"}}),
            "input.instructions is required",
        ),
        (
            row_for("unsupported_family", input={"question": "Q"}, eval={"answer": "A"}),
            "Unknown benchmark family",
        ),
    ],
)
def test_supported_family_missing_required_fields_raise(row, match):
    with pytest.raises(ConfigError, match=match):
        validate_benchmark_row_family(row)


@pytest.mark.parametrize(
    "row, match",
    [
        (
            row_for(
                "repo_patch",
                input={"repo": "repo/", "base_commit": "abc", "instructions": ""},
                eval={"tests": {"source": "command", "command": ["pytest", "-q"]}},
            ),
            "input.instructions must be a non-empty string",
        ),
        (
            row_for(
                "repo_patch",
                input={"repo": "repo/", "base_commit": "abc", "instructions": "Fix"},
                eval={
                    "candidate_policy": {"patch_preserved_paths": [""]},
                    "tests": {"source": "command", "command": ["pytest", "-q"]},
                },
            ),
            "eval.candidate_policy.patch_preserved_paths must be a string array",
        ),
        (
            row_for(
                "repo_patch",
                input={"repo": "repo/", "base_commit": "abc", "instructions": "Fix"},
                eval={"tests": {"source": "command", "command": "pytest -q"}},
            ),
            "eval.tests.command must be a non-empty string array",
        ),
        (
            row_for("terminal_task", input={"instructions": "Do it"}, eval={"checker": {"source": "pytest", "path": ""}}),
            "eval.checker.path must be a non-empty string",
        ),
        (
            row_for(
                "terminal_task",
                input={"instructions": "Do it"},
                eval={"checker": {"source": "pytest", "path": "checks", "timeout_seconds": 0}},
            ),
            "eval.checker.timeout_seconds must be a positive number",
        ),
    ],
)
def test_supported_family_malformed_fields_raise(row, match):
    with pytest.raises(ConfigError, match=match):
        validate_benchmark_row_family(row)


@pytest.mark.parametrize(
    "row, match",
    [
        (
            row_for(
                "terminal_task",
                input={"instructions": "Do it", "extra": "no"},
                eval={"checker": {"source": "pytest", "path": "checks"}},
            ),
            "input has unknown field",
        ),
        (
            row_for(
                "repo_patch",
                input={"repo": "repo/", "base_commit": "abc", "instructions": "Fix"},
                eval={
                    "tests": {
                        "source": "command",
                        "command": ["pytest", "-q"],
                        "candidate_policy": {"allow_paths": ["src/"]},
                    }
                },
            ),
            "eval.tests has unknown field",
        ),
    ],
)
def test_supported_family_unknown_input_or_eval_keys_raise(row, match):
    with pytest.raises(ConfigError, match=match):
        validate_benchmark_row_family(row)
