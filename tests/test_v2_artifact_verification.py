from __future__ import annotations

import io
import json
import math
import os
import shutil
import struct
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateStore,
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_git_patch_workspace,
    capture_filesystem_overlay,
    OverlayReplayBackend,
    OverlayScanLimits,
    scan_overlay_roots,
)
from securebench.schemas.benchmark import ArtifactSpec, FileBundleCandidate
from securebench.verification import (
    VerificationEngine,
    OracleSession,
    OracleVerdict,
)
from securebench.verification.models import (
    CandidateObservationError,
    ParserRejected,
    VerificationInfrastructureError,
)
from securebench.verification.oracle import OracleProcessSession
from securebench.verification.artifacts import _candidate_artifact
from securebench.verification.json_data import json_digest
from securebench.verification.parsers import default_parser_registry


DIGEST = "sha256:" + "c" * 64


def npy_float_file(
    values,
    *,
    descr="<f8",
    shape=None,
    version=(1, 0),
    header_source=None,
    trailing=b"",
):
    shape = (len(values),) if shape is None else shape
    if header_source is None:
        header_source = repr(
            {"descr": descr, "fortran_order": False, "shape": shape}
        )
    length_size = 2 if version == (1, 0) else 4
    encoding = "utf-8" if version == (3, 0) else "latin-1"
    preamble_size = 8 + length_size
    encoded_header = header_source.encode(encoding)
    padding = (-(preamble_size + len(encoded_header) + 1)) % 64
    header = encoded_header + b" " * padding + b"\n"
    byte_order = ">" if descr.startswith(">") else "<"
    item_size = int(descr.lstrip("<>=")[1:])
    if item_size == 16:
        payload = b"".join(_x87_float(value, byte_order) for value in values)
    else:
        code = {2: "e", 4: "f", 8: "d"}[item_size]
        payload = b"".join(struct.pack(byte_order + code, value) for value in values)
    return (
        b"\x93NUMPY"
        + bytes(version)
        + len(header).to_bytes(length_size, "little")
        + header
        + payload
        + trailing
    )


def _x87_float(value, byte_order):
    if value == 0.0:
        exponent = 0
        significand = 0
    else:
        fraction, power = math.frexp(abs(value))
        exponent = power - 1 + 16383
        significand = round(fraction * 2 * (1 << 63))
    sign_and_exponent = exponent | (0x8000 if value < 0 else 0)
    if byte_order == "<":
        return (
            significand.to_bytes(8, "little")
            + sign_and_exponent.to_bytes(2, "little")
            + b"\x00" * 6
        )
    return (
        sign_and_exponent.to_bytes(2, "big")
        + significand.to_bytes(8, "big")
        + b"\x00" * 6
    )


class RecordingOracle(OracleSession):
    def __init__(self) -> None:
        self.initialized = False
        self.evidence = []
        self.closed = False

    def initialize(self, task, *, run_seed):
        self.initialized = True
        self.seed = run_seed

    def evaluate_artifact(self, evidence):
        self.evidence.append(evidence)

    def finalize(self):
        passed = bool(self.evidence) and all(item.status == "observed" for item in self.evidence)
        return OracleVerdict(
            passed=passed,
            score=1.0 if passed else 0.0,
            public_diagnostics={"message": "accepted" if passed else "rejected"},
            check_outcomes={"result_artifact": passed},
        )

    def close(self):
        self.closed = True


class FixedVerdictOracle(RecordingOracle):
    def __init__(self, verdict):
        super().__init__()
        self.verdict = verdict

    def finalize(self):
        return self.verdict


def write_artifact_pack(
    root: Path,
    *,
    parser="securebench.strict-json/v1",
    overlay: bool = False,
):
    (root / "assets").mkdir(parents=True)
    (root / "evaluation_inputs").mkdir()
    (root / "hidden" / "task" / "oracle").mkdir(parents=True)
    manifest = root / "manifest.yaml"
    manifest.write_text(
        f"""
schema_version: "2.0"
id: artifact-pack
defaults:
  family: terminal_task
  environment:
    image: {DIGEST}
    workdir: /app
    timeout_seconds: 30
    agent_network: none
resource_roots:
  public: assets/
  runtime: evaluation_inputs/
  host: hidden/
""".lstrip()
    )
    row = {
        "id": "artifact/task",
        "input": {"instructions": "Write /app/result.json."},
        "verification": {
            "execution_profile": "strict-split/v1",
            "candidate": ({
                "type": "filesystem_overlay",
                "include_roots": ["/app"],
                "max_changed_paths": 10,
                "max_changed_bytes": 1024,
                "allow_internal_symlinks": False,
            } if overlay else {
                "type": "file_bundle",
                "max_total_files": 1,
                "max_total_bytes": 1024,
                "files": [
                    {
                        "id": "result",
                        "path": "/app/result.json",
                        "kind": "regular_file",
                        "max_bytes": 1024,
                    }
                ],
            }),
            "resources": {
                "host": {"oracle": {"path": "task/oracle"}},
            },
            "checks": [
                {
                    "id": "result_artifact",
                    "type": "artifact",
                    "artifacts": [
                        {
                            "id": "result",
                            "source": ({"path": "/app/result.json"} if overlay else {"entry": "result"}),
                            "parser": parser,
                            "limits": {"max_bytes": 1024},
                        }
                    ],
                }
            ],
            "oracle": "host.oracle",
        },
    }
    tasks = root / "tasks.jsonl"
    tasks.write_text(json.dumps(row) + "\n")
    pack = load_benchmark_pack(manifest, tasks)
    return next(compile_benchmark_pack(pack))


class FakeOverlayWorkspace:
    def __init__(
        self,
        root: Path,
        include_roots: tuple[str, ...],
        events: list[str],
        *,
        fail_cleanup: bool = False,
    ):
        self.include_roots = include_roots
        self.root = root
        self.roots = {
            guest: root / f"root-{index}"
            for index, guest in enumerate(include_roots)
        }
        for path in self.roots.values():
            path.mkdir(parents=True)
        self.events = events
        self.fail_cleanup = fail_cleanup

    def host_roots(self):
        return self.roots

    def close(self):
        self.events.append("closed")
        shutil.rmtree(self.root)
        if self.fail_cleanup:
            raise RuntimeError("synthetic overlay cleanup failure")


@pytest.mark.parametrize("fail_cleanup", [False, True])
def test_overlay_artifact_uses_fresh_absolute_path_mapping_and_cleanup(
    tmp_path, monkeypatch, fail_cleanup
):
    import securebench.candidates.overlay as overlay_module

    monkeypatch.setattr(overlay_module, "_has_extended_metadata", lambda _path: False)
    task = write_artifact_pack(tmp_path / "pack", overlay=True)
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (baseline / "result.json").write_text('{"answer": 0}')
    (final / "result.json").write_text('{"answer": 42}')
    limits = OverlayScanLimits(required_uid=os.getuid(), required_gid=os.getgid())
    store = CandidateStore(tmp_path / "store")
    candidate = capture_filesystem_overlay(
        {"/app": baseline},
        {"/app": final},
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
        scan_limits=limits,
    )
    events: list[str] = []
    created: list[FakeOverlayWorkspace] = []

    def workspace_factory(*, include_roots, **_kwargs):
        workspace = FakeOverlayWorkspace(
            tmp_path / f"evaluation-{len(created)}",
            include_roots,
            events,
            fail_cleanup=fail_cleanup,
        )
        created.append(workspace)
        return workspace

    def materializer(_image, workspace, *, scan_limits):
        shutil.copy2(baseline / "result.json", workspace.roots["/app"] / "result.json")
        return scan_overlay_roots(
            workspace.include_roots,
            workspace.host_roots(),
            limits=scan_limits,
            label="baseline",
        )

    backend = OverlayReplayBackend(
        storage_root=tmp_path / "storage",
        capacity_bytes=2 * 1024 * 1024 * 1024,
        scan_limits=limits,
        workspace_factory=workspace_factory,
        materializer=materializer,
    )
    oracle = RecordingOracle()

    result = VerificationEngine(overlay_backend=backend).verify(
        task, candidate, store, run_seed="overlay-artifact", oracle=oracle
    )

    if fail_cleanup:
        assert result.status == "infrastructure_error"
        assert result.infrastructure_error["code"] == "artifact_cleanup_failed"
    else:
        assert result.status == "passed"
        assert oracle.evidence[0].parsed_value == {"answer": 42}
    assert len(created) == 1
    assert events == ["closed"]
    assert not created[0].root.exists()


def capture_result(tmp_path: Path, task, content: bytes):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.json").write_bytes(content)
    store = CandidateStore(tmp_path / "candidate-store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )
    return store, candidate


def test_file_bundle_tree_evidence_uses_its_own_digest_and_requires_all_blobs(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "tree").mkdir(parents=True)
    (workspace / "tree" / "answer.txt").write_text("42")
    spec = FileBundleCandidate.model_validate(
        {
            "type": "file_bundle",
            "max_total_files": 2,
            "max_total_bytes": 16,
            "files": [
                {
                    "id": "tree",
                    "path": "/app/tree",
                    "kind": "directory_tree",
                    "max_files": 2,
                    "max_total_bytes": 16,
                }
            ],
        }
    )
    store = CandidateStore(tmp_path / "store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        spec,
        store,
        baseline_digest=DIGEST,
    )
    artifact = ArtifactSpec.model_validate(
        {
            "id": "tree",
            "source": {"entry": "tree"},
            "parser": "securebench.tree-manifest/v1",
            "limits": {"max_files": 2, "max_total_bytes": 16},
        }
    )

    kind, digest, size, tree = _candidate_artifact(
        object(), candidate, store, artifact
    )

    assert kind == "directory_tree"
    assert digest == json_digest(tree)
    assert digest != candidate.digest
    assert size == 2

    manifest = store.load_candidate(candidate.digest)
    blob = manifest.payload["entries"][0]["nodes"][0]["blob"]
    hexadecimal = blob.removeprefix("sha256:")
    (store.blobs_root / hexadecimal[:2] / hexadecimal).unlink()
    with pytest.raises(VerificationInfrastructureError, match="blob is invalid"):
        _candidate_artifact(object(), candidate, store, artifact)


@pytest.mark.parametrize(
    ("subpath", "maximum", "expected_code"),
    [
        ("summary.csv", 64, None),
        ("missing.csv", 64, "artifact_missing"),
        ("nested", 64, "artifact_wrong_type"),
        ("summary.csv", 4, "artifact_too_large"),
        ("summary-link.csv", 64, "artifact_wrong_type"),
    ],
)
def test_file_bundle_tree_subpath_selects_only_a_bounded_regular_file(
    tmp_path, subpath, maximum, expected_code
):
    from types import SimpleNamespace

    workspace = tmp_path / "workspace"
    tree = workspace / "tree"
    (tree / "nested").mkdir(parents=True)
    (tree / "summary.csv").write_text("name,value\ntotal,42\n")
    (tree / "unrelated.bin").write_bytes(b"untrusted")
    (tree / "summary-link.csv").symlink_to("summary.csv")
    spec = FileBundleCandidate.model_validate(
        {
            "type": "file_bundle",
            "max_total_files": 8,
            "max_total_bytes": 1024,
            "files": [
                {
                    "id": "tree",
                    "path": "/app/tree",
                    "kind": "directory_tree",
                    "max_files": 8,
                    "max_total_bytes": 1024,
                    "allow_internal_symlinks": True,
                }
            ],
        }
    )
    store = CandidateStore(tmp_path / "store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        spec,
        store,
        baseline_digest=DIGEST,
    )
    artifact = ArtifactSpec.model_validate(
        {
            "id": "summary",
            "source": {"entry": "tree", "subpath": subpath},
            "parser": "securebench.utf8-text/v1",
            "limits": {"max_bytes": maximum},
        }
    )
    task = SimpleNamespace(verification=SimpleNamespace(candidate=spec))

    if expected_code is not None:
        with pytest.raises(CandidateObservationError) as raised:
            _candidate_artifact(task, candidate, store, artifact)
        assert raised.value.code == expected_code
        return

    kind, digest, size, content = _candidate_artifact(task, candidate, store, artifact)
    assert kind == "regular_file"
    assert digest.startswith("sha256:")
    assert size == len(content)
    assert content == b"name,value\ntotal,42\n"


def write_repo_artifact_pack(root: Path, *, base_commit: str):
    (root / "assets").mkdir(parents=True)
    (root / "evaluation_inputs").mkdir()
    (root / "hidden" / "task" / "oracle").mkdir(parents=True)
    (root / "manifest.yaml").write_text(
        f"""
schema_version: "2.0"
id: repo-artifact-pack
defaults:
  family: repo_patch
  environment:
    image: {DIGEST}
    workdir: /app
    timeout_seconds: 30
    agent_network: none
resource_roots:
  public: assets/
  runtime: evaluation_inputs/
  host: hidden/
""".lstrip()
    )
    row = {
        "id": "repo-artifact/task",
        "input": {
            "repo": "example/repository",
            "base_commit": base_commit,
            "instructions": "Write result.json.",
        },
        "verification": {
            "execution_profile": "strict-split/v1",
            "candidate": {
                "type": "git_patch",
                "max_patch_bytes": 4096,
                "max_changed_files": 2,
                "max_changed_bytes": 1024,
                "allow_paths": ["result.json"],
            },
            "resources": {"host": {"oracle": {"path": "task/oracle"}}},
            "checks": [
                {
                    "id": "result_artifact",
                    "type": "artifact",
                    "artifacts": [
                        {
                            "id": "result",
                            "source": {"path": "result.json"},
                            "parser": "securebench.strict-json/v1",
                            "limits": {"max_bytes": 1024},
                        }
                    ],
                }
            ],
            "oracle": "host.oracle",
        },
    }
    (root / "tasks.jsonl").write_text(json.dumps(row) + "\n")
    return next(
        compile_benchmark_pack(
            load_benchmark_pack(root / "manifest.yaml", root / "tasks.jsonl")
        )
    )


def make_repository(root: Path) -> tuple[Path, str]:
    root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "securebench@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "SecureBench"], cwd=root, check=True
    )
    (root / "README.md").write_text("baseline\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return root, commit


def test_git_patch_artifact_path_is_passively_observed(tmp_path, monkeypatch):
    baseline, base_commit = make_repository(tmp_path / "baseline")
    task = write_repo_artifact_pack(tmp_path / "pack", base_commit=base_commit)
    workspace = tmp_path / "workspace"
    subprocess.run(["git", "clone", "--quiet", str(baseline), str(workspace)], check=True)
    (workspace / "result.json").write_text('{"answer":42}\n')
    store = CandidateStore(tmp_path / "candidate-store")
    candidate = capture_git_patch_workspace(
        workspace,
        baseline,
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
        base_commit=base_commit,
    )

    def materialize(_task, destination):
        subprocess.run(
            ["git", "clone", "--quiet", str(baseline), str(destination)],
            check=True,
        )

    monkeypatch.setattr("securebench.harnesses.shared.materialize_image_workdir", materialize)
    monkeypatch.setattr(
        "securebench.verification.artifacts.remove_untrusted_tree",
        lambda path, *, image: shutil.rmtree(path),
    )
    oracle = RecordingOracle()

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="repo-artifact-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert oracle.evidence[0].source_kind == "regular_file"
    assert oracle.evidence[0].parsed_value == {"answer": 42}


def test_artifact_evidence_is_internal_and_result_is_sanitized(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b'{"private_observation":"secret-value"}\n')
    oracle = RecordingOracle()

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-1",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert oracle.evidence[0].parsed_value == {"private_observation": "secret-value"}
    record = result.to_record(run_id="run-1", execution_digest=DIGEST)
    encoded = json.dumps(record)
    assert "secret-value" not in encoded
    assert "parsed_value" not in encoded
    assert record["checks"][0]["evidence_digests"][0].startswith("sha256:")


def test_owned_oracle_cleanup_failure_becomes_an_infrastructure_result(
    tmp_path,
    monkeypatch,
):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"{}")

    class CleanupFailingOracle(RecordingOracle):
        def close(self):
            raise VerificationInfrastructureError(
                "oracle_cleanup_failed",
                "Oracle process cleanup failed",
            )

    monkeypatch.setattr(
        "securebench.verification.artifacts.OracleProcessSession",
        lambda resource_root: CleanupFailingOracle(),
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="cleanup-failure",
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "oracle_cleanup_failed"


def test_oracle_process_close_reports_a_process_that_cannot_be_reaped():
    class StuckProcess:
        stdin = io.BytesIO()
        stdout = io.BytesIO()

        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout):
            raise subprocess.TimeoutExpired(["oracle"], timeout)

    session = OracleProcessSession.__new__(OracleProcessSession)
    session.process = StuckProcess()

    with pytest.raises(VerificationInfrastructureError) as error:
        session.close()

    assert error.value.code == "oracle_cleanup_failed"


def test_oracle_process_close_tolerates_a_terminate_exit_race():
    class ExitedProcess:
        stdin = io.BytesIO()
        stdout = io.BytesIO()

        def __init__(self):
            self.exited = False

        def poll(self):
            return 0 if self.exited else None

        def terminate(self):
            self.exited = True
            raise ProcessLookupError

        def wait(self, timeout):
            return 0

        def kill(self):
            raise AssertionError("an exited Oracle must not be killed")

    session = OracleProcessSession.__new__(OracleProcessSession)
    session.process = ExitedProcess()

    session.close()


def test_parser_rejection_is_candidate_evidence_for_oracle(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"not-json")
    oracle = RecordingOracle()

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-2",
        oracle=oracle,
    )

    assert result.status == "failed"
    assert oracle.evidence[0].status == "candidate_error"
    assert oracle.evidence[0].error_code == "invalid_json"


@pytest.mark.parametrize("content", [b'{"answer":1,"answer":2}', b'{"answer":NaN}'])
def test_strict_json_parser_rejects_ambiguous_or_non_finite_artifacts(tmp_path, content):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, content)
    oracle = RecordingOracle()

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-strict-json",
        oracle=oracle,
    )

    assert result.status == "failed"
    assert oracle.evidence[0].status == "candidate_error"
    assert oracle.evidence[0].error_code == "invalid_json"


@pytest.mark.parametrize(
    ("descr", "values"),
    [
        ("<f2", [0.25, 0.75]),
        (">f4", [0.25, 0.75]),
        ("<f8", [0.25, 0.75]),
        ("<f16", [0.25, 0.75]),
    ],
)
def test_strict_npy_float_summary_parser_observes_generic_statistics(descr, values):
    parsed = default_parser_registry().parse_bytes(
        "securebench.strict-npy-float-summary/v1",
        npy_float_file(values, descr=descr),
    )

    assert parsed["format"] == "npy"
    assert parsed["dtype"] == descr
    assert parsed["shape"] == [2]
    assert parsed["count"] == 2
    assert parsed["statistics"]["all_finite"] is True
    assert parsed["statistics"]["all_positive"] is True
    assert parsed["statistics"]["minimum"] == pytest.approx(0.25)
    assert parsed["statistics"]["maximum"] == pytest.approx(0.75)
    assert parsed["statistics"]["sum"] == pytest.approx(1.0)


def test_strict_npy_parser_returns_json_safe_flags_for_nonfinite_values():
    parsed = default_parser_registry().parse_bytes(
        "securebench.strict-npy-float-summary/v1",
        npy_float_file([float("nan"), float("inf")]),
    )

    assert parsed["statistics"] == {
        "all_finite": False,
        "all_positive": False,
        "minimum": None,
        "maximum": None,
        "sum": None,
        "sum_log": None,
        "sum_x_log_x": None,
    }


def test_strict_npy_parser_preserves_x87_log_below_binary64_range():
    content = npy_float_file([0.25], descr="<f16")
    tiny_x87 = (
        (1 << 63).to_bytes(8, "little")
        + (10_000).to_bytes(2, "little")
        + b"\x00" * 6
    )

    parsed = default_parser_registry().parse_bytes(
        "securebench.strict-npy-float-summary/v1",
        content[:-16] + tiny_x87,
    )

    assert parsed["statistics"]["all_finite"] is True
    assert parsed["statistics"]["all_positive"] is True
    assert parsed["statistics"]["sum"] == 0.0
    assert parsed["statistics"]["sum_log"] < -4000.0


@pytest.mark.parametrize(
    ("content", "error_code"),
    [
        (b"not-npy", "invalid_npy"),
        (npy_float_file([1.0])[:-1], "invalid_npy"),
        (npy_float_file([1.0], trailing=b"x"), "invalid_npy"),
        (npy_float_file([1.0], version=(9, 0)), "invalid_npy"),
        (
            npy_float_file(
                [1.0],
                header_source=(
                    "{'descr':'<f8','descr':'>f8',"
                    "'fortran_order':False,'shape':(1,)}"
                ),
            ),
            "invalid_npy",
        ),
        (
            npy_float_file(
                [1.0],
                header_source=(
                    "{'descr':'<i8','fortran_order':False,'shape':(1,)}"
                ),
            ),
            "unsupported_npy_dtype",
        ),
        (
            npy_float_file(
                [1.0],
                shape=(1_000_001,),
            ),
            "npy_too_many_elements",
        ),
    ],
)
def test_strict_npy_parser_rejects_malformed_ambiguous_or_excessive_arrays(
    content,
    error_code,
):
    with pytest.raises(ParserRejected) as error:
        default_parser_registry().parse_bytes(
            "securebench.strict-npy-float-summary/v1",
            content,
        )

    assert getattr(error.value, "code", None) == error_code


def test_strict_npy_header_cannot_execute_candidate_expression(tmp_path):
    marker = tmp_path / "executed"
    source = (
        "{'descr':__import__('pathlib').Path(%r).write_text('bad'),"
        "'fortran_order':False,'shape':(1,)}" % str(marker)
    )
    content = npy_float_file([1.0], header_source=source)

    with pytest.raises(ParserRejected) as error:
        default_parser_registry().parse_bytes(
            "securebench.strict-npy-float-summary/v1",
            content,
        )

    assert getattr(error.value, "code", None) == "invalid_npy"
    assert not marker.exists()


@pytest.mark.parametrize(
    "verdict",
    [
        OracleVerdict(passed=True, score=1.0, check_outcomes={}),
        OracleVerdict(
            passed=True,
            score=1.0,
            check_outcomes={"result_artifact": True, "unknown": True},
        ),
    ],
)
def test_oracle_verdict_outcomes_must_match_declared_checks(tmp_path, verdict):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"{}")

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-invalid-verdict",
        oracle=FixedVerdictOracle(verdict),
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "oracle_protocol_error"


def test_oracle_may_apply_its_own_threshold_across_check_outcomes(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"{}")
    verdict = OracleVerdict(
        passed=True,
        score=0.75,
        check_outcomes={"result_artifact": False},
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-custom-threshold",
        oracle=FixedVerdictOracle(verdict),
    )

    assert result.status == "passed"
    assert result.score == 0.75
    assert result.checks[0].status == "failed"


def test_pack_local_oracle_process_owns_final_verdict(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    oracle_root = tmp_path / "pack" / "hidden" / "task" / "oracle"
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 5
""".lstrip()
    )
    (oracle_root / "oracle.py").write_text(
        """
import json
import sys

accepted = False
for line in sys.stdin:
    request = json.loads(line)
    if request["op"] == "initialize":
        print(json.dumps({"type": "ack"}), flush=True)
    elif request["op"] == "evaluate_artifact":
        accepted = request["evidence"]["parsed_value"] == {"answer": 42}
        print(json.dumps({"type": "ack"}), flush=True)
    elif request["op"] == "finalize":
        print(json.dumps({
            "type": "verdict",
            "verdict": {
                "passed": accepted,
                "score": 1.0 if accepted else 0.0,
                "check_outcomes": {"result_artifact": accepted},
                "public_diagnostics": {"message": "oracle evaluated artifact"}
            }
        }), flush=True)
""".lstrip()
    )
    task = next(
        compile_benchmark_pack(
            load_benchmark_pack(
                tmp_path / "pack" / "manifest.yaml",
                tmp_path / "pack" / "tasks.jsonl",
            )
        )
    )
    store, candidate = capture_result(tmp_path, task, b'{"answer":42}')

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-4",
    )

    assert result.status == "passed"
    assert result.public_diagnostics == {"message": "oracle evaluated artifact"}
    assert not (oracle_root / "__pycache__").exists()


def test_oracle_request_write_obeys_timeout(tmp_path):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 0.1
""".lstrip()
    )
    (oracle_root / "oracle.py").write_text(
        "import time\ntime.sleep(10)\n"
    )
    session = OracleProcessSession(oracle_root)
    started = time.monotonic()

    try:
        with pytest.raises(VerificationInfrastructureError, match="request timeout"):
            session._request(
                {"op": "large", "payload": "x" * (2 * 1024 * 1024)},
                expected="ack",
            )
    finally:
        session.close()

    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    "manifest",
    [
        "command: [unterminated\n",
        (
            "abi: securebench.oracle/v1\ncommand: ['{python}', 'oracle.py']\n"
            "timeout_seconds: 1\ntimeout_seconds: 2\n"
        ),
        "abi: securebench.oracle/v1\ncommand: ['{python}', 'oracle.py']\ntimeout_seconds: .inf\n",
        (
            "abi: securebench.oracle/v1\ncommand: ['{python}', 'oracle.py']\n"
            f"timeout_seconds: {10**400}\n"
        ),
    ],
)
def test_oracle_process_rejects_invalid_manifests(tmp_path, manifest):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(manifest)

    with pytest.raises(VerificationInfrastructureError) as error:
        OracleProcessSession(oracle_root)

    assert error.value.code == "oracle_manifest_invalid"


def test_oracle_process_rejects_an_oversized_manifest(tmp_path, monkeypatch):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text("x" * 17)
    monkeypatch.setattr("securebench.verification.oracle.MAX_ORACLE_MANIFEST_BYTES", 16)

    with pytest.raises(VerificationInfrastructureError) as error:
        OracleProcessSession(oracle_root)

    assert error.value.code == "oracle_manifest_too_large"


def test_oracle_process_reports_start_failure_as_infrastructure_error(tmp_path):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        "abi: securebench.oracle/v1\n"
        "command: ['/definitely/missing/securebench-oracle']\n"
        "timeout_seconds: 1\n"
    )

    with pytest.raises(VerificationInfrastructureError) as error:
        OracleProcessSession(oracle_root)

    assert error.value.code == "oracle_start_failed"


@pytest.mark.parametrize(
    "verdict",
    [
        {"passed": True, "score": 1.0},
        {
            "passed": True,
            "score": 1.0,
            "check_outcomes": {"result_artifact": True},
            "unexpected": True,
        },
    ],
)
def test_oracle_process_rejects_missing_or_unknown_verdict_fields(tmp_path, verdict):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 1
""".lstrip()
    )
    response = json.dumps({"type": "verdict", "verdict": verdict})
    (oracle_root / "oracle.py").write_text(
        "import sys\nfor line in sys.stdin:\n"
        f"    print({response!r}, flush=True)\n"
    )
    session = OracleProcessSession(oracle_root)

    try:
        with pytest.raises(VerificationInfrastructureError) as error:
            session.finalize()
    finally:
        session.close()

    assert error.value.code == "oracle_protocol_error"


def test_oracle_process_rejects_a_numeric_score_that_overflows_float(tmp_path):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        "abi: securebench.oracle/v1\n"
        "command: ['{python}', 'oracle.py']\n"
        "timeout_seconds: 1\n"
    )
    response = json.dumps(
        {
            "type": "verdict",
            "verdict": {
                "passed": True,
                "score": 10**400,
                "check_outcomes": {"result_artifact": True},
            },
        }
    )
    (oracle_root / "oracle.py").write_text(
        "import sys\nfor line in sys.stdin:\n"
        f"    print({response!r}, flush=True)\n"
    )
    session = OracleProcessSession(oracle_root)

    try:
        with pytest.raises(VerificationInfrastructureError) as error:
            session.finalize()
    finally:
        session.close()

    assert error.value.code == "oracle_protocol_error"


def test_unknown_parser_is_an_infrastructure_error(tmp_path):
    task = write_artifact_pack(tmp_path / "pack", parser="securebench.unknown/v1")
    store, candidate = capture_result(tmp_path, task, b"{}")

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-5",
        oracle=RecordingOracle(),
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "verification_internal_error"


def test_verification_rejects_candidate_from_another_baseline(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b'{}')
    mismatched = replace(candidate, baseline_digest="sha256:" + "0" * 64)

    result = VerificationEngine().verify(
        task,
        mismatched,
        store,
        run_seed="seed-mismatch",
        oracle=RecordingOracle(),
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "candidate_reference_mismatch"
