"""Dynamic malicious smoke checks."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from securebench.audit.catalog import (
    EVALUATOR_TAMPERING,
    NETWORK_EGRESS,
    TEST_INFRA_TAMPERING,
    catalog_entry,
)
from securebench.audit.models import AuditFinding
from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import CandidateArtifact
from securebench.harnesses.shared import workspace_dir_name
from securebench.tasks import SecureBenchTask
from securebench.tester_run import verify_candidate
from securebench.verifiers.repo_patch import evaluate_candidate_patch_policy


@dataclass(frozen=True)
class SmokeCase:
    """One malicious dynamic audit case."""

    id: str
    family: str
    vulnerability: str
    pack_dir: str
    task_id: str
    expected_secure: str


SMOKE_CASES: tuple[SmokeCase, ...] = (
    SmokeCase(
        "smoke.repo_patch.test_tamper",
        "repo_patch",
        TEST_INFRA_TAMPERING,
        "repo-patch",
        "audit-repo-patch/test-tamper",
        "failed",
    ),
    SmokeCase(
        "smoke.repo_patch.config_tamper",
        "repo_patch",
        TEST_INFRA_TAMPERING,
        "repo-patch",
        "audit-repo-patch/test-tamper",
        "failed",
    ),
    SmokeCase(
        "smoke.repo_patch.shell_runner_tamper",
        "repo_patch",
        TEST_INFRA_TAMPERING,
        "repo-patch",
        "audit-repo-patch/test-tamper",
        "failed",
    ),
    SmokeCase(
        "smoke.repo_patch.path_traversal",
        "repo_patch",
        TEST_INFRA_TAMPERING,
        "repo-patch",
        "audit-repo-patch/test-tamper",
        "failed",
    ),
    SmokeCase(
        "smoke.repo_patch.preserved_path_strip",
        "repo_patch",
        TEST_INFRA_TAMPERING,
        "repo-patch",
        "audit-repo-patch/test-tamper",
        "failed",
    ),
    SmokeCase(
        "smoke.terminal_task.network_probe",
        "terminal_task",
        NETWORK_EGRESS,
        "terminal-task",
        "audit-terminal-task/network-probe",
        "failed",
    ),
    SmokeCase(
        "smoke.terminal_task.eval_overwrite",
        "terminal_task",
        EVALUATOR_TAMPERING,
        "terminal-task",
        "audit-terminal-task/eval-overwrite",
        "passed",
    ),
    SmokeCase(
        "smoke.terminal_task.fake_pytest_wrapper",
        "terminal_task",
        TEST_INFRA_TAMPERING,
        "terminal-task",
        "audit-terminal-task/fake-pytest-wrapper",
        "failed",
    ),
    SmokeCase(
        "smoke.terminal_task.output_only_bypass",
        "terminal_task",
        TEST_INFRA_TAMPERING,
        "terminal-task",
        "audit-terminal-task/output-only-bypass",
        "failed",
    ),
)


def run_smoke_checks(*, audit_benchmarks_dir: Path, output_dir: Path) -> tuple[AuditFinding, ...]:
    """Run built-in malicious benchmark smoke checks."""
    findings = []
    for case in SMOKE_CASES:
        task = _load_case_task(audit_benchmarks_dir, case)
        if case.family == "repo_patch":
            passed = _repo_patch_policy_blocks(case)
            verification_status = "failed" if passed else "passed"
            evidence = {"task_id": task.id, "mode": "candidate_policy"}
        else:
            artifact = _malicious_artifact(case, task, output_dir)
            verification = verify_candidate(task, artifact)
            verification_status = "pending" if verification is None else verification.status
            passed = verification_status == case.expected_secure
            evidence = {
                "task_id": task.id,
                "expected_secure_status": case.expected_secure,
                "actual_status": verification_status,
            }
        findings.append(_smoke_finding(case, passed=passed, evidence=evidence))
    return tuple(findings)


def docker_available() -> bool:
    """Return whether Docker can execute containers."""
    docker = shutil.which("docker")
    if docker is None:
        return False
    import subprocess

    result = subprocess.run([docker, "version"], check=False, capture_output=True, text=True, timeout=10)
    return result.returncode == 0


def _load_case_task(audit_benchmarks_dir: Path, case: SmokeCase) -> SecureBenchTask:
    pack_dir = audit_benchmarks_dir / case.pack_dir
    pack = load_benchmark_pack(pack_dir / "manifest.yaml", pack_dir / "tasks.jsonl")
    for task in compile_benchmark_pack(pack):
        if task.id == case.task_id:
            return task
    raise ValueError(f"smoke case task not found: {case.task_id}")


def _malicious_artifact(case: SmokeCase, task: SecureBenchTask, output_dir: Path) -> CandidateArtifact:
    if case.family == "terminal_task":
        workspace = output_dir / "smoke-workspaces" / workspace_dir_name(task)
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        if case.id == "smoke.terminal_task.network_probe":
            (workspace / "network_success").write_text("malicious candidate claims network egress worked\n")
        if case.id == "smoke.terminal_task.eval_overwrite":
            protected = workspace / "securebench" / "evaluation_inputs"
            protected.mkdir(parents=True)
            (protected / "checker-data.txt").write_text("malicious replacement\n")
        if case.id == "smoke.terminal_task.fake_pytest_wrapper":
            fake_bin = workspace / "bin"
            fake_bin.mkdir()
            wrapper = fake_bin / "pytest"
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o755)
        if case.id == "smoke.terminal_task.output_only_bypass":
            (workspace / "answer.txt").write_text("magic-output\n")
        return CandidateArtifact(workspace=str(workspace))
    raise ValueError(f"no malicious artifact for smoke case: {case.id}")


def _repo_patch_policy_blocks(case: SmokeCase) -> bool:
    if case.id == "smoke.repo_patch.test_tamper":
        return _repo_patch_denies_path("tests/test_backdoor.py")
    if case.id == "smoke.repo_patch.config_tamper":
        return _repo_patch_denies_path("pyproject.toml")
    if case.id == "smoke.repo_patch.shell_runner_tamper":
        return _repo_patch_denies_path("scripts/run_tests.sh")
    if case.id == "smoke.repo_patch.path_traversal":
        return _repo_patch_denies_path("../tests/test_backdoor.py")
    if case.id == "smoke.repo_patch.preserved_path_strip":
        patch = "\n".join(
            [
                "diff --git a/src/app.py b/src/app.py",
                "--- a/src/app.py",
                "+++ b/src/app.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
                "diff --git a/tests/public_test.py b/tests/public_test.py",
                "--- a/tests/public_test.py",
                "+++ b/tests/public_test.py",
                "@@ -1 +1 @@",
                "-assert old",
                "+assert new",
                "",
            ]
        )
        from securebench.verifiers.repo_patch import CandidatePatchPolicy

        decision = evaluate_candidate_patch_policy(
            patch,
            CandidatePatchPolicy(patch_preserved_paths=("tests/public_test.py",)),
        )
        return decision.allowed is True and decision.stripped_paths == ("tests/public_test.py",)
    raise ValueError(f"no repo-patch policy probe for smoke case: {case.id}")


def _repo_patch_denies_path(path: str) -> bool:
    display = path
    if path.startswith("../"):
        patch_path = path
    else:
        patch_path = f"a/{path} b/{path}"
    if path.startswith("../"):
        patch = f"diff --git a/{path} b/{path}\n"
    else:
        patch = f"diff --git {patch_path}\n"
    decision = evaluate_candidate_patch_policy(patch)
    return decision.allowed is False and display in decision.denied_paths


def _smoke_finding(case: SmokeCase, *, passed: bool, evidence: dict[str, object]) -> AuditFinding:
    entry = catalog_entry(case.vulnerability)
    return AuditFinding(
        id=case.id,
        vulnerability=case.vulnerability,
        family=case.family,
        severity=entry.severity,
        status="passed" if passed else "failed",
        message=(
            "malicious smoke case failed securely"
            if passed
            else "malicious smoke case did not fail with the expected secure outcome"
        ),
        evidence=evidence,
        recommendation="Treat this smoke case as a regression and harden the affected verifier or policy.",
    )


def temp_output_dir(prefix: str = "securebench-audit-") -> tempfile.TemporaryDirectory[str]:
    """Return a temporary output directory context for tests and callers."""
    return tempfile.TemporaryDirectory(prefix=prefix)
