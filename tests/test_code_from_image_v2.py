from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateCaptureError,
    CandidateStore,
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_production,
)
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.command import CommandHarnessProducer
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from securebench.workspaces.cleanup import remove_untrusted_tree


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/code-from-image"
IMAGE = (
    "alexgshaw/code-from-image@"
    "sha256:2be9cdb746ed18c1b2b1404032efae0b2235a1b8fc479ef17730c95409d89f76"
)
EXPECTED = "bee26a133f103b9ecda444c70ec22cafef6e31a3de7af6d047974dc90ce3defe"
PUBLIC_IMAGE_SHA256 = "f4d0330407b363a9ef03d563e5c2ffd24aa76345f997613741f9fc0935354305"


def compiled_task():
    pack = load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
    return next(task for task in compile_benchmark_pack(pack) if task.id == TASK_ID)


def verify_output(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "unrelated.log").write_text("excluded", encoding="utf-8")
    target = workspace / "output.txt"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    store = CandidateStore(tmp_path / "store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )
    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="code-from-image-qualification",
    )
    return result, candidate, store


def test_code_from_image_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.artifacts[0].parser == "securebench.utf8-text/v1"
    assert not task.verification.resources.runtime
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 4096
    entry = task.verification.candidate.files[0]
    assert entry.id == "output"
    assert entry.path == "/app/output.txt"
    assert entry.max_bytes == 4096

    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml"}


def test_public_image_reproduces_the_source_verifier_output():
    content = (PACK / "docker" / "code-from-image" / "code.png").read_bytes()
    assert hashlib.sha256(content).hexdigest() == PUBLIC_IMAGE_SHA256
    first = hashlib.sha256(content).digest()
    actual = hashlib.sha256(first + first[:10] + b"0000TBENCH-SALT").hexdigest()
    assert actual == EXPECTED


@pytest.mark.parametrize("content", [EXPECTED, f" \n\t{EXPECTED}\r\n "])
def test_reference_output_passes_with_source_strip_semantics(tmp_path, content):
    result, candidate, store = verify_output(tmp_path, content)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["output"]


def test_missing_candidate_is_scored_by_the_oracle():
    result = VerificationEngine().verify_candidate_error(
        compiled_task(),
        code="candidate_capture_rejected",
        message="Candidate capture was rejected",
        run_seed="code-from-image-missing",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "candidate_capture_rejected"
    ]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("bee26a", id="published_prefix_only"),
        pytest.param(EXPECTED[:-1] + "f", id="wrong_digest_nibble"),
        pytest.param(EXPECTED.upper(), id="case_changed"),
        pytest.param(EXPECTED + "\nPASS", id="forged_verdict"),
        pytest.param('{"verdict":"pass"}', id="structured_verdict_claim"),
        pytest.param(EXPECTED + "\x00", id="nul_suffix"),
    ],
)
def test_targeted_mutants_and_candidate_claims_fail(tmp_path, content):
    result, _, _ = verify_output(tmp_path, content)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["incorrect_output"]


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_output(tmp_path, EXPECTED.encode() + b"\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["invalid_utf8"]


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_capture_rejects_malicious_artifact_shapes(tmp_path, attack):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "output.txt"
    if attack == "symlink":
        outside = tmp_path / "outside.txt"
        outside.write_text(EXPECTED, encoding="utf-8")
        target.symlink_to(outside)
    elif attack == "directory":
        target.mkdir()
    else:
        target.write_bytes(b"x" * 4097)

    with pytest.raises(CandidateCaptureError):
        capture_file_bundle(
            HostWorkspaceFilesystem(workspace, guest_root="/app"),
            task.verification.candidate,
            CandidateStore(tmp_path / "store"),
            baseline_digest=task.baseline_digest,
        )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_output(tmp_path, EXPECTED)
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="code-from-image-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for pinned-image qualification",
)
def test_base_image_fails_stopped_candidate_capture(tmp_path):
    task = compiled_task()
    producer = CommandHarnessProducer(
        command=("true",),
        workspace_root=tmp_path / "workspaces",
    )
    production = producer.produce(task)
    try:
        with pytest.raises(CandidateCaptureError):
            capture_production(task, production, CandidateStore(tmp_path / "store"))
    finally:
        remove_untrusted_tree(production.workspace, image=task.environment.image)


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for pinned-image qualification",
)
@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        pytest.param(EXPECTED, "passed", id="reference"),
        pytest.param("bee26a", "failed", id="prefix_mutant"),
        pytest.param(EXPECTED + "\nPASS", "failed", id="forged_verdict"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(tmp_path, content, expected_status):
    task = compiled_task()
    script = (
        "from pathlib import Path;import hashlib;"
        "image=Path('/app/code.png').read_bytes();"
        f"assert len(image)==95041 and hashlib.sha256(image).hexdigest()=='{PUBLIC_IMAGE_SHA256}';"
        f"Path('/app/output.txt').write_text({content!r},encoding='utf-8')"
    )
    producer = CommandHarnessProducer(
        command=("python3", "-c", script),
        workspace_root=tmp_path / "workspaces",
    )
    production = producer.produce(task)
    try:
        store = CandidateStore(tmp_path / "store")
        candidate = capture_production(task, production, store)
        result = VerificationEngine().verify(
            task,
            candidate,
            store,
            run_seed=f"code-from-image-pinned-{expected_status}",
        )
    finally:
        remove_untrusted_tree(production.workspace, image=task.environment.image)

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
