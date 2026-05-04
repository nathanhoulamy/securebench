from securebench.candidates import (
    CandidateArtifact,
    SandboxedCommandProducer,
    SandboxedPatchProducer,
    StaticCandidateProducer,
    TextCompletionProducer,
    WorkspaceAgentPatchProducer,
)
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import GitHubPatchTask, MultipleChoiceTask


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


def make_mc_task():
    return MultipleChoiceTask(
        id="mmlu/math/test/7",
        benchmark_id="mmlu",
        task_type="multiple_choice",
        question="2 + 2?",
        choices=("1", "2", "4", "5"),
    )


def make_patch_task():
    return GitHubPatchTask(
        id="example__repo-1",
        benchmark_id="example",
        task_type="github_patch",
        repo="example/repo",
        base_commit="abc123",
        instructions="Fix the bug.",
        hints_text="Look at file.py.",
        version="1.2.3",
        fail_to_pass=("tests/test_bug.py::test_fixed",),
        pass_to_pass=("tests/test_existing.py::test_still_passes",),
        gold_patch="gold patch",
        test_patch="hidden test patch",
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
    assert sandbox.calls == [(["securebench-agent", "run"], None, 3)]
    assert artifact.metadata["exit_code"] == 0


def test_sandboxed_patch_producer_uses_agent_process_exit_as_done_signal_then_collects_diff():
    sandbox = FakeSandbox()
    producer = SandboxedPatchProducer(
        sandbox=sandbox,
        agent_command=["securebench-agent", "run"],
        setup_commands=("python -m pip install -e . || true",),
        timeout=5,
    )

    artifact = producer.produce(make_patch_task())

    assert sandbox.calls == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, 5),
        (["git", "checkout", "abc123"], "repo", 5),
        ("python -m pip install -e . || true", "repo", 5),
        (["securebench-agent", "run"], "repo", 5),
        (["git", "diff", "--binary"], "repo", 5),
    ]
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
        setup_commands=("python -m pip install pytest",),
        timeout=17,
    )

    artifact = producer.produce(make_patch_task())

    assert sandbox.calls == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, 17),
        (["git", "checkout", "abc123"], "repo", 17),
        ("python -m pip install pytest", "repo", 17),
        (
            [
                "python",
                "-m",
                "securebench.agent.run",
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
    assert artifact.patch == "diff --git a/file.py b/file.py\n"


def test_workspace_agent_patch_producer_can_run_replay_agent_without_model():
    sandbox = FakeSandbox()
    producer = WorkspaceAgentPatchProducer(
        sandbox=sandbox,
        replay_file="/workspace/replay.json",
        max_steps=2,
        timeout=3,
    )

    producer.produce(make_patch_task())

    assert sandbox.calls[2] == (
        [
            "python",
            "-m",
            "securebench.agent.run",
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

    def make_sandbox():
        sandbox = FakeSandbox()
        sandboxes.append(sandbox)
        return sandbox

    producer = SandboxedPatchProducer(
        sandbox_factory=make_sandbox,
        agent_command=["securebench-agent", "run"],
    )

    producer.produce(make_patch_task())
    producer.produce(make_patch_task())

    assert len(sandboxes) == 2
    assert sandboxes[0] is not sandboxes[1]
    assert sandboxes[0].closed is True
    assert sandboxes[1].closed is True
    assert sandboxes[0].calls[:2] == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, None),
        (["git", "checkout", "abc123"], "repo", None),
    ]
