from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.harnesses.command import CommandHarnessProducer
from securebench.harnesses.shared import workspace_dir_name
from securebench.sandboxes import CommandResult


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"


class FakeDockerSandbox:
    instances = []

    def __init__(self, *, root, image, mounts=(), **kwargs):
        self.root = Path(root)
        self.image = image
        self.mounts = tuple(mounts)
        self.kwargs = kwargs
        self.commands = []
        self.closed = False
        self.__class__.instances.append(self)

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((command, workdir, timeout))
        return CommandResult(tuple(command), 0, "agent log", "")

    def close(self):
        self.closed = True


def compiled_task():
    return next(
        compile_benchmark_pack(
            load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
        )
    )


def test_command_harness_exposes_ephemeral_workspace_for_declared_capture(monkeypatch, tmp_path):
    FakeDockerSandbox.instances = []
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    monkeypatch.setattr(
        "securebench.harnesses.command.materialize_image_workdir",
        lambda task, destination: None,
    )

    task = compiled_task()
    production = CommandHarnessProducer(
        command=("produce",),
        workspace_root=tmp_path,
    ).produce(task)

    assert production.patch is None
    assert production.workspace == str(tmp_path / workspace_dir_name(task))
    assert production.metadata["candidate_type"] == "file_bundle"
    sandbox = FakeDockerSandbox.instances[-1]
    assert sandbox.commands == [(('produce',), "/app", 1200.0)]
    assert sandbox.closed is True
    assert len(sandbox.mounts) == 3
    assert not any("oracle" in str(mount.source) for mount in sandbox.mounts)
