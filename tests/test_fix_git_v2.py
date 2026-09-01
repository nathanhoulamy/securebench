from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    assert_file_bundle_capture_rejected,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/fix-git"
IMAGE = (
    "alexgshaw/fix-git@"
    "sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119"
)
ORACLE_ROOT = PACK / "v2" / "hidden" / "fix-git" / "oracle"
ORACLE = ORACLE_ROOT / "oracle.py"
SOURCE_VERIFIER = PACK / "hidden" / "fix-git" / "tests" / "test_outputs.py"
MASK = PACK / "docker" / "fix-git" / "masked-resources"
REFERENCE_ROOT = PACK / "docker" / "fix-git" / "resources" / "patch_files"
ABOUT = (REFERENCE_ROOT / "about.md").read_text(encoding="utf-8")
LAYOUT = (REFERENCE_ROOT / "default.html").read_text(encoding="utf-8")
LOST_COMMIT = "650dba427e0a9dcd118f41a4c5e35c8017550a5a"


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_files(
    tmp_path: Path,
    *,
    about: str | bytes = ABOUT,
    layout: str | bytes = LAYOUT,
):
    workspace = tmp_path / "workspace"
    (workspace / "personal-site" / "_includes").mkdir(parents=True)
    (workspace / "personal-site" / "_layouts").mkdir(parents=True)
    targets = {
        workspace / "personal-site" / "_includes" / "about.md": about,
        workspace / "personal-site" / "_layouts" / "default.html": layout,
    }
    for target, content in targets.items():
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8", newline="")
        else:
            target.write_bytes(content)
    return verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="fix-git-qualification",
    )


def artifact_evidence(artifact_id: str, value: str) -> dict:
    return {
        "check_id": "recovered_files_artifact",
        "artifact_id": artifact_id,
        "status": "observed",
        "parsed_value": value,
    }


def test_fix_git_row_is_passive_bounded_masked_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app/personal-site"
    assert task.environment.timeout_seconds == 900
    assert [(asset.path, asset.mount, asset.read_only) for asset in task.assets] == [
        ("fix-git/masked-resources", "/app/resources", True)
    ]
    assert {path.name for path in MASK.iterdir()} == {".keep"}
    assert not task.verification.resources.runtime
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.id == "recovered_files_artifact"
    assert [(item.id, item.parser) for item in check.artifacts] == [
        ("about", "securebench.utf8-text/v1"),
        ("layout", "securebench.utf8-text/v1"),
    ]
    candidate = task.verification.candidate
    assert candidate.max_total_files == 2
    assert candidate.max_total_bytes == 32_768
    assert [(item.id, item.path, item.max_bytes) for item in candidate.files] == [
        ("about", "/app/personal-site/_includes/about.md", 16_384),
        ("layout", "/app/personal-site/_layouts/default.html", 16_384),
    ]
    assert {
        path.relative_to(ORACLE_ROOT).as_posix()
        for path in ORACLE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } == {"oracle.py", "oracle.yaml"}


def test_host_digests_match_source_gold_files_and_binary_strip_semantics(tmp_path):
    source = load_module(SOURCE_VERIFIER, "fix_git_source_semantics")
    oracle = load_module(ORACLE, "fix_git_oracle_semantics")

    expected = {"about": ABOUT, "layout": LAYOUT}
    for artifact_id, content in expected.items():
        path = tmp_path / artifact_id
        path.write_bytes(content.encode("utf-8"))
        assert source.hash_file(path) == hashlib.md5(
            content.encode("utf-8").strip()
        ).hexdigest()
        assert oracle.source_digest(content) == oracle.EXPECTED_SHA256[artifact_id]


@pytest.mark.parametrize(
    ("prefix", "suffix"),
    [
        ("", ""),
        (" \t\r\n", "\n\r\t "),
        ("\v\f", "\f\v"),
    ],
)
def test_source_accepted_ascii_edge_whitespace_passes(tmp_path, prefix, suffix):
    result, candidate, store = verify_files(
        tmp_path,
        about=prefix + ABOUT + suffix,
        layout=prefix + LAYOUT + suffix,
    )

    assert result.status == "passed", result
    assert result.candidate_digest == candidate.digest
    assert len(store.load_candidate(candidate.digest).payload["entries"]) == 2


@pytest.mark.parametrize(
    ("about", "layout", "category"),
    [
        (ABOUT.replace("Stanford", "Berkeley", 1), LAYOUT, "incorrect_about_file"),
        (ABOUT, LAYOUT.replace("Stanford", "Berkeley", 1), "incorrect_layout_file"),
        ("PASS", '{"verdict":"passed","score":1}', "incorrect_about_file"),
        ("\u2003" + ABOUT, LAYOUT, "incorrect_about_file"),
    ],
)
def test_targeted_mutants_and_forged_claims_fail(tmp_path, about, layout, category):
    result, _, _ = verify_files(tmp_path, about=about, layout=layout)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"]


def test_oracle_rejects_duplicate_and_uncorrelated_artifacts():
    module = load_module(ORACLE, "fix_git_oracle_correlation")
    oracle = module.FixGitOracle()
    oracle.initialize()
    oracle.evaluate(artifact_evidence("about", ABOUT))
    oracle.evaluate(artifact_evidence("about", ABOUT))
    oracle.evaluate(artifact_evidence("layout", LAYOUT))
    oracle.evaluate(artifact_evidence("unexpected", "PASS"))

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is False
    assert verdict["check_outcomes"] == {"recovered_files_artifact": False}
    assert verdict["public_diagnostics"]["failure_categories"] == [
        "duplicate_artifact",
        "uncorrelated_artifact",
    ]


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_files(tmp_path, about=ABOUT.encode() + b"\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["about:invalid_utf8"]


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_files(tmp_path)
    replay = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="fix-git-replay",
    )

    assert first.status == replay.status == "passed"
    assert first.candidate_digest == replay.candidate_digest == candidate.digest


@pytest.mark.parametrize("target_id", ["about", "layout"])
@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_both_candidate_files_reject_malicious_shapes(tmp_path, target_id, attack):
    assert_file_bundle_capture_rejected(
        compiled_task(),
        tmp_path,
        attack=attack,
        target_id=target_id,
    )


REFERENCE_COMMAND = (
    "set -eu; "
    "test ! -e /app/resources/patch_files; "
    f"git merge --no-edit {LOST_COMMIT} || true; "
    f"git checkout {LOST_COMMIT} -- _includes/about.md _layouts/default.html; "
    "git add _includes/about.md _layouts/default.html; "
    "git commit --no-edit"
)


@DOCKER_INTEGRATION
def test_pinned_base_fails_and_mask_hides_gold_copies(tmp_path):
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", "test ! -e /app/resources/patch_files"),
        run_seed="fix-git-pinned-base",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert set(result.public_diagnostics["failure_categories"]) == {
        "incorrect_about_file",
        "incorrect_layout_file",
    }


@DOCKER_INTEGRATION
def test_pinned_reflog_merge_reference_passes_and_replays(tmp_path):
    result, candidate, store = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", REFERENCE_COMMAND),
        run_seed="fix-git-pinned-reference",
    )
    replay = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="fix-git-pinned-reference",
    )

    assert result.status == replay.status == "passed"
    assert result.candidate_digest == replay.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "command",
    [
        pytest.param(
            f"git checkout {LOST_COMMIT} -- _includes/about.md",
            id="about-only",
        ),
        pytest.param(
            f"git checkout {LOST_COMMIT} -- _layouts/default.html",
            id="layout-only",
        ),
        pytest.param(
            "printf PASS > _includes/about.md; printf PASS > _layouts/default.html",
            id="forged-pass",
        ),
    ],
)
def test_pinned_partial_and_forged_mutants_fail(tmp_path, command):
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", command),
        run_seed="fix-git-pinned-mutant",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
