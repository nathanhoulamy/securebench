from pathlib import Path

from securebench.candidates import (
    CandidateArtifact,
    SandboxedCommandProducer,
    SandboxedPatchProducer,
    StaticCandidateProducer,
    TextCompletionProducer,
    WorkspaceAgentPatchProducer,
)
from securebench.repositories import PreparedRepository
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import task_from_spec


class FakeSandbox(Sandbox):
    def __init__(self):
        self.files = {}
        self.calls = []
        self.closed = False

    def run(self, command, *, workdir=None, timeout=None):
        self.calls.append((command, workdir, timeout))
        if command == ["git", "diff", "--binary"]:
            return CommandResult(tuple(command), 0, "diff --git a/file.py b/file.py\n", "")
        return CommandResult(tuple(command) if not isinstance(command, str) else ("sh", "-lc", command), 0, "stdout", "")

    def write_file(self, path, content):
        self.files[str(path)] = content

    def read_file(self, path):
        return self.files[str(path)]

    def extract_file(self, path):
        return self.files[str(path)].encode()

    def close(self):
        self.closed = True


class RecordingRepositoryPreparer:
    def __init__(self):
        self.calls = []

    def prepare(self, task, sandbox, *, repo_dir, timeout=None):
        self.calls.append((task.id, sandbox, repo_dir, timeout))
        sandbox.write_file(f"{repo_dir}/prepared.txt", "prepared")
        return PreparedRepository(path=Path(repo_dir), repo_dir=repo_dir)


def make_mc_task():
    return task_from_spec(
        {
            "id": "mmlu/math/test/7",
            "benchmark_id": "mmlu",
            "task_type": "multiple_choice",
            "resources": {
                "question": {"value": "2 + 2?", "visibility": "public"},
                "choices": {"value": ["1", "2", "4", "5"], "visibility": "public"},
                "answer": {"value": 2, "visibility": "hidden"},
            },
        }
    )


def make_patch_task():
    return task_from_spec(
        {
            "id": "example__repo-1",
            "benchmark_id": "example",
            "task_type": "github_patch",
            "resources": {
                "id": {"value": "example__repo-1", "visibility": "public"},
                "repo": {"value": "example/repo", "visibility": "public"},
                "base_commit": {"value": "abc123", "visibility": "public"},
                "instructions": {"value": "Fix the bug.", "visibility": "public"},
                "hints_text": {"value": "Look at file.py.", "visibility": "public"},
                "version": {"value": "1.2.3", "visibility": "public"},
                "fail_to_pass": {
                    "value": ["tests/test_bug.py::test_fixed"],
                    "visibility": "hidden",
                },
                "pass_to_pass": {
                    "value": ["tests/test_existing.py::test_still_passes"],
                    "visibility": "hidden",
                },
                "gold_patch": {"value": "gold patch", "visibility": "hidden"},
                "test_patch": {"value": "hidden test patch", "visibility": "hidden"},
            },
        }
    )


def test_candidate_artifact_returns_runner_value_by_task_type():
    assert CandidateArtifact(text="C", patch="diff").for_task(make_mc_task()) == "C"
    assert CandidateArtifact(text="C", patch="diff").for_task(make_patch_task()) == "diff"


def test_static_candidate_producer_returns_fixed_text_artifact():
    artifact = StaticCandidateProducer("C").produce(make_mc_task())

    assert artifact.text == "C"


def test_text_completion_producer_calls_generator_with_agent_payload():
    seen = {}

    def generate(payload, **options):
        seen["payload"] = payload
        seen["options"] = options
        return "C"

    artifact = TextCompletionProducer(generate, name="test-model", options={"temperature": 0}).produce(
        make_mc_task(),
        timeout=8,
    )

    assert artifact.text == "C"
    assert artifact.metadata["producer"] == "test-model"
    assert seen["payload"]["question"] == "2 + 2?"
    assert "answer" not in seen["payload"]
    assert seen["options"] == {"temperature": 0, "timeout": 8}


def test_sandboxed_command_producer_writes_task_payload_and_reads_artifact_file():
    sandbox = FakeSandbox()
    sandbox.files["candidate.txt"] = "B"
    producer = SandboxedCommandProducer(
        sandbox=sandbox,
        command=["securebench-agent", "run"],
        artifact_path="candidate.txt",
        timeout=3,
    )

    artifact = producer.produce(make_mc_task())

    assert artifact.text == "B"
    assert "securebench_task.json" in sandbox.files
    assert "answer" not in sandbox.files["securebench_task.json"]
    assert sandbox.calls == [(["securebench-agent", "run"], None, 3)]
    assert artifact.metadata["exit_code"] == 0


def test_sandboxed_patch_producer_uses_agent_process_exit_as_done_signal_then_collects_diff():
    sandbox = FakeSandbox()
    preparer = RecordingRepositoryPreparer()
    producer = SandboxedPatchProducer(
        sandbox=sandbox,
        agent_command=["securebench-agent", "run"],
        repository_preparer=preparer,
        setup_commands=("python -m pip install -e . || true",),
        timeout=5,
    )

    artifact = producer.produce(make_patch_task())

    assert sandbox.calls == [
        ("python -m pip install -e . || true", "repo", 5),
        (["securebench-agent", "run"], "repo", 5),
        (["git", "diff", "--binary"], "repo", 5),
    ]
    assert preparer.calls == [("example__repo-1", sandbox, "repo", 5)]
    assert sandbox.files["repo/prepared.txt"] == "prepared"
    task_file = sandbox.files["repo/SECUREBENCH_TASK.md"]
    assert "repo: example/repo" in task_file
    assert "base_commit: abc123" in task_file
    assert "version: 1.2.3" in task_file
    assert "Fix the bug." in task_file
    assert "Look at file.py." in task_file
    assert "gold patch" not in task_file
    assert "hidden test patch" not in task_file
    assert "FAIL_TO_PASS" not in task_file
    assert "PASS_TO_PASS" not in task_file
    assert artifact.patch == "diff --git a/file.py b/file.py\n"
    assert artifact.metadata["setup_command_count"] == 1
    assert artifact.metadata["agent_exit_code"] == 0


def test_workspace_agent_patch_producer_runs_builtin_agent_command_and_collects_diff():
    sandbox = FakeSandbox()
    preparer = RecordingRepositoryPreparer()
    producer = WorkspaceAgentPatchProducer(
        sandbox=sandbox,
        model="test-model",
        base_url="https://llm.example/v1",
        api_key_env="TEST_API_KEY",
        max_steps=7,
        max_tool_output=4096,
        command_timeout=11,
        request_timeout=13,
        temperature=0,
        allow_commands=("git", "pytest"),
        deny_commands=("curl",),
        repository_preparer=preparer,
        setup_commands=("python -m pip install pytest",),
        timeout=17,
    )

    artifact = producer.produce(make_patch_task())

    assert sandbox.calls == [
        ("python -m pip install pytest", "repo", 17),
        (
            [
                "python",
                "-m",
                "securebench_agent.run",
                "--repo-root",
                ".",
                "--task-file",
                "SECUREBENCH_TASK.md",
                "--max-steps",
                "7",
                "--max-tool-output",
                "4096",
                "--command-timeout",
                "11",
                "--model",
                "test-model",
                "--base-url",
                "https://llm.example/v1",
                "--api-key-env",
                "TEST_API_KEY",
                "--timeout",
                "13",
                "--temperature",
                "0",
                "--allow-command",
                "git",
                "--allow-command",
                "pytest",
                "--deny-command",
                "curl",
            ],
            "repo",
            17,
        ),
        (["git", "diff", "--binary"], "repo", 17),
    ]
    assert preparer.calls == [("example__repo-1", sandbox, "repo", 17)]
    assert artifact.patch == "diff --git a/file.py b/file.py\n"


def test_workspace_agent_patch_producer_can_run_replay_agent_without_model():
    sandbox = FakeSandbox()
    preparer = RecordingRepositoryPreparer()
    producer = WorkspaceAgentPatchProducer(
        sandbox=sandbox,
        repository_preparer=preparer,
        replay_file="/workspace/replay.json",
        max_steps=2,
        timeout=3,
    )

    producer.produce(make_patch_task())

    assert sandbox.calls[0] == (
        [
            "python",
            "-m",
            "securebench_agent.run",
            "--repo-root",
            ".",
            "--task-file",
            "SECUREBENCH_TASK.md",
            "--max-steps",
            "2",
            "--max-tool-output",
            "12000",
            "--command-timeout",
            "60.0",
            "--replay-file",
            "/workspace/replay.json",
            "--timeout",
            "60.0",
            "--temperature",
            "0.0",
        ],
        "repo",
        3,
    )


def test_sandboxed_patch_producer_uses_fresh_factory_sandbox_per_task_and_closes_it():
    sandboxes = []
    preparer = RecordingRepositoryPreparer()

    def make_sandbox():
        sandbox = FakeSandbox()
        sandboxes.append(sandbox)
        return sandbox

    producer = SandboxedPatchProducer(
        sandbox_factory=make_sandbox,
        agent_command=["securebench-agent", "run"],
        repository_preparer=preparer,
    )

    producer.produce(make_patch_task())
    producer.produce(make_patch_task())

    assert len(sandboxes) == 2
    assert sandboxes[0] is not sandboxes[1]
    assert sandboxes[0].closed is True
    assert sandboxes[1].closed is True
    assert len(preparer.calls) == 2
    assert preparer.calls[0][1] is sandboxes[0]
    assert preparer.calls[1][1] is sandboxes[1]
