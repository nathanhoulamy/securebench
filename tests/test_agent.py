import subprocess

from securebench.agent import ReplayToolModel, WorkspaceAgent


def test_workspace_agent_executes_tool_loop_and_applies_patch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SECUREBENCH_TASK.md").write_text("Change greeting to hello.\n")
    (repo / "app.py").write_text('GREETING = "hi"\n')
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)

    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-GREETING = "hi"
+GREETING = "hello"
"""
    model = ReplayToolModel(
        [
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            {"tool": "apply_patch", "arguments": {"patch": patch}},
            {"tool": "finish", "arguments": {"summary": "updated greeting"}},
        ]
    )

    result = WorkspaceAgent(repo_root=repo, task_file="SECUREBENCH_TASK.md", model=model, max_steps=5).run()

    assert result.finished is True
    assert result.summary == "updated greeting"
    assert (repo / "app.py").read_text() == 'GREETING = "hello"\n'
    assert any(message["role"] == "tool" and '"path": "app.py"' in message["content"] for message in result.messages)
