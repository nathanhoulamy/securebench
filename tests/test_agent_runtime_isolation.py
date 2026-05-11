import json
import subprocess
import sys


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
