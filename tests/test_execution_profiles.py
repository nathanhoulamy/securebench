from dataclasses import replace

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.errors import ConfigError
from securebench.execution_profiles import execution_profile, validate_executable_task
from securebench.harnesses.shared import run_timeout_seconds, task_allowed_domains
from securebench.schemas.benchmark import (
    ArtifactSource,
    BenchmarkRowV2,
    FilesystemOverlayCandidate,
    GitPatchCandidate,
    VerificationSpec,
)


def task():
    pack = load_benchmark_pack(
        "benchmarks/terminal-bench/manifest-v2.yaml",
        "benchmarks/terminal-bench/tasks-v2.jsonl",
    )
    return next(compile_benchmark_pack(pack))


def test_strict_profile_is_registered_and_reference_row_is_executable():
    assert execution_profile("strict-split/v1").implemented is True
    validate_executable_task(task())


def _unsupported_profile(compiled):
    return _validated_task_variant(compiled, execution_profile="batched-split/v1")


def _unsupported_git_patch(compiled):
    candidate = GitPatchCandidate.model_validate(
        {
            "type": "git_patch",
            "max_patch_bytes": 1024,
            "max_changed_files": 4,
            "max_changed_bytes": 4096,
        }
    )
    return _validated_task_variant(
        compiled,
        candidate=candidate,
        artifact_source=ArtifactSource(path="meeting_scheduled.ics"),
        family="repo_patch",
        input={
            "repo": "example/repository",
            "base_commit": "a" * 40,
            "instructions": "Update the repository.",
        },
    )


def _unsupported_filesystem_overlay(compiled):
    candidate = FilesystemOverlayCandidate.model_validate(
        {
            "type": "filesystem_overlay",
            "include_roots": ["/app"],
            "max_files": 4,
            "max_total_bytes": 4096,
        }
    )
    return _validated_task_variant(
        compiled,
        candidate=candidate,
        artifact_source=ArtifactSource(path="/app/meeting_scheduled.ics"),
    )


def _validated_task_variant(
    compiled,
    *,
    execution_profile=None,
    candidate=None,
    artifact_source=None,
    family=None,
    input=None,
):
    check = compiled.verification.checks[0]
    if artifact_source is not None:
        artifact = check.artifacts[0].model_copy(update={"source": artifact_source})
        check = check.model_copy(update={"artifacts": (artifact,)})
    verification_data = compiled.verification.model_dump()
    verification_data["checks"] = [check.model_dump()]
    if execution_profile is not None:
        verification_data["execution_profile"] = execution_profile
    if candidate is not None:
        verification_data["candidate"] = candidate.model_dump()
    verification = VerificationSpec.model_validate(verification_data)
    row = BenchmarkRowV2.model_validate(
        {
            "id": compiled.id,
            "family": family or compiled.family,
            "input": compiled.input if input is None else input,
            "assets": [asset.model_dump() for asset in compiled.assets],
            "environment": compiled.environment.model_dump(),
            "verification": verification.model_dump(),
            "metadata": compiled.metadata,
        }
    )
    return replace(
        compiled,
        family=row.family,
        input=dict(row.input),
        verification=row.verification,
    )


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        (_unsupported_profile, "registered but not implemented"),
        (_unsupported_filesystem_overlay, "filesystem_overlay.*schema-valid but not executable"),
    ],
    ids=["batched-profile", "filesystem-overlay"],
)
def test_executable_capability_matrix_rejects_unsupported_schema_branches(variant, message):
    compiled = variant(task())

    with pytest.raises(ConfigError, match=message):
        validate_executable_task(compiled)


def test_git_patch_candidate_is_executable_for_repo_patch_rows():
    validate_executable_task(_unsupported_git_patch(task()))


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


def test_harness_timeout_is_an_upper_bound_on_row_timeout():
    compiled = task()

    assert run_timeout_seconds(compiled, fallback_timeout=60) == 60
    assert run_timeout_seconds(compiled, fallback_timeout=3600) == 1200
    assert run_timeout_seconds(compiled, context_timeout=15, fallback_timeout=60) == 15

    for invalid in (float("inf"), 10**400):
        with pytest.raises(ConfigError, match="positive number"):
            run_timeout_seconds(compiled, context_timeout=invalid)


def test_current_backend_rejects_writable_or_candidate_overlapping_assets():
    compiled = task()
    writable_asset = compiled.assets[0].model_copy(update={"read_only": False})
    writable = compiled.__class__(**{**compiled.__dict__, "assets": (writable_asset,)})
    with pytest.raises(ConfigError, match="read-only public assets"):
        validate_executable_task(writable)

    candidate_path = compiled.verification.candidate.files[0].path
    overlapping_asset = compiled.assets[0].model_copy(update={"mount": candidate_path})
    overlapping = compiled.__class__(**{**compiled.__dict__, "assets": (overlapping_asset,)})
    with pytest.raises(ConfigError, match="overlaps candidate entry"):
        validate_executable_task(overlapping)


def test_current_backend_rejects_unknown_parser_before_agent_launch():
    compiled = task()
    check = compiled.verification.checks[0]
    artifact = check.artifacts[0].model_copy(update={"parser": "securebench.unknown/v1"})
    changed_check = check.model_copy(update={"artifacts": (artifact,)})
    verification = compiled.verification.model_copy(update={"checks": (changed_check,)})
    changed = compiled.__class__(**{**compiled.__dict__, "verification": verification})

    with pytest.raises(ConfigError, match="unknown parser profile"):
        validate_executable_task(changed)
