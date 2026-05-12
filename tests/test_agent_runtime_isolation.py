import json
import subprocess
import sys
from types import SimpleNamespace


def test_standalone_agent_import_does_not_load_securebench_framework():
    script = """
import json
import sys
import securebench_agent.run
blocked = [
    name for name in sys.modules
    if name == "securebench" or name.startswith(("securebench.config", "securebench.evaluator", "securebench.runners", "securebench.candidates"))
]
print(json.dumps(blocked))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []


def test_agent_cli_omits_temperature_by_default(monkeypatch, tmp_path):
    import securebench_agent.run as agent_run

    seen = {}

    class FakeToolModel:
        def __init__(self, config):
            seen["config"] = config

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self):
            return SimpleNamespace(finished=True, steps=0, summary="done")

    monkeypatch.setattr(agent_run, "OpenAICompatibleToolModel", FakeToolModel)
    monkeypatch.setattr(agent_run, "WorkspaceAgent", FakeAgent)

    exit_code = agent_run.main(
        [
            "--repo-root",
            str(tmp_path),
            "--model",
            "gpt-5.5",
        ]
    )

    assert exit_code == 0
    assert seen["config"].temperature is None
