import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.errors import ConfigError
from securebench.execution_profiles import execution_profile, validate_executable_task
from securebench.harnesses.shared import task_allowed_domains


def task():
    pack = load_benchmark_pack(
        "benchmarks/terminal-bench/manifest-v2.yaml",
        "benchmarks/terminal-bench/tasks-v2.jsonl",
    )
    return next(compile_benchmark_pack(pack))


def test_strict_profile_is_registered_and_reference_row_is_executable():
    assert execution_profile("strict-split/v1").implemented is True
    validate_executable_task(task())


def test_registered_batched_fallback_is_explicitly_not_implemented():
    compiled = task()
    verification = compiled.verification.model_copy(update={"execution_profile": "batched-split/v1"})

    with pytest.raises(ConfigError, match="registered but not implemented"):
        validate_executable_task(compiled.__class__(**{**compiled.__dict__, "verification": verification}))


def test_unknown_profile_does_not_fall_back_to_another_policy():
    with pytest.raises(ConfigError, match="Unknown verification.execution_profile"):
        execution_profile("custom/v9")


def test_agent_network_none_is_a_hard_ceiling_on_tester_domains():
    compiled = task()
    environment = compiled.environment.model_copy(update={"agent_network": "none"})
    restricted = compiled.__class__(**{**compiled.__dict__, "environment": environment})

    assert task_allowed_domains(restricted, ("example.com",)) == ()


def test_current_capture_backend_rejects_bundle_entries_outside_workdir():
    compiled = task()
    candidate = compiled.verification.candidate
    entry = candidate.files[0].model_copy(update={"path": "/output/result.ics"})
    changed_candidate = candidate.model_copy(update={"files": (entry,)})
    verification = compiled.verification.model_copy(update={"candidate": changed_candidate})
    changed = compiled.__class__(**{**compiled.__dict__, "verification": verification})

    with pytest.raises(ConfigError, match="requires file_bundle entries under"):
        validate_executable_task(changed)
