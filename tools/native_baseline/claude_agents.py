"""Upstream Claude Code agents plus the post-run capture, for condition A.

The Claude Code counterpart of ``codex_agents``: the harnesses' own
``ClaudeCode`` agents, unchanged, followed by the same read-only capture step
(``worktree.patch`` for DeepSWE, ``final-state.tar`` for Terminal-Bench).

Pass ``--ak base_commit=<sha>`` (Pier) or ``--ak capture_paths=/app/a,/app/b``
(Harbor), plus ``--ak version=... --ak reasoning_effort=...``.
"""

from __future__ import annotations

from harbor.agents.installed.claude_code import ClaudeCode as HarborClaudeCode
from harbor.agents.installed.claude_code import ClaudeCodeOptions as HarborClaudeCodeOptions
from pier.agents.installed.claude_code import ClaudeCode as PierClaudeCode

from tools.native_baseline.codex_agents import final_state_command, worktree_patch_command


class PierClaudeCodeCapture(PierClaudeCode):
    def __init__(self, *args, base_commit: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if not base_commit:
            raise ValueError("PierClaudeCodeCapture requires --ak base_commit=<sha>")
        self._campaign_base_commit = base_commit

    async def run(self, instruction, environment, context) -> None:
        try:
            await super().run(instruction, environment, context)
        finally:
            await environment.exec(command=worktree_patch_command(self._campaign_base_commit))


class HarborClaudeCodeCaptureOptions(HarborClaudeCodeOptions):
    # Plain field (no Cli annotation): validated by Harbor, never rendered as a claude flag.
    capture_paths: str | None = None


class HarborClaudeCodeCapture(HarborClaudeCode):
    options_model = HarborClaudeCodeCaptureOptions

    def __init__(self, *args, capture_paths: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        capture_paths = capture_paths or getattr(getattr(self, "options", None), "capture_paths", None)
        if not capture_paths:
            raise ValueError("HarborClaudeCodeCapture requires --ak capture_paths=/a,/b")
        self._campaign_capture_paths = [p for p in capture_paths.split(",") if p]

    async def run(self, instruction, environment, context) -> None:
        try:
            await super().run(instruction, environment, context)
        finally:
            await environment.exec(command=final_state_command(self._campaign_capture_paths))
