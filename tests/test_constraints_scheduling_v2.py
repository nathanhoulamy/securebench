from __future__ import annotations

from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import CandidateStore, HostWorkspaceFilesystem, capture_file_bundle
from securebench.verification import ArtifactVerificationEngine


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"


def candidate_calendar(start: str, end: str) -> str:
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//SecureBench//Constraints Scheduling Candidate//EN
BEGIN:VEVENT
UID:team-planning@example.com
DTSTART:{start}
DTEND:{end}
SUMMARY:Team Planning Meeting
ATTENDEE:mailto:alice@example.com
ATTENDEE:mailto:bob@example.com
ATTENDEE:mailto:carol@example.com
END:VEVENT
END:VCALENDAR
"""


def compiled_task():
    pack = load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
    return next(compile_benchmark_pack(pack))


def verify_calendar(tmp_path: Path, content: str):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "meeting_scheduled.ics").write_text(content)
    # Candidate-side copies are deliberately untrusted and are not consulted
    # by the host Oracle; public assets are resolved from the pack source lane.
    (workspace / "alice_calendar.ics").write_text("candidate-modified")
    store = CandidateStore(tmp_path / "candidate-store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )
    return ArtifactVerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="constraints-scheduling-test-seed",
    )


def test_constraints_scheduling_v2_passes_known_good_artifact(tmp_path):
    result = verify_calendar(
        tmp_path,
        candidate_calendar("20240117T110000Z", "20240117T120000Z"),
    )

    assert result.status == "passed"
    assert result.score == 1.0
    assert result.checks[0].id == "schedule_artifact"


def test_constraints_scheduling_v2_rejects_non_earliest_artifact(tmp_path):
    result = verify_calendar(
        tmp_path,
        candidate_calendar("20240118T110000Z", "20240118T120000Z"),
    )

    assert result.status == "failed"
    assert result.score == 0.0
    assert "not_earliest_valid_slot" in result.public_diagnostics["failure_categories"]
