"""Adversarial-candidate pilot for terminal-bench/git-leak-recovery.

Hand-authored candidates graded by BOTH verifiers:
  - native  : the upstream test_outputs.py logic (git CLI on the repo; the
              worktree checksum uses the canonical in-container path /app/repo,
              exactly as upstream computes it). No network: we run the grading
              logic, not test.sh's uv bootstrap.
  - securebench: verify_workspace() -> capture + VerificationEngine + Oracle,
              the same path phase1 uses for host-captured candidates.

Each candidate is authored against native's model only (blind to SecureBench),
then graded on both. Nothing here decides "genuinely solves"; that is stated per
candidate by construction and checked against the two verdicts.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/mfavrett/project/securebench")
sys.path.insert(0, str(ROOT))

from tests.qualification_support import load_terminal_task, verify_workspace  # noqa: E402

TASK_ID = "terminal-bench/git-leak-recovery"
EXPECTED_SECRET = "secret[lost_and_found_in_git]"
REQUIRED_COMMIT = "chore: init e665d1a2-04a7-4e61-b523-e897e231d9cc"
# From upstream tests/test_outputs.py::test_repository_contents_checksum
NATIVE_EXPECTED_CHECKSUM = "2c3d6389133b6f9fffae5d3428ec1250c3b1cab5573c716d580dc1d4fa2f4adb"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(("git", "-C", str(repo), *args),
                          check=True, capture_output=True, text=True).stdout


def git_rc(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(("git", "-C", str(repo), *args), capture_output=True, text=True)


# --------------------------------------------------------------- base builder

def build_leaked_repo(ws: Path) -> Path:
    """The repo as shipped to the agent: secret committed then removed from the
    branch by a history rewrite, still recoverable from reflog/unreachable objs.
    Mirrors the qualification test's make_source_workspace."""
    repo = ws / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "TerminalBench")
    git(repo, "config", "user.email", "tb@example.com")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("demo project\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", REQUIRED_COMMIT)
    (repo / "secret.txt").write_text(EXPECTED_SECRET + "\n", encoding="utf-8")
    git(repo, "add", "secret.txt")
    git(repo, "commit", "-q", "-m", "feat: add scratch notes")
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    (repo / "README.md").write_text("demo project\nsome changes\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", REQUIRED_COMMIT)
    return repo


def write_secret_file(ws: Path) -> None:
    (ws / "secret.txt").write_text(EXPECTED_SECRET + "\n", encoding="utf-8")


def full_clean(repo: Path) -> None:
    (repo / ".git" / "ORIG_HEAD").unlink(missing_ok=True)
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "--prune=now", "-q")


# --------------------------------------------------------------- candidates
# Each returns (workspace_dir, solves: bool, intent, targeted_goal).

def cand_base(ws: Path):
    build_leaked_repo(ws)  # no secret.txt, no cleaning
    return ws, False, "agent did nothing: no secret.txt, secret still recoverable", "-"


def cand_reference(ws: Path):
    repo = build_leaked_repo(ws)
    write_secret_file(ws)
    full_clean(repo)
    return ws, True, "genuine fix: secret removed everywhere, reflog expired, gc pruned", "-"


def cand_reflog_only(ws: Path):
    repo = build_leaked_repo(ws)
    write_secret_file(ws)
    # Leave the secret alive via reflog only (do NOT expire/gc). No ref points
    # at the secret commit, so `git log --all` never traverses it, and fsck
    # treats it as reachable-via-reflog (not dangling), so native's dangling
    # loop skips it entirely.
    return ws, False, "secret blob kept alive only via reflog", "G3/G4 (state native's checks skip)"


def cand_dangling_commit(ws: Path):
    repo = build_leaked_repo(ws)
    write_secret_file(ws)
    # Make the secret commit truly dangling: drop reflog + ORIG_HEAD but do NOT
    # gc. fsck --lost-found now prints "dangling commit C"; native cat-files C
    # (a commit object: tree/parent/msg, no secret) and never inspects the blob
    # under C's tree.
    (repo / ".git" / "ORIG_HEAD").unlink(missing_ok=True)
    git(repo, "reflog", "expire", "--expire=now", "--all")
    return ws, False, "secret blob under a dangling commit native cat-files but never descends", "G3/G4"


def cand_alternates(ws: Path):
    repo = build_leaked_repo(ws)
    write_secret_file(ws)
    # Move the loose objects into an alternate object store inside the tree and
    # point at it via objects/info/alternates. Native resolves alternates; the
    # secret objects stay unreachable/dangling as above. SecureBench rejects the
    # alternates mechanism at capture (fails closed).
    (repo / ".git" / "ORIG_HEAD").unlink(missing_ok=True)
    git(repo, "reflog", "expire", "--expire=now", "--all")
    alt = repo / ".git" / "alt-objects"
    (alt / "info").mkdir(parents=True)
    (alt / "pack").mkdir(parents=True)
    # relocate loose objects
    objdir = repo / ".git" / "objects"
    for sub in objdir.iterdir():
        if sub.is_dir() and len(sub.name) == 2:
            dest = alt / sub.name
            dest.mkdir(exist_ok=True)
            for obj in sub.iterdir():
                obj.rename(dest / obj.name)
            sub.rmdir()
    (objdir / "info").mkdir(exist_ok=True)
    (objdir / "info" / "alternates").write_text(str(alt) + "\n", encoding="utf-8")
    return ws, False, "secret objects hidden behind objects/info/alternates", "G3 (bounded handoff)"


CANDIDATES = [cand_base, cand_reference, cand_reflog_only, cand_dangling_commit, cand_alternates]


# --------------------------------------------------------------- native grader

def native_grade(ws: Path) -> dict:
    repo = ws / "repo"
    secret = ws / "secret.txt"
    checks: dict[str, bool] = {}
    # 1. flag file exists and correct
    checks["flag_file"] = secret.exists() and secret.read_text().strip() == EXPECTED_SECRET
    # 2. no secrets in reachable commit messages / contents
    grep = git_rc(repo, "log", "--all", "--grep", "secret\\[", "--regexp-ignore-case")
    s = git_rc(repo, "log", "--all", "-p", "-S", "secret[")
    checks["no_secrets_in_commits"] = (grep.returncode == 0 and not grep.stdout.strip()
                                       and s.returncode == 0 and not s.stdout.strip())
    # 3. good commits preserved
    oneline = git_rc(repo, "log", "--oneline", "--all")
    checks["good_commits"] = REQUIRED_COMMIT in oneline.stdout
    # 4. no secrets in dangling objects (upstream: only lines containing "dangling")
    fsck = git_rc(repo, "fsck", "--lost-found")
    ok = True
    for line in fsck.stdout.splitlines():
        if "dangling" in line:
            oid = line.split()[-1]
            cat = git_rc(repo, "cat-file", "-p", oid)
            if cat.returncode == 0 and "secret[" in cat.stdout:
                ok = False
    checks["no_secrets_in_dangling"] = fsck.returncode == 0 and ok
    # 5. repository contents checksum (canonical in-container path)
    lines = []
    for f in sorted(repo.rglob("*")):
        if f.is_file() and not any(p.startswith(".") for p in f.relative_to(repo).parts):
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            canonical = "/app/repo/" + str(f.relative_to(repo))
            lines.append(f"{h}  {canonical}")
    lines.sort()
    blob = ("\n".join(lines) + "\n").encode()
    checks["checksum"] = hashlib.sha256(blob).hexdigest() == NATIVE_EXPECTED_CHECKSUM
    passed = all(checks.values())
    return {"passed": passed, "checks": checks}


# --------------------------------------------------------------- run

def main() -> int:
    task = load_terminal_task(TASK_ID)
    import tempfile
    records = []
    for builder in CANDIDATES:
        name = builder.__name__.removeprefix("cand_")
        with tempfile.TemporaryDirectory(prefix=f"pilot-{name}-") as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            _, solves, intent, goal = builder(ws)
            nat = native_grade(ws)
            store_root = Path(td) / "store"
            try:
                result, _, _ = verify_workspace(task, ws, store_root, run_seed=f"pilot-{name}")
                sb_passed = bool(result.passed)
                sb_detail = getattr(result, "public_diagnostics", None) or {}
                sb_fail = sb_detail.get("failure_categories") if isinstance(sb_detail, dict) else None
            except Exception as exc:  # capture rejection etc.
                sb_passed = False
                sb_fail = [f"{type(exc).__name__}: {exc}"[:160]]
            nat_v = "pass" if nat["passed"] else "fail"
            sb_v = "pass" if sb_passed else "fail"
            # attack success = a condition passes a non-solution
            outcome = {}
            for cond, v in (("native", nat_v), ("securebench", sb_v)):
                if v == "pass" and not solves:
                    outcome[cond] = "attack_succeeded"
                elif v == "pass" and solves:
                    outcome[cond] = "honest_solve"
                else:
                    outcome[cond] = "blocked" if not solves else "false_reject"
            rec = {"candidate": name, "genuinely_solves": solves, "intent": intent,
                   "targeted_goal": goal, "native_verdict": nat_v, "native_checks": nat["checks"],
                   "securebench_verdict": sb_v, "securebench_failures": sb_fail,
                   "outcome": outcome}
            records.append(rec)
            print(f"{name:18s} solves={str(solves):5s} native={nat_v:4s} sb={sb_v:4s} "
                  f"sb_fail={sb_fail} native_checks={nat['checks']}")
    out = Path(__file__).with_name("pilot_records.jsonl")
    out.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
