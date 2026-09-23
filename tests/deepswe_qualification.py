"""Shared real-capture qualification for DeepSWE ``repo_patch`` rows.

Generalises the harness first written for ``go-critic-doc-link-checker``. Every
candidate goes through the production path: a workspace is cloned from the
materialised pinned baseline, optionally patched, and then captured by the
trusted ``capture_git_patch_workspace`` against the exact base commit. No patch
is ever handed to the verifier directly, and nothing here executes candidate
code on the host — candidate code runs only inside Evaluation containers.

The reference patch is host-only qualification material installed by
``tools/deepswe_reference.py``; it is never declared as a row resource.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import CandidateStore, capture_git_patch_workspace
from securebench.harnesses.shared import materialize_image_workdir
from securebench.tester_config import load_tester_config
from securebench.tester_run import docker_memory_limit
from securebench.verification import VerificationEngine
from securebench.verification.oracle import OracleProcessSession


# Qualify under the same memory policy the pack's tester config runs with.
PACK_MEMORY_LIMIT = load_tester_config(
    Path(__file__).resolve().parents[1] / "benchmarks" / "deep-swe" / "tester-linux.yaml"
).docker.memory_limit


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "deep-swe"
HIDDEN = PACK / "v2" / "hidden"


STAGING = PACK / "v2" / "staging"


def _registered_ids() -> set[str]:
    return {
        json.loads(line)["id"]
        for line in (PACK / "tasks-v2.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def deep_task(name: str):
    """Compile one DeepSWE row, from the pack or from its staging file.

    A conversion in progress lives in ``v2/staging/<name>.json`` until it has
    qualified, and is compiled on its own in a single-row pack built next to the
    real manifest. That keeps a half-finished row from breaking compilation of
    the registered pack, and lets several conversions proceed independently.
    Once integrated into ``tasks-v2.jsonl`` the registered row takes precedence.
    """
    task_id = f"deep-swe/{name}"
    staged = STAGING / f"{name}.json"
    if task_id not in _registered_ids() and staged.is_file():
        row = json.loads(staged.read_text(encoding="utf-8"))
        assert row["id"] == task_id, (row["id"], task_id)
        tasks_file = STAGING / f".{name}.tasks.jsonl"
        tasks_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
        try:
            pack = load_benchmark_pack(PACK / "manifest-v2.yaml", tasks_file)
            return next(iter(compile_benchmark_pack(pack)))
        finally:
            tasks_file.unlink(missing_ok=True)
    pack = load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
    for task in compile_benchmark_pack(pack):
        if task.id == task_id:
            return task
    raise KeyError(task_id)


def reference_patch(name: str) -> Path:
    path = HIDDEN / name / "qualification" / "reference.patch"
    assert path.is_file(), f"missing host-only reference material: {path}"
    return path


def materialize_baseline(name: str, root: Path) -> Path:
    materialize_image_workdir(deep_task(name), root)
    return root


class RecordingOracle(OracleProcessSession):
    """Real Oracle subprocess that also keeps the Challenge Evidence it saw."""

    def __init__(self, name: str):
        super().__init__(HIDDEN / name / "oracle")
        self.evidence = []

    def evaluate_challenge(self, check_id, challenge_context, evidence):
        self.evidence.append(evidence)
        super().evaluate_challenge(check_id, challenge_context, evidence)


@dataclass
class Qualification:
    result: object
    candidate: object
    evidence: list

    @property
    def status(self) -> str:
        return self.result.status

    @property
    def evaluation_ids(self) -> list[str]:
        return [item.evaluation_id for item in self.evidence]

    @property
    def infrastructure_errors(self) -> list:
        return [item for item in self.evidence if item.status == "infrastructure_error"]


def verify_patch(
    name: str,
    baseline: Path,
    tmp_path: Path,
    *,
    reference: bool = False,
    mutate: Callable[[Path], None] | None = None,
    run_seed: str | None = None,
) -> Qualification:
    task = deep_task(name)
    workspace = tmp_path / "workspace"
    subprocess.run(
        ["git", "clone", "--quiet", str(baseline), str(workspace)], check=True
    )
    if reference:
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn",
             str(reference_patch(name))],
            check=True,
        )
    if mutate is not None:
        mutate(workspace)

    store = CandidateStore(tmp_path / "store")
    candidate = capture_git_patch_workspace(
        workspace,
        baseline,
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
        base_commit=task.input["base_commit"],
    )
    with RecordingOracle(name) as oracle, docker_memory_limit(PACK_MEMORY_LIMIT):
        result = VerificationEngine().verify(
            task,
            candidate,
            store,
            run_seed=run_seed or f"{name}-qualification",
            oracle=oracle,
        )
        evidence = list(oracle.evidence)

    assert result.candidate_digest == candidate.digest
    assert store.reference(candidate.digest) == candidate
    (tmp_path / "qualification-summary.json").write_text(
        json.dumps(
            {
                "status": result.status,
                "candidate_digest": candidate.digest,
                "row_digest": task.row_digest,
                "baseline_digest": task.baseline_digest,
                "verification_digest": task.verification_digest,
                "evaluations": [
                    {
                        "evaluation_id": item.evaluation_id,
                        "challenge_id": item.challenge_id,
                        "evidence_digest": item.digest,
                        "status": item.status,
                    }
                    for item in evidence
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return Qualification(result=result, candidate=candidate, evidence=evidence)
