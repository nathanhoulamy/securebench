"""git-leak-recovery candidate builder for the faithful dual-grader driver."""
from __future__ import annotations

from pathlib import Path

from tools.native_baseline.adversarial import git_leak_recovery as g

ROW = "terminal-bench/git-leak-recovery"
CANDIDATES = ["base", "reference", "reflog_only", "dangling_commit", "alternates"]

_FUNCS = {
    "base": g.cand_base,
    "reference": g.cand_reference,
    "reflog_only": g.cand_reflog_only,
    "dangling_commit": g.cand_dangling_commit,
    "alternates": g.cand_alternates,
}


def build(name: str, workspace: Path):
    _, solves, intent, goal = _FUNCS[name](workspace)
    return solves, intent, goal
