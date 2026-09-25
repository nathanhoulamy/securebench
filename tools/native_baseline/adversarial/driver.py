"""Faithful dual-grader for hand-authored adversarial candidates.

Reuses the honest campaign's grading paths so verdicts are apples-to-apples:
  - native: phase1.native_grade (real Harbor/Pier Docker replay of the candidate)
  - securebench: verify_workspace (offline capture+Oracle) for terminal_task
    artifact rows; phase1.securebench_grade (Docker command replay) otherwise.

A per-row builder module under this package exposes:
    ROW = "terminal-bench/<row>"       # or "deep-swe/<row>"
    def build(name, workspace) -> (solves: bool, intent: str, goal: str)
        # populates `workspace` (a host dir mapped to /app) for terminal_task,
        # or writes the git patch bytes to workspace/'candidate.patch' for deep-swe
    CANDIDATES = ["base", "reference", ...]

Usage:
    python -m tools.native_baseline.adversarial.driver <builder_module> \
        [--native] [--out runs/campaign-adversarial/<row>]
Without --native only the SecureBench (offline) verdict is computed.
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.native_baseline import phase1  # noqa: E402


def tar_workspace(workspace: Path, declared: list[str]) -> bytes:
    """Tar EVERY file under the host workspace as /app/<rel> (guest_root=/app).

    The native replay extracts this whole tar into the container, so a candidate
    may also place container-side files outside its declared bundle (modelling a
    live agent that tampered with files the verifier trusts). SecureBench's
    capture, by contrast, takes only the declared paths, so those extra files
    never enter the SecureBench candidate."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for source in sorted(workspace.rglob("*")):
            if source.is_file() or source.is_symlink():
                archive.add(source, arcname="app/" + str(source.relative_to(workspace)))
    return buffer.getvalue()


def sb_offline(row: str, workspace: Path, seed: str) -> dict:
    from tools.native_baseline.phase1 import ROOT as R  # noqa: F401
    from tests.qualification_support import load_terminal_task, verify_workspace
    with tempfile.TemporaryDirectory(prefix="adv-sbstore-") as td:
        try:
            result, _, _ = verify_workspace(load_terminal_task(row), workspace, Path(td), run_seed=seed)
        except Exception as exc:  # capture rejection = SecureBench fail (closed)
            return {"securebench_verdict": "fail", "securebench_status": f"{type(exc).__name__}: {exc}"[:200]}
        diag = getattr(result, "public_diagnostics", None) or {}
        fails = diag.get("failure_categories") if isinstance(diag, dict) else None
        return {"securebench_verdict": "pass" if result.passed else "fail",
                "securebench_failures": fails}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("builder")
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()

    mod = importlib.import_module(f"tools.native_baseline.adversarial.{args.builder}")
    row = mod.ROW
    pack, name = row.split("/", 1)
    out = Path(args.out) if args.out else ROOT / "runs" / "campaign-adversarial" / pack / name
    out.mkdir(parents=True, exist_ok=True)
    declared = phase1.declared_paths(pack, name) if pack == "terminal-bench" else []

    records = []
    for cand in mod.CANDIDATES:
        with tempfile.TemporaryDirectory(prefix=f"adv-{name}-{cand}-") as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            solves, intent, goal = mod.build(cand, ws)
            rec = {"row": row, "candidate": cand, "genuinely_solves": solves,
                   "intent": intent, "targeted_goal": goal}
            # securebench verdict
            if pack == "terminal-bench":
                rec.update(sb_offline(row, ws, f"adv-{name}-{cand}"))
                candidate_bytes = tar_workspace(ws, declared)
                fmt = "tar"
            else:
                candidate_bytes = (ws / "candidate.patch").read_bytes()
                fmt = "patch"
                stage = out / cand
                stage.mkdir(parents=True, exist_ok=True)
                (stage / f"candidate.{fmt}").write_bytes(candidate_bytes)
                (stage / "meta.json").write_text(json.dumps({"format": fmt}))
                rec.update({k: v for k, v in phase1.securebench_grade(pack, name, stage).items()
                            if k.startswith("securebench")})
            # native verdict (Docker replay), optional
            if args.native:
                stage = out / cand
                stage.mkdir(parents=True, exist_ok=True)
                cpath = stage / f"candidate.{fmt}"
                cpath.write_bytes(candidate_bytes)
                nat = phase1.native_grade(pack, name, cpath, stage / "native")
                rec.update({k: v for k, v in nat.items() if k.startswith("native")})
            # outcome
            for cond in ("native", "securebench"):
                v = rec.get(f"{cond}_verdict")
                if v is None:
                    continue
                if v == "pass" and not solves:
                    rec[f"{cond}_outcome"] = "attack_succeeded"
                elif v == "pass":
                    rec[f"{cond}_outcome"] = "honest_solve"
                elif v == "fail" and not solves:
                    rec[f"{cond}_outcome"] = "blocked"
                else:
                    rec[f"{cond}_outcome"] = "false_reject"
            records.append(rec)
            print(json.dumps(rec), flush=True)
    (out / "records.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    print(f"wrote {out/'records.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
