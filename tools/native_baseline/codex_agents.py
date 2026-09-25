"""Upstream Codex agents plus a post-run capture, for condition A.

These subclass the harnesses' own ``Codex`` agents unchanged and add one step
after Codex exits (before the harness runs pre_artifacts/verification):

* ``PierCodexCapture`` (DeepSWE): writes ``/logs/agent/campaign/worktree.patch``,
  the full working-tree diff against the base commit (tracked + untracked, via a
  throwaway index so the repository's index, HEAD and files are untouched).
  Upstream grades only committed work (``pre_artifacts.sh`` →
  ``/logs/artifacts/model.patch``); the working-tree diff lets Phase 5 separate
  "did not commit" from "wrong code".
* ``HarborCodexCapture`` (Terminal-Bench): tars the SecureBench-declared
  candidate paths to ``/logs/agent/campaign/final-state.tar`` so the same
  file_bundle can be re-graded by SecureBench.

Pass ``--ak base_commit=<sha>`` (Pier) or ``--ak capture_paths=/app/a,/app/b``
(Harbor), plus the normal ``--ak version=... --ak reasoning_effort=...``.
Both steps only read the candidate state; their exit codes are logged.
"""

from __future__ import annotations

import shlex

from harbor.agents.installed.codex import Codex as HarborCodex
from harbor.agents.installed.codex import CodexOptions as HarborCodexOptions
from pier.agents.installed.codex import Codex as PierCodex

CAPTURE_DIR = "/logs/agent/campaign"


def worktree_patch_command(base_commit: str) -> str:
    base = shlex.quote(base_commit)
    return (
        f"mkdir -p {CAPTURE_DIR}; cd /app || exit 0; "
        "index=$(mktemp); "
        "git -c safe.directory='*' log --format='%H %s' "
        f"{base}..HEAD > {CAPTURE_DIR}/commits.txt 2>&1; "
        "git -c safe.directory='*' status --porcelain=v1 --untracked-files=all "
        f"> {CAPTURE_DIR}/status.txt 2>&1; "
        f"GIT_INDEX_FILE=$index git -c safe.directory='*' read-tree {base} && "
        "GIT_INDEX_FILE=$index git -c safe.directory='*' add -A -- . && "
        "GIT_INDEX_FILE=$index git -c safe.directory='*' diff --cached --binary --no-renames "
        f"{base} > {CAPTURE_DIR}/worktree.patch; "
        f"echo $? > {CAPTURE_DIR}/worktree.exit; rm -f $index"
    )


def final_state_command(paths: list[str]) -> str:
    quoted = " ".join(shlex.quote(p.lstrip("/")) for p in paths)
    return (
        f"mkdir -p {CAPTURE_DIR}; cd / && "
        f"tar -cpf {CAPTURE_DIR}/final-state.tar --ignore-failed-read {quoted} "
        f"> {CAPTURE_DIR}/final-state.log 2>&1; echo $? > {CAPTURE_DIR}/final-state.exit; "
        f"for p in {quoted}; do ls -ld \"/$p\" 2>&1; done > {CAPTURE_DIR}/final-state.ls"
    )


class PierCodexCapture(PierCodex):
    def __init__(self, *args, base_commit: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if not base_commit:
            raise ValueError("PierCodexCapture requires --ak base_commit=<sha>")
        self._campaign_base_commit = base_commit

    async def run(self, instruction, environment, context) -> None:
        try:
            await super().run(instruction, environment, context)
        finally:
            await environment.exec(command=worktree_patch_command(self._campaign_base_commit))


class HarborCodexCaptureOptions(HarborCodexOptions):
    # Plain field (no Cli annotation): validated by Harbor, never rendered as a codex flag.
    capture_paths: str | None = None


class HarborCodexCapture(HarborCodex):
    options_model = HarborCodexCaptureOptions

    def __init__(self, *args, capture_paths: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        capture_paths = capture_paths or getattr(getattr(self, "options", None), "capture_paths", None)
        if not capture_paths:
            raise ValueError("HarborCodexCapture requires --ak capture_paths=/a,/b")
        self._campaign_capture_paths = [p for p in capture_paths.split(",") if p]

    async def run(self, instruction, environment, context) -> None:
        try:
            await super().run(instruction, environment, context)
        finally:
            await environment.exec(command=final_state_command(self._campaign_capture_paths))
