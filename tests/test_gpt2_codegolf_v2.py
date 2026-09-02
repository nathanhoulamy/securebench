from __future__ import annotations

import base64
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ProtocolCheck
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/gpt2-codegolf"
IMAGE = (
    "alexgshaw/gpt2-codegolf@"
    "sha256:537e7bd26b02db5c761230515fa09dc05f89403c6737fbdae4b5793ebc2c7066"
)
ADAPTER = PACK / "v2" / "evaluation_inputs" / "gpt2-codegolf" / "adapter"
ORACLE = PACK / "v2" / "hidden" / "gpt2-codegolf" / "oracle" / "oracle.py"
REFERENCE = (
    PACK
    / "v2"
    / "hidden"
    / "gpt2-codegolf"
    / "qualification"
    / "reference.c"
)


def compiled_task():
    return load_terminal_task(TASK_ID)


def _observation(stdout: bytes, *, compile_exit: int = 0, run_exit: int = 0):
    encoded = lambda value: base64.b64encode(value).decode("ascii")
    return {
        "compile_exit": compile_exit,
        "compile_stdout_base64": encoded(b""),
        "compile_stderr_base64": encoded(b""),
        "run_exit": run_exit,
        "stdout_base64": encoded(stdout),
        "stderr_base64": encoded(b""),
    }


def _evaluate_all(oracle, outputs: list[bytes]):
    for index, output in enumerate(outputs):
        case = oracle.next_case()
        assert case["type"] == "case"
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": f"evaluation_{index}",
                "observation": _observation(output),
            },
        )


def test_gpt2_row_is_bounded_split_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 4_999
    assert task.verification.candidate.files[0].path == "/app/gpt2.c"
    assert task.verification.candidate.files[0].max_bytes == 4_999
    assert [type(check) for check in task.verification.checks] == [ProtocolCheck]
    protocol = task.verification.checks[0]
    assert protocol.challenge.max_cases == 2
    assert protocol.protocol == "securebench.gpt2-codegolf/v1"
    assert not protocol.trusted_helpers
    assert not protocol.output_artifacts

    adapter_files = {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file()
    }
    assert adapter_files == {"adapter.sh", "adapter.yaml"}


def test_public_adapter_contains_no_oracle_expectations():
    adapter = (ADAPTER / "adapter.sh").read_text()

    assert "WARRANTY OF ANY KIND" not in adapter
    assert "meaning of life" not in adapter
    assert "passed" not in adapter.lower()


def test_oracle_replays_source_case_and_private_fixed_output_guard():
    oracle_module = load_module(ORACLE, "gpt2_codegolf_oracle_cases")
    oracle = oracle_module.Gpt2CodegolfOracle()

    first = oracle.next_case()
    second = oracle.next_case()

    assert base64.b64decode(first["challenge"]["prompt_base64"]) == (
        b'THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT'
    )
    assert base64.b64decode(second["challenge"]["prompt_base64"]) != (
        b'THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT'
    )
    assert oracle.next_case() == {"type": "exhausted"}


def test_oracle_accepts_independent_correct_evidence():
    oracle_module = load_module(ORACLE, "gpt2_codegolf_oracle_pass")
    oracle = oracle_module.Gpt2CodegolfOracle()
    outputs = [expected.encode() for _, expected in oracle_module.CASES]

    _evaluate_all(oracle, outputs)

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is True
    assert verdict["check_outcomes"] == {"gpt2_continuation_behavior": True}


@pytest.mark.parametrize(
    "attack",
    ["wrong_output", "fixed_source_output", "compile_failure", "runtime_failure", "reused_id"],
)
def test_oracle_rejects_behavior_mutants_and_claims(attack):
    oracle_module = load_module(ORACLE, f"gpt2_codegolf_oracle_{attack}")
    oracle = oracle_module.Gpt2CodegolfOracle()
    outputs = [expected.encode() for _, expected in oracle_module.CASES]
    if attack == "wrong_output":
        outputs[0] = b'{"verdict":"passed","score":1}'
    elif attack == "fixed_source_output":
        outputs[1] = outputs[0]

    for index, output in enumerate(outputs):
        case = oracle.next_case()
        observation = _observation(output)
        if attack == "compile_failure" and index == 0:
            observation["compile_exit"] = 1
        if attack == "runtime_failure" and index == 0:
            observation["run_exit"] = 124
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": (
                    "evaluation_0" if attack == "reused_id" else f"evaluation_{index}"
                ),
                "observation": observation,
            },
        )

    assert oracle.verdict()["verdict"]["passed"] is False


@pytest.mark.parametrize("value", ["%%%", base64.b64encode(b"x" * 65_537).decode()])
def test_oracle_rejects_malformed_or_oversized_encoded_output(value):
    oracle_module = load_module(ORACLE, "gpt2_codegolf_oracle_bad_base64")
    oracle = oracle_module.Gpt2CodegolfOracle()
    case = oracle.next_case()
    observation = _observation(b"")
    observation["stdout_base64"] = value

    oracle.evaluate_case(
        case["case_context"],
        {
            "status": "observed",
            "evaluation_id": "evaluation_0",
            "observation": observation,
        },
    )

    assert oracle.verdict()["verdict"]["passed"] is False
    assert oracle.failures == ["invalid_observation"]


@DOCKER_INTEGRATION
def test_reference_passes_real_pinned_evaluations(tmp_path):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "gpt2.c").write_bytes(REFERENCE.read_bytes())

    result, _, _ = verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="gpt2-codegolf-pinned-reference",
    )

    assert result.status == "passed", result
    behavior = result.checks[0]
    assert behavior.cases == 2
    assert len(set(behavior.evidence_digests)) == 2


@DOCKER_INTEGRATION
def test_behavior_mutants_fail_real_pinned_evaluations(tmp_path):
    task = compiled_task()
    mutants = {
        "fixed-output": b'#include <stdio.h>\nint main(){puts("WARRANTY OF ANY KIND, EXPRESS OR IMPLIED");}\n',
        "compile-error": b"this is not C\n",
        "output-flood": b"#include <stdio.h>\nint main(){for(;;)puts(\"x\");}\n",
        "forked-pipe-holder": (
            b"#include <unistd.h>\n"
            b"int main(){if(!fork())for(;;)pause();return 1;}\n"
        ),
    }
    for name, content in mutants.items():
        workspace = tmp_path / name
        workspace.mkdir()
        (workspace / "gpt2.c").write_bytes(content)
        result, _, _ = verify_workspace(
            task,
            workspace,
            tmp_path / f"store-{name}",
            run_seed=f"gpt2-codegolf-{name}-mutant",
        )

        assert result.status == "failed", result
        assert result.infrastructure_error is None, result
