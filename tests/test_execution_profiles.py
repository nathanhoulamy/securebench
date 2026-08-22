from dataclasses import replace

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.errors import ConfigError
from securebench.execution_profiles import (
    MAX_FILE_BUNDLE_BYTES,
    MAX_FILESYSTEM_OVERLAY_CHANGED_BYTES,
    MAX_FILESYSTEM_OVERLAY_CHANGED_PATHS,
    MAX_GIT_CHANGED_BYTES,
    MAX_PASSIVE_ARTIFACT_BYTES_PER_CHECK,
    execution_profile,
    validate_executable_task,
    validate_task_components,
)
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
            "max_changed_paths": 4,
            "max_changed_bytes": 4096,
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


def test_overlay_static_contract_can_be_validated_only_by_the_internal_gate():
    validate_task_components(_unsupported_filesystem_overlay(task()))


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

    case_aliased_entry = candidate.files[0].model_copy(
        update={"path": "/App/result.ics"}
    )
    case_aliased_candidate = candidate.model_copy(update={"files": (case_aliased_entry,)})
    case_aliased_verification = compiled.verification.model_copy(
        update={"candidate": case_aliased_candidate}
    )
    case_aliased = compiled.__class__(
        **{**compiled.__dict__, "verification": case_aliased_verification}
    )

    with pytest.raises(ConfigError, match="requires file_bundle entries under"):
        validate_executable_task(case_aliased)


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


def test_current_backend_rejects_portable_aliases_of_framework_paths():
    compiled = task()
    candidate = compiled.verification.candidate
    aliased_entry = candidate.files[0].model_copy(
        update={"path": "/app/SecureBench/public/result.ics"}
    )
    aliased_candidate = candidate.model_copy(update={"files": (aliased_entry,)})
    aliased_verification = compiled.verification.model_copy(
        update={"candidate": aliased_candidate}
    )
    aliased = compiled.__class__(
        **{**compiled.__dict__, "verification": aliased_verification}
    )

    with pytest.raises(ConfigError, match="framework materialization root"):
        validate_executable_task(aliased)

    aliased_asset = compiled.assets[0].model_copy(
        update={"mount": "/app/SECUREBENCH/evaluation_inputs/public.ics"}
    )
    mounted = compiled.__class__(**{**compiled.__dict__, "assets": (aliased_asset,)})

    with pytest.raises(ConfigError, match="framework materialization root"):
        validate_executable_task(mounted)


def test_current_backend_rejects_unknown_parser_before_agent_launch():
    compiled = task()
    check = compiled.verification.checks[0]
    artifact = check.artifacts[0].model_copy(update={"parser": "securebench.unknown/v1"})
    changed_check = check.model_copy(update={"artifacts": (artifact,)})
    verification = compiled.verification.model_copy(update={"checks": (changed_check,)})
    changed = compiled.__class__(**{**compiled.__dict__, "verification": verification})

    with pytest.raises(ConfigError, match="unknown parser profile"):
        validate_executable_task(changed)


def test_current_backend_rejects_candidate_bounds_above_its_capacity():
    compiled = task()
    bundle = compiled.verification.candidate.model_copy(
        update={"max_total_bytes": MAX_FILE_BUNDLE_BYTES + 1}
    )
    bundle_verification = compiled.verification.model_copy(update={"candidate": bundle})
    oversized_bundle = compiled.__class__(
        **{**compiled.__dict__, "verification": bundle_verification}
    )

    with pytest.raises(ConfigError, match="file_bundle candidate bounds"):
        validate_executable_task(oversized_bundle)

    git_task = _unsupported_git_patch(compiled)
    git_candidate = git_task.verification.candidate.model_copy(
        update={"max_changed_bytes": MAX_GIT_CHANGED_BYTES + 1}
    )
    git_verification = git_task.verification.model_copy(update={"candidate": git_candidate})
    oversized_git = git_task.__class__(
        **{**git_task.__dict__, "verification": git_verification}
    )

    with pytest.raises(ConfigError, match="git_patch candidate bounds"):
        validate_executable_task(oversized_git)


@pytest.mark.parametrize(
    "updates",
    [
        {"max_changed_paths": MAX_FILESYSTEM_OVERLAY_CHANGED_PATHS + 1},
        {"max_changed_bytes": MAX_FILESYSTEM_OVERLAY_CHANGED_BYTES + 1},
    ],
)
def test_overlay_bounds_fail_before_the_non_executable_gate(updates):
    compiled = _unsupported_filesystem_overlay(task())
    candidate = compiled.verification.candidate.model_copy(update=updates)
    verification = compiled.verification.model_copy(update={"candidate": candidate})
    changed = compiled.__class__(
        **{**compiled.__dict__, "verification": verification}
    )

    with pytest.raises(ConfigError, match="planned backend capacity"):
        validate_executable_task(changed)


def test_current_backend_rejects_passive_artifact_bounds_above_its_capacity():
    compiled = task()
    check = compiled.verification.checks[0]
    artifact = check.artifacts[0]
    limits = artifact.limits.model_copy(
        update={"max_bytes": MAX_PASSIVE_ARTIFACT_BYTES_PER_CHECK + 1}
    )
    changed_artifact = artifact.model_copy(update={"limits": limits})
    changed_check = check.model_copy(update={"artifacts": (changed_artifact,)})
    verification = compiled.verification.model_copy(update={"checks": (changed_check,)})
    changed = compiled.__class__(**{**compiled.__dict__, "verification": verification})

    with pytest.raises(ConfigError, match="passive backend capacity"):
        validate_executable_task(changed)
