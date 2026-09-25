"""Phase 1: verifier agreement on fixed candidates (no model calls).

Steps (each resumable; outputs under ``runs/campaign/phase1/``)::

    python -m tools.native_baseline.phase1 record  [--pack P] [--rows ...]
    python -m tools.native_baseline.phase1 build
    python -m tools.native_baseline.phase1 native  [--pack P] [--rows ...]
    python -m tools.native_baseline.phase1 securebench [--pack P] [--rows ...]
    python -m tools.native_baseline.phase1 table

``record`` runs each row's qualification tests (the same selection as
``tools.qualify_rows`` plus the DeepSWE ``*_mutants_v2.py`` files) under the
candidate recorder plugin. ``build`` turns the recorded captures into
standalone candidates: a patch (DeepSWE, the raw workspace diff before
SecureBench's exclude_paths) or a tar of declared paths (Terminal-Bench).
``native`` replays each through the upstream harness (Pier / Harbor) with a
replay agent; ``securebench`` replays each through ``securebench.cli run`` with
``harness.type: command``. ``table`` writes ``phase1-agreement.csv``.

Candidate kinds are assigned from the test node id (see ``classify``) and can be
overridden in ``phase1/kind-overrides.csv`` (candidate_id,kind).
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import yaml

from tools.native_baseline.campaign_configs import CONFIGS, PACKS
from tools.qualify_rows import SHARED_BUNDLE_TESTS, SHARED_FOCUSED_TESTS, _focused_test_path

ROOT = Path(__file__).resolve().parents[2]
PHASE1 = ROOT / "runs" / "campaign" / "phase1"
NATIVE_VENV = ROOT / "runs" / "campaign" / "native-venv" / "bin"
UPSTREAM_TASKS = {
    "deep-swe": ROOT / "runs" / "campaign" / "upstream" / "deep-swe" / "tasks",
    "terminal-bench": ROOT / "runs" / "campaign" / "upstream" / "tb2",
}
MUTANT_FILES = {
    "cattrs-partial-structuring-recovery": "test_deepswe_cattrs_partial_structuring_recovery_mutants_v2.py",
    "fd-deterministic-multi-key-sorting": "test_deepswe_fd_deterministic_multi_key_sorting_mutants_v2.py",
    "updo-policy-alerting": "test_deepswe_updo_policy_alerting_mutants_v2.py",
}
# Linux MAX_ARG_STRLEN is 128 KiB per argv string.
ARG_CHUNK = 96 * 1024
MAX_ARGV_TOTAL = 1_500_000


def rows_for(pack: str) -> list[str]:
    path = PACKS[pack]["tasks"]
    return [json.loads(line)["id"].split("/", 1)[1] for line in path.read_text().splitlines()]


# ---------------------------------------------------------------- record

def test_commands(pack: str, row: str) -> list[list[str]]:
    base = [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
            "-p", "tools.native_baseline.candidate_recorder"]
    focused = _focused_test_path(row, pack)
    commands = []
    if focused is not None:
        command = base + [str(focused.relative_to(ROOT))]
        if row in SHARED_FOCUSED_TESTS or focused.name == "test_deepswe_first_wave_replay_v2.py":
            command += ["-k", row]
        commands.append(command)
    if pack == "terminal-bench":
        commands.append(base + [str(SHARED_BUNDLE_TESTS.relative_to(ROOT)), "-k", row])
    if row in MUTANT_FILES:
        commands.append(base + [f"tests/{MUTANT_FILES[row]}"])
    return commands


def cmd_record(args) -> None:
    for pack in args.packs:
        for row in args.rows or rows_for(pack):
            destination = PHASE1 / "recorded" / pack / row
            if (destination / "done.json").exists() and not args.force:
                continue
            shutil.rmtree(destination, ignore_errors=True)
            destination.mkdir(parents=True)
            env = dict(os.environ, CAMPAIGN_CANDIDATE_DIR=str(destination),
                       SECUREBENCH_DOCKER_INTEGRATION="1", PYTHONPATH=str(ROOT))
            summaries = []
            for command in test_commands(pack, row):
                started = time.time()
                completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
                tail = (completed.stdout + completed.stderr)[-4000:]
                summaries.append({"command": " ".join(command[3:]), "exit": completed.returncode,
                                  "seconds": round(time.time() - started, 1), "tail": tail})
                print(f"[record] {pack}/{row}: exit={completed.returncode} "
                      f"{tail.strip().splitlines()[-1] if tail.strip() else ''}", flush=True)
            (destination / "done.json").write_text(json.dumps(summaries, indent=2))


# ---------------------------------------------------------------- build

MALICIOUS = re.compile(
    r"malicious|forg|attack|symlink|oversiz|directory\]|hostile|credential|flood|"
    r"claim|verdict|nul_|nul\b|invalid_utf8|pickle|traversal|alternates|fork|"
    r"early_cancel|pipe_holder|trailing_claim|duplicate_key|duplicate_header",
    re.IGNORECASE,
)
MUTANT = re.compile(
    r"mutant|incomplete|dropping|missing_rewriter|rejects|reject|fails|wrong|"
    r"semantic|regress|missing|partial|off_by|below|above|truncat|case_|swap|"
    r"shift|stale|unsorted|extra|lower|second_line|leading|trailing|empty|"
    r"whitespace_only|non_|not_|zero|negative|nan|infinite|reversed|corrupt",
    re.IGNORECASE,
)
BASE = re.compile(r"base", re.IGNORECASE)
REFERENCE = re.compile(r"reference|gold|accept|passes|variant|alternate|valid", re.IGNORECASE)


def classify(nodeid: str, rejected: bool, in_test_verdict: str | None = None) -> str:
    """Kind from the qualification test's own expectation, which every row passed.

    A candidate its test accepts is an honest (reference-equivalent) answer, even
    when it carries ignored decorations such as a forged verdict line. A candidate
    its test rejects is a mutant, or malicious when the test names an attack.
    Name patterns only split rejected candidates and break ties when the recorded
    verdict is missing or an infrastructure error.
    """
    name = nodeid.split("::", 1)[-1]
    # A parametrised test names the candidate in its id; prefer that over the
    # function name (e.g. "..._reject_mutants_and_claims[sequential_mutant]").
    param = re.search(r"\[(.*)\]", name)
    if param:
        name = param.group(1) + " " + name.split("[", 1)[0]
        name = param.group(1) if (MALICIOUS.search(param.group(1)) or MUTANT.search(param.group(1))) else name
    base_like = bool(re.search(r"base|pinned_image_ships|command_agent_smoke", name))
    if in_test_verdict == "passed":
        return "reference"
    if rejected:
        return "base" if base_like and not MALICIOUS.search(name) else "malicious"
    if in_test_verdict == "failed":
        if MALICIOUS.search(name):
            return "malicious"
        return "base" if base_like else "mutant"
    if MALICIOUS.search(name):
        return "malicious"
    if BASE.search(name) and not REFERENCE.search(name.replace("base_", "")):
        return "base"
    if MUTANT.search(name):
        return "mutant"
    if REFERENCE.search(name):
        return "reference"
    return "malicious" if rejected else "unclassified"


def _blob(recorded: Path, digest: str) -> bytes:
    return (recorded / "blobs" / digest.removeprefix("sha256:")).read_bytes()


def _bundle_tar(recorded: Path, payload: dict) -> bytes:
    """Rebuild the declared files of a stored file_bundle as a tar at guest paths."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        def add_file(path: str, content: bytes, mode: int) -> None:
            info = tarfile.TarInfo(path.lstrip("/"))
            info.size = len(content)
            info.mode = mode & 0o7777 or 0o644
            archive.addfile(info, io.BytesIO(content))

        def add_dir(path: str, mode: int = 0o755) -> None:
            info = tarfile.TarInfo(path.lstrip("/"))
            info.type = tarfile.DIRTYPE
            info.mode = mode
            archive.addfile(info)

        def add_nodes(prefix: str, nodes) -> None:
            for node in nodes:
                path = f"{prefix}/{node['path']}" if node.get("path") else prefix
                kind = node.get("kind")
                if kind in ("directory", "dir"):
                    add_dir(path, node.get("mode", 0o755))
                elif kind in ("regular_file", "file"):
                    add_file(path, _blob(recorded, node["blob"]), node.get("mode", 0o644))
                elif kind == "symlink":
                    info = tarfile.TarInfo(path.lstrip("/"))
                    info.type = tarfile.SYMTYPE
                    info.linkname = node["target"]
                    archive.addfile(info)
                else:
                    raise ValueError(f"unknown tree node kind {kind!r}")

        for entry in payload["entries"]:
            if entry["kind"] == "regular_file":
                add_file(entry["source_path"], _blob(recorded, entry["blob"]), entry.get("mode", 0o644))
            else:
                add_dir(entry["source_path"])
                add_nodes(entry["source_path"], entry["nodes"])
    return buffer.getvalue()


def cmd_build(args) -> None:
    rows_out = []
    overrides = {}
    override_path = PHASE1 / "kind-overrides.csv"
    if override_path.exists():
        with override_path.open() as handle:
            overrides = {r["candidate_id"]: r["kind"] for r in csv.DictReader(handle)}
    for pack in PACKS:
        for row in rows_for(pack):
            recorded = PHASE1 / "recorded" / pack / row
            if not (recorded / "records.jsonl").exists():
                continue
            events = [json.loads(line) for line in (recorded / "records.jsonl").read_text().splitlines()]
            payloads = {e["candidate_digest"]: e for e in events if e["kind"] == "put_candidate"}
            verdicts = {}
            for e in events:
                if e["kind"] == "verify":
                    verdicts[(e["nodeid"], e["candidate_digest"])] = e["status"]
            seen: dict[str, str] = {}
            per_node: dict[str, int] = {}
            for e in events:
                if e["kind"] not in ("capture", "capture_rejected"):
                    continue
                nodeid = e["nodeid"] or "unknown"
                per_node[nodeid] = per_node.get(nodeid, 0) + 1
                rejected = e["kind"] == "capture_rejected"
                if e["candidate_type"] == "git_patch":
                    blob = e.get("raw_patch_blob")
                    if blob is None:
                        continue
                    content = _blob(recorded, blob)
                    suffix = "patch"
                else:
                    if rejected:
                        tree = e.get("tree")
                        if not tree or str(tree).startswith("unrecorded"):
                            continue
                        content = (recorded / "trees" / f"{tree}.tar").read_bytes()
                    else:
                        content = _bundle_tar(recorded, payloads[e["candidate_digest"]]["payload"])
                    suffix = "tar"
                digest = hashlib.sha256(content).hexdigest()
                short = nodeid.split("::", 1)[-1]
                candidate_id = f"{short}#{per_node[nodeid]}"
                if digest in seen:
                    # Same bytes from another test: grade once, keep the alias.
                    continue
                seen[digest] = candidate_id
                in_test = verdicts.get((nodeid, e.get("candidate_digest")))
                kind = overrides.get(f"{row}:{candidate_id}") or classify(nodeid, rejected, in_test)
                directory = PHASE1 / "candidates" / pack / row / digest[:16]
                directory.mkdir(parents=True, exist_ok=True)
                (directory / f"candidate.{suffix}").write_bytes(content)
                meta = {
                    "pack": pack, "task": row, "candidate_id": candidate_id,
                    "candidate_kind": kind, "nodeid": nodeid, "sha256": digest,
                    "format": suffix, "bytes": len(content),
                    "recorded_capture": "rejected" if rejected else "captured",
                    "recorded_error": e.get("error"),
                    "recorded_in_test_verdict": verdicts.get((nodeid, e.get("candidate_digest"))),
                }
                (directory / "meta.json").write_text(json.dumps(meta, indent=2))
                rows_out.append({**meta, "dir": str(directory.relative_to(ROOT))})
    with (PHASE1 / "candidates.csv").open("w", newline="") as handle:
        fields = ["pack", "task", "candidate_kind", "candidate_id", "sha256", "format", "bytes",
                  "recorded_capture", "recorded_in_test_verdict", "nodeid", "dir"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_out)
    print(f"[build] {len(rows_out)} distinct candidates")


def candidate_dirs(args):
    for pack in args.packs:
        for row in args.rows or rows_for(pack):
            base = PHASE1 / "candidates" / pack / row
            if base.is_dir():
                for directory in sorted(base.iterdir()):
                    if (directory / "meta.json").exists():
                        yield pack, row, directory


# ---------------------------------------------------------------- native

def native_grade(pack: str, row: str, candidate: Path, out: Path) -> dict:
    """Replay one candidate through the upstream harness; return verdict fields."""
    task_dir = UPSTREAM_TASKS[pack] / row
    if pack == "deep-swe":
        cli = NATIVE_VENV / "pier"
        agent = "tools.native_baseline.replay_agents:PierPatchReplayAgent"
    else:
        cli = NATIVE_VENV / "harbor"
        agent = "tools.native_baseline.replay_agents:HarborBundleReplayAgent"
    command = [str(cli), "run", "-p", str(task_dir), "--agent-import-path", agent,
               "--ak", f"candidate={candidate}", "-e", "docker", "-o", str(out),
               "-n", "1", "-y", "-q"]
    if pack == "terminal-bench":
        command += ["--ak", "clear=" + ",".join(declared_paths(pack, row))]
    started = time.time()
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                               env=dict(os.environ, PYTHONPATH=str(ROOT)))
    (out / "cli.log").parent.mkdir(parents=True, exist_ok=True)
    (out / "cli.log").write_text(completed.stdout[-20000:] + "\n--- stderr\n" + completed.stderr[-20000:])
    return {"native_seconds": round(time.time() - started, 1), **read_native_trial(out)}


def read_native_trial(out: Path) -> dict:
    trials = [p for p in out.glob("*/*/result.json")]
    if len(trials) != 1:
        return {"native_verdict": "infrastructure_error", "native_error": f"{len(trials)} trial results"}
    result = json.loads(trials[0].read_text())
    trial = trials[0].parent
    reward = None
    reward_json = trial / "verifier" / "reward.json"
    reward_txt = trial / "verifier" / "reward.txt"
    detail = {}
    if reward_json.exists():
        detail = json.loads(reward_json.read_text())
        reward = detail.get("reward")
    elif reward_txt.exists():
        try:
            reward = float(reward_txt.read_text().strip())
        except ValueError:
            reward = None
    exception = result.get("exception_info")
    if reward is None:
        name = (exception or {}).get("exception_type") if isinstance(exception, dict) else exception
        return {"native_verdict": "infrastructure_error", "native_error": str(name)[:300],
                "native_trial": (str(trial.relative_to(ROOT)) if trial.is_relative_to(ROOT) else str(trial))}
    verdict = "pass" if float(reward) >= 1.0 else "fail"
    return {"native_verdict": verdict, "native_reward": reward,
            "native_detail": json.dumps(detail, sort_keys=True) if detail else "",
            "native_error": "" if not exception else str(exception)[:300],
            "native_trial": (str(trial.relative_to(ROOT)) if trial.is_relative_to(ROOT) else str(trial))}


def _pool(args, items, fn) -> None:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(fn, items))


def cmd_native(args) -> None:
    def one(item):
        pack, row, directory = item
        verdict_path = directory / "native.json"
        if verdict_path.exists() and not args.force:
            return
        candidate = next(directory.glob("candidate.*"))
        out = directory / "native"
        shutil.rmtree(out, ignore_errors=True)
        verdict = native_grade(pack, row, candidate, out)
        verdict_path.write_text(json.dumps(verdict, indent=2))
        print(f"[native] {pack}/{row}/{directory.name}: {verdict['native_verdict']}", flush=True)

    _pool(args, list(candidate_dirs(args)), one)


# ---------------------------------------------------------------- securebench

def _chunks(content: bytes) -> list[str]:
    encoded = base64.b64encode(content).decode("ascii")
    # An empty candidate (base state) gets no chunks: the tester config rejects
    # empty argv strings, and printf with no arguments writes nothing.
    return [encoded[i:i + ARG_CHUNK] for i in range(0, len(encoded), ARG_CHUNK)]


def declared_paths(pack: str, row: str) -> list[str]:
    task = json.loads((CONFIGS / "securebench" / pack / row / "task.jsonl").read_text())
    return [entry["path"] for entry in task["verification"]["candidate"].get("files", [])]


def replay_command(fmt: str, content: bytes, clear: list[str] = ()) -> list[str]:
    if fmt == "patch":
        script = ('set -e; printf %s "$@" | base64 -d > /tmp/campaign-candidate.patch; '
                  'if [ -s /tmp/campaign-candidate.patch ]; then '
                  'git apply --whitespace=nowarn /tmp/campaign-candidate.patch; fi; '
                  'rm -f /tmp/campaign-candidate.patch')
    else:
        # The candidate replaces its declared paths (see ISSUES I-31).
        removal = "".join(f"rm -rf -- '{p}'; " for p in clear)
        script = f'set -e; {removal}printf %s "$@" | base64 -d | tar --no-same-owner -xpf - -C /'
    return ["sh", "-c", script, "sh", *_chunks(content)]


def securebench_grade(pack: str, row: str, directory: Path) -> dict:
    meta = json.loads((directory / "meta.json").read_text())
    candidate = next(directory.glob("candidate.*"))
    content = candidate.read_bytes()
    clear = declared_paths(pack, row) if meta["format"] == "tar" else []
    command = replay_command(meta["format"], content, clear)
    if sum(len(part) for part in command) > MAX_ARGV_TOTAL:
        if meta["format"] == "tar":
            return host_capture_grade(pack, row, directory, content)
        return {"securebench_verdict": "n/a", "securebench_error": "candidate exceeds argv replay bound"}
    campaign = yaml.safe_load((CONFIGS / "securebench" / pack / row / "config.yaml").read_text())
    config = {
        "schema_version": "1.0",
        "run": {"id": f"phase1-{pack}-{row}-{directory.name}",
                "output_dir": str(directory / "securebench"), "max_workers": 1},
        "benchmark": campaign["benchmark"],
        "docker": campaign["docker"],
        **({"network_policy": campaign["network_policy"]} if "network_policy" in campaign else {}),
        "harness": {"type": "command", "config": {
            "command": command, "task_file": "task.json",
            "timeout_seconds": campaign["harness"]["config"]["timeout_seconds"]}},
        **({"capture": campaign["capture"]} if "capture" in campaign else {}),
    }
    config_path = directory / "securebench-config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    out = directory / "securebench"
    shutil.rmtree(out, ignore_errors=True)
    started = time.time()
    completed = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "securebench.cli", "run",
         "--config", str(config_path), "--output-dir", str(out), "--quiet"],
        cwd=ROOT, capture_output=True, text=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cli.log").write_text(completed.stdout[-20000:] + "\n--- stderr\n" + completed.stderr[-20000:])
    seconds = round(time.time() - started, 1)
    results = out / "results.jsonl"
    if not results.exists():
        return {"securebench_verdict": "infrastructure_error", "securebench_seconds": seconds,
                "securebench_error": f"no results.jsonl (exit {completed.returncode})"}
    records = [json.loads(line) for line in results.read_text().splitlines() if line.strip()]
    if len(records) != 1:
        return {"securebench_verdict": "infrastructure_error", "securebench_seconds": seconds,
                "securebench_error": f"{len(records)} result records"}
    return {"securebench_seconds": seconds, **securebench_verdict(records[0])}


def host_capture_grade(pack: str, row: str, directory: Path, content: bytes) -> dict:
    """SecureBench capture + verification of a file_bundle from a host directory.

    Used only when a candidate is too large for the argv replay channel. Same
    code path as the qualification tests (tests/qualification_support.py):
    capture_file_bundle over the stopped /app tree, then VerificationEngine,
    under the campaign's memory limit. Flagged source=host-capture.
    """
    import tempfile
    sys.path.insert(0, str(ROOT))
    from securebench.tester_run import docker_memory_limit
    from tests.qualification_support import load_terminal_task, verify_workspace
    campaign = yaml.safe_load((CONFIGS / "securebench" / pack / row / "config.yaml").read_text())
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="campaign-hostcap-") as temporary:
        root = Path(temporary)
        (root / "fs").mkdir()
        subprocess.run(["tar", "--no-same-owner", "-xpf", "-", "-C", str(root / "fs")],
                       input=content, check=True)
        workspace = root / "fs" / "app"
        workspace.mkdir(exist_ok=True)
        try:
            with docker_memory_limit(campaign["docker"]["memory_limit"]):
                result, _, _ = verify_workspace(load_terminal_task(f"{pack}/{row}"), workspace,
                                                root / "store", run_seed=f"phase1-{directory.name}")
        except Exception as exc:  # capture rejection is a SecureBench verdict of fail
            name = type(exc).__name__
            if "Capture" in name:
                return {"securebench_verdict": "fail", "securebench_status": f"capture_rejected:{name}",
                        "securebench_source": "host-capture", "securebench_seconds": round(time.time() - started, 1)}
            return {"securebench_verdict": "infrastructure_error", "securebench_error": f"{name}: {exc}"[:300],
                    "securebench_source": "host-capture"}
    return {"securebench_seconds": round(time.time() - started, 1), "securebench_source": "host-capture",
            **securebench_verdict({"status": result.status, "passed": result.passed, "score": result.score})}


def securebench_verdict(record: dict) -> dict:
    status = str(record.get("status") or record.get("verification", {}).get("status"))
    passed = record.get("passed")
    if passed is None:
        passed = record.get("verification", {}).get("passed")
    if status in {"infrastructure_error", "error"}:
        verdict = "infrastructure_error"
    else:
        verdict = "pass" if passed else "fail"
    return {"securebench_verdict": verdict, "securebench_status": status,
            "securebench_score": record.get("score", record.get("verification", {}).get("score"))}


def cmd_securebench(args) -> None:
    def one(item):
        pack, row, directory = item
        verdict_path = directory / "securebench.json"
        if verdict_path.exists() and not args.force:
            return
        verdict = securebench_grade(pack, row, directory)
        verdict_path.write_text(json.dumps(verdict, indent=2))
        print(f"[securebench] {pack}/{row}/{directory.name}: {verdict['securebench_verdict']}", flush=True)

    _pool(args, list(candidate_dirs(args)), one)


# ---------------------------------------------------------------- table

def cmd_table(args) -> None:
    out_rows = []
    for pack in PACKS:
        for row in rows_for(pack):
            base = PHASE1 / "candidates" / pack / row
            if not base.is_dir():
                continue
            for directory in sorted(base.iterdir()):
                meta_path = directory / "meta.json"
                if not meta_path.exists():
                    continue
                meta = json.loads(meta_path.read_text())
                native = json.loads((directory / "native.json").read_text()) if (directory / "native.json").exists() else {}
                secure = json.loads((directory / "securebench.json").read_text()) if (directory / "securebench.json").exists() else {}
                nv = native.get("native_verdict", "pending")
                sv = secure.get("securebench_verdict", "pending")
                comparable = nv in {"pass", "fail"} and sv in {"pass", "fail"}
                out_rows.append({
                    "task": f"{pack}/{row}",
                    "candidate_kind": meta["candidate_kind"],
                    "candidate_id": meta["candidate_id"],
                    "native_verdict": nv,
                    "securebench_verdict": sv,
                    "agree": ("yes" if nv == sv else "no") if comparable else "n/a",
                    "sha256": meta["sha256"],
                    "recorded_in_test_verdict": meta.get("recorded_in_test_verdict"),
                    "native_reward": native.get("native_reward"),
                    "native_error": native.get("native_error"),
                    "securebench_status": secure.get("securebench_status"),
                    "securebench_source": secure.get("securebench_source", "command-replay") if secure else "",
                    "securebench_error": secure.get("securebench_error"),
                })
    path = ROOT / "runs" / "campaign" / "phase1-agreement.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out_rows[0]))
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"[table] {len(out_rows)} rows -> {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["record", "build", "native", "securebench", "table"])
    parser.add_argument("--pack", choices=list(PACKS), action="append", dest="packs")
    parser.add_argument("--rows", nargs="*")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    args.packs = args.packs or list(PACKS)
    {"record": cmd_record, "build": cmd_build, "native": cmd_native,
     "securebench": cmd_securebench, "table": cmd_table}[args.step](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
