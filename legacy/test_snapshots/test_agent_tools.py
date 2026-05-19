import shutil
import subprocess

import pytest

from securebench_agent import WorkspaceTools


def test_workspace_tools_block_env_and_path_escape(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET=value\n")
    tools = WorkspaceTools(repo)

    with pytest.raises(ValueError, match=".env"):
        tools.read_file(".env")

    with pytest.raises(ValueError, match="escape"):
        tools.read_file("../outside.txt")


def test_workspace_tools_search_uses_rg_and_hides_env_files(tmp_path):
    if shutil.which("rg") is None:
        pytest.skip("rg is required for search tool")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("needle = True\n")
    (repo / ".env").write_text("needle=secret\n")

    result = WorkspaceTools(repo).search("needle")

    assert result["ok"] is True
    assert result["matches"] == ["app.py:1:needle = True"]


def test_workspace_tools_apply_patch_and_run_allowed_command(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text('GREETING = "hi"\n')
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)

    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-GREETING = "hi"
+GREETING = "hello"
"""
    tools = WorkspaceTools(repo, command_allow={"git"})

    patch_result = tools.apply_patch(patch)
    command_result = tools.run_command("git status --short")

    assert patch_result["ok"] is True
    assert (repo / "app.py").read_text() == 'GREETING = "hello"\n'
    assert command_result["ok"] is True
    assert "app.py" in command_result["stdout"]


def test_workspace_tools_reject_disallowed_commands_and_env_references(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = WorkspaceTools(repo, command_allow={"python"})

    result = tools.run_tool("run_command", {"command": "cat app.py"})

    assert result["ok"] is False
    assert result["error_type"] == "PolicyViolation"

    result = tools.run_tool("run_command", {"command": "python .env"})

    assert result["ok"] is False
    assert result["error_type"] == "PolicyViolation"
