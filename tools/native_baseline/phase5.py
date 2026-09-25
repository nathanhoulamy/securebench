"""Phase 5: cross-grade real agent outputs with the other condition's verifier.

    python -m tools.native_baseline.phase5 [--reps 1 2 ...] [--limit N]

* Condition B (SecureBench) candidates -> upstream verifier (Pier / Harbor
  replay agents), using the exact candidate SecureBench captured and graded.
* Condition A DeepSWE -> SecureBench (command-harness replay) of the committed
  diff upstream graded (``model.patch``); the working-tree diff is graded too
  when it differs, so "did not commit" is separable from "wrong code".
* Condition A Terminal-Bench -> SecureBench from ``final-state.tar`` (the
  declared paths tarred right after the agent exited). ``n/a`` when that tar is
  missing, or is empty while the native run passed.

Each graded pair lands in ``runs/campaign/phase5/<condition>/<pack>/rep<r>/<task>/``
(``<kind>/candidate.*``, ``native.json`` / ``securebench.json``), and
``runs/campaign/phase5-crossgrade.csv`` summarises them.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import tarfile
from pathlib import Path

from securebench.candidates.store import CandidateStore
from tools.native_baseline.phase1 import native_grade, securebench_grade

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "runs" / "campaign"
OUT = CAMPAIGN / "phase5"


def securebench_candidate(run_dir: Path, digest: str) -> tuple[str, bytes] | None:
    store = CandidateStore(run_dir / "artifacts")
    manifest = store.load_candidate(digest)
    payload = manifest.payload
    if manifest.type == "git_patch":
        return "patch", store.read_blob(payload["patch_blob"])
    if manifest.type != "file_bundle":
        return None
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        def add_file(path, content, mode):
            info = tarfile.TarInfo(path.lstrip("/"))
            info.size, info.mode = len(content), (mode & 0o7777) or 0o644
            archive.addfile(info, io.BytesIO(content))

        def add_dir(path, mode=0o755):
            info = tarfile.TarInfo(path.lstrip("/"))
            info.type, info.mode = tarfile.DIRTYPE, mode
            archive.addfile(info)

        for entry in payload["entries"]:
            if entry["kind"] == "regular_file":
                add_file(entry["source_path"], store.read_blob(entry["blob"]), entry.get("mode", 0o644))
                continue
            add_dir(entry["source_path"])
            for node in entry["nodes"]:
                path = f"{entry['source_path']}/{node['path']}"
                if node["kind"] == "directory":
                    add_dir(path, node.get("mode", 0o755))
                elif node["kind"] == "regular_file":
                    add_file(path, store.read_blob(node["blob"]), node.get("mode", 0o644))
                elif node["kind"] == "symlink":
                    info = tarfile.TarInfo(path.lstrip("/"))
                    info.type, info.linkname = tarfile.SYMTYPE, node["target"]
                    archive.addfile(info)
    return "tar", buffer.getvalue()


def stage(destination: Path, fmt: str, content: bytes, **meta) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"candidate.{fmt}").write_bytes(content)
    (destination / "meta.json").write_text(json.dumps({"format": fmt, **meta}, indent=2))
    return destination


def grade_native(pack, task, directory: Path) -> dict:
    if (directory / "native.json").exists():
        return json.loads((directory / "native.json").read_text())
    candidate = next(directory.glob("candidate.*"))
    out = directory / "native"
    shutil.rmtree(out, ignore_errors=True)
    result = native_grade(pack, task, candidate, out)
    (directory / "native.json").write_text(json.dumps(result, indent=2))
    return result


def grade_securebench(pack, task, directory: Path) -> dict:
    if (directory / "securebench.json").exists():
        return json.loads((directory / "securebench.json").read_text())
    result = securebench_grade(pack, task, directory)
    (directory / "securebench.json").write_text(json.dumps(result, indent=2))
    return result


def cross_grade(record: dict) -> list[dict]:
    condition, pack, task, rep = record["condition"], record["benchmark"], record["task"], record["rep"]
    run_dir = CAMPAIGN / condition / pack / f"rep{rep}" / task
    base = OUT / condition / pack / f"rep{rep}" / task
    common = {"condition": condition, "benchmark": pack, "task": task, "rep": rep,
              "original_status": record["status"], "original_passed": record.get("passed")}
    rows = []
    if record["status"] == "infrastructure_error":
        return [{**common, "candidate": "-", "cross_verdict": "n/a", "reason": "original run was an infrastructure error"}]
    if condition == "securebench":
        digest = record.get("candidate_digest")
        extracted = securebench_candidate(run_dir, digest) if digest else None
        if extracted is None:
            return [{**common, "candidate": "securebench", "cross_verdict": "n/a", "reason": "no stored candidate"}]
        directory = stage(base / "securebench-candidate", extracted[0], extracted[1], source=digest)
        result = grade_native(pack, task, directory)
        return [{**common, "candidate": "securebench-captured", "cross_verifier": "native",
                 "cross_verdict": result.get("native_verdict"), "reason": result.get("native_error", "")}]
    # condition == native
    if pack == "deep-swe":
        committed = ROOT / record["candidate_committed_patch"] if record.get("candidate_committed_patch") else None
        worktree = ROOT / record["candidate_worktree_patch"] if record.get("candidate_worktree_patch") else None
        candidates = []
        if committed is not None and committed.exists():
            candidates.append(("committed", committed.read_bytes()))
        else:
            candidates.append(("committed", b""))  # upstream graded the base state
        if worktree is not None and worktree.exists() and worktree.read_bytes() != candidates[0][1]:
            candidates.append(("worktree", worktree.read_bytes()))
        for kind, content in candidates:
            directory = stage(base / kind, "patch", content, source=kind)
            result = grade_securebench(pack, task, directory)
            rows.append({**common, "candidate": kind, "cross_verifier": "securebench",
                         "cross_verdict": result.get("securebench_verdict"),
                         "reason": result.get("securebench_error", "")})
        return rows
    final = ROOT / record["candidate_final_state"] if record.get("candidate_final_state") else None
    if final is None or not final.exists():
        return [{**common, "candidate": "final-state", "cross_verdict": "n/a",
                 "reason": "final-state.tar not captured"}]
    content = final.read_bytes()
    with tarfile.open(fileobj=io.BytesIO(content)) as archive:
        members = archive.getmembers()
    if not members and record.get("passed"):
        return [{**common, "candidate": "final-state", "cross_verdict": "n/a",
                 "reason": "native passed but no declared path existed at capture"}]
    directory = stage(base / "final-state", "tar", content, source="final-state.tar")
    result = grade_securebench(pack, task, directory)
    return [{**common, "candidate": "final-state", "cross_verifier": "securebench",
             "cross_verdict": result.get("securebench_verdict"), "reason": result.get("securebench_error", "")}]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reps", type=int, nargs="*")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    records = [json.loads(line) for line in (CAMPAIGN / "records.jsonl").read_text().splitlines()]
    records = [r for r in records if r["rep"] >= 1 and (not args.reps or r["rep"] in args.reps)]
    rows = []
    selected = records[: args.limit] if args.limit else records
    from concurrent.futures import ThreadPoolExecutor

    def safe(record):
        try:
            return cross_grade(record)
        except Exception as exc:  # keep going; the row says why
            return [{"condition": record["condition"], "benchmark": record["benchmark"], "task": record["task"],
                     "rep": record["rep"], "candidate": "-", "original_status": record["status"],
                     "original_passed": record.get("passed"), "cross_verdict": "n/a",
                     "reason": f"cross-grade error: {type(exc).__name__}: {exc}"[:300]}]

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(safe, selected))
    for index, (record, graded) in enumerate(zip(selected, results), 1):
        for row in graded:
            original = "pass" if row["original_passed"] else "fail"
            row["original_verdict"] = original if row["original_status"] != "infrastructure_error" else "n/a"
            row["agree"] = ("yes" if row["cross_verdict"] == original else "no") \
                if row["cross_verdict"] in {"pass", "fail"} else "n/a"
            rows.append(row)
            print(f"[{index}/{len(records)}] {row['condition']} {row['benchmark']}/{row['task']} rep{row['rep']} "
                  f"{row['candidate']}: original={row['original_verdict']} cross={row['cross_verdict']}", flush=True)
    fields = ["condition", "benchmark", "task", "rep", "candidate", "original_status", "original_verdict",
              "cross_verifier", "cross_verdict", "agree", "reason", "original_passed"]
    with (CAMPAIGN / "phase5-crossgrade.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
