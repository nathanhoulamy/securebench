from securebench.candidates import (
    CandidateArtifact,
    SandboxedCommandProducer,
    SandboxedPatchProducer,
    StaticCandidateProducer,
    TextCompletionProducer,
)
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import GitHubPatchTask, MultipleChoiceTask


class FakeSandbox(Sandbox):
    def __init__(self):
        self.files = {}
        self.calls = []

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
        timeout=5,
    )

    artifact = producer.produce(make_patch_task())

    assert sandbox.calls == [
        (["git", "clone", "https://github.com/example/repo.git", "repo"], None, 5),
        (["git", "checkout", "abc123"], "repo", 5),
        (["securebench-agent", "run"], "repo", 5),
        (["git", "diff", "--binary"], "repo", 5),
    ]
    assert sandbox.files["repo/SECUREBENCH_TASK.md"].startswith("# example__repo-1\n")
    assert artifact.patch == "diff --git a/file.py b/file.py\n"
    assert artifact.metadata["agent_exit_code"] == 0
