"""Campaign driver: run the same agent under native (A) and SecureBench (B).

    python -m tools.native_baseline.campaign run --rep 1 [--tasks deep-swe/x terminal-bench/y ...]
          [--conditions native securebench] [--seed S] [--dry-run]
    python -m tools.native_baseline.campaign records      # rebuild records.jsonl from run dirs

Order: within a rep, tasks are shuffled with a seed derived from the rep, and
for each task the two conditions run back to back in a per-task random order,
so API drift over time does not systematically favour one condition.

Layout (one directory per run; attempts that end in infrastructure_error are
kept as ``attempt-<k>``)::

    runs/campaign/{native,securebench}/{deep-swe,terminal-bench}/rep<r>/<task>/

Each finished run gets ``record.json`` with the Phase 2 fields; ``records``
concatenates them into ``runs/campaign/records.jsonl``. Retries of
infrastructure errors (at most 2) are logged in ``runs/campaign/retries.jsonl``.

Credentials: the API key (or Claude subscription token) is read from ``.env``
by the child processes only (``--env-file``); this module never reads or prints it.

The agent and the results root come from ``CAMPAIGN_PROFILE`` (``profile.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from tools.native_baseline.campaign_configs import (
    AGENT_VERSION, CONFIGS, MODEL, PACKS, REASONING_EFFORT,
)
from tools.native_baseline.profile import PROFILE, SHARED

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = PROFILE.root
NATIVE_BIN = SHARED / "native-venv" / "bin"
ENV_FILE = ROOT / ".env"
UPSTREAM_TASKS = {
    "deep-swe": SHARED / "upstream" / "deep-swe" / "tasks",
    "terminal-bench": SHARED / "upstream" / "tb2",
}
MAX_RETRIES = 2

PRICE = PROFILE.price

# Codex-reported failures that are about the model API, not the agent's work.
API_ERROR_MARKERS = (
    "429", "rate limit", "Rate limit", "500 Internal", "502", "503", "504",
    "stream disconnected", "error sending request", "Connection reset",
    "exceeded retry limit", "insufficient_quota", "server_error",
)


def all_tasks() -> list[str]:
    tasks = []
    for pack, spec in PACKS.items():
        for line in spec["tasks"].read_text().splitlines():
            tasks.append(f"{pack}/{json.loads(line)['id'].split('/', 1)[1]}")
    return tasks


def schedule(rep: int, tasks: list[str], conditions: list[str], seed: int) -> list[tuple[str, str]]:
    rng = random.Random(f"{seed}:{rep}")
    order = list(tasks)
    rng.shuffle(order)
    plan = []
    for task in order:
        conds = list(conditions)
        rng.shuffle(conds)
        plan.extend((task, c) for c in conds)
    return plan


def run_dir(condition: str, task: str, rep: int) -> Path:
    pack, name = task.split("/", 1)
    return CAMPAIGN / condition / pack / f"rep{rep}" / name


# ------------------------------------------------------------------ usage

def codex_usage(lines) -> dict:
    """Sum turn.completed usage and find API-level errors in Codex JSON events."""
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
             "reasoning_tokens": 0}
    turns = 0
    started = False
    fatal_pending = False
    api_errors = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind in {"thread.started", "turn.started"}:
            started = True
        if kind == "turn.completed":
            turns += 1
            fatal_pending = False
            u = event.get("usage") or {}
            usage["input_tokens"] += int(u.get("input_tokens") or 0)
            usage["cached_input_tokens"] += int(u.get("cached_input_tokens") or 0)
            usage["output_tokens"] += int(u.get("output_tokens") or 0)
            usage["reasoning_tokens"] += int(u.get("reasoning_output_tokens") or 0)
        elif kind == "turn.failed":
            api_errors.append(json.dumps(event)[:500])
            fatal_pending = True
        elif kind == "error":
            message = json.dumps(event)[:500]
            # "Reconnecting... n/5" is Codex retrying on its own; it only
            # matters if the turn never completes afterwards.
            if any(marker in message for marker in API_ERROR_MARKERS):
                api_errors.append(message)
                fatal_pending = True
    usage["turns"] = turns
    usage["started"] = started
    # API trouble counts only when it ended the session: an error with no
    # completed turn after it, or an explicit turn.failed.
    usage["api_errors"] = api_errors if fatal_pending else []
    usage["api_errors_recovered"] = [] if fatal_pending else api_errors
    uncached = max(usage["input_tokens"] - usage["cached_input_tokens"], 0)
    usage["cost_usd"] = round(
        uncached * PRICE["input"] + usage["cached_input_tokens"] * PRICE["cached_input"]
        + usage["output_tokens"] * PRICE["output"], 6)
    return usage


# Claude Code failures that are about the model API or the subscription's
# usage limits, not the agent's work.
CLAUDE_API_ERROR_MARKERS = (
    "API Error", "usage limit", "hit your limit", "limit reached", "rate_limit", "rate limit",
    "overloaded",
    "authentication_error", "OAuth token", "Invalid API key", "Please run /login",
)


def claude_usage(lines) -> dict:
    """Usage and API-level errors from Claude Code stream-json events.

    The last ``result`` event carries the session totals; with background
    tasks (enabled upstream) there is one ``result`` per segment and only
    ``num_turns`` is per segment. Without one (the run was killed, e.g. by the
    timeout) the per-message usage is summed, which undercounts output: a
    lower bound.
    ``cost_usd`` is Claude Code's own API-price estimate; the campaign is billed
    to a subscription, so it is a notional figure.
    """
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "cache_creation_input_tokens": 0,
             "output_tokens": 0, "reasoning_tokens": 0}
    turns = 0
    started = False
    result = None
    result_turns = 0
    messages = {}
    api_errors = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            if any(marker in line for marker in CLAUDE_API_ERROR_MARKERS):
                api_errors.append(line[:500])
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            started = True
        elif kind == "assistant":
            message = event.get("message") or {}
            turns += 1
            if message.get("id") and message.get("usage"):
                messages[message["id"]] = message["usage"]  # one message spans several events
        elif kind == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            if info.get("status") not in (None, "allowed", "allowed_warning"):
                # A subscription limit refused the request; resetsAt is exact.
                api_errors.append(f"usage limit reached|{int(info.get('resetsAt') or 0)} "
                                  f"({info.get('rateLimitType')}, {info.get('status')})")
        elif kind == "result":
            result = event
            result_turns += int(event.get("num_turns") or 0)
    totals = (result or {}).get("usage") or {}
    if not totals and messages:
        totals = {key: sum(int(u.get(key) or 0) for u in messages.values())
                  for key in ("input_tokens", "cache_read_input_tokens",
                              "cache_creation_input_tokens", "output_tokens")}
    cached = int(totals.get("cache_read_input_tokens") or 0)
    created = int(totals.get("cache_creation_input_tokens") or 0)
    # Same convention as Codex: input_tokens includes the cached part.
    usage["input_tokens"] = int(totals.get("input_tokens") or 0) + cached + created
    usage["cached_input_tokens"] = cached
    usage["cache_creation_input_tokens"] = created
    usage["output_tokens"] = int(totals.get("output_tokens") or 0)
    usage["turns"] = result_turns if result else turns
    usage["started"] = started or bool(result and result.get("num_turns"))
    if result and result.get("is_error"):
        text = json.dumps(result)[:500]
        if any(marker in text for marker in CLAUDE_API_ERROR_MARKERS):
            api_errors.append(text)
    # Claude Code retries API errors itself; they count only when the session
    # ended in one (no successful result).
    ended_badly = result is None or bool(result.get("is_error"))
    usage["api_errors"] = api_errors if ended_badly else []
    usage["api_errors_recovered"] = [] if ended_badly else api_errors
    usage["cost_usd"] = round(float(result.get("total_cost_usd") or 0), 6) if result else None
    # Totals exist only in a result event; without one (timeout, or a bounded
    # SecureBench stdout that dropped it, Luna I-28) usage is unknown, as for Codex.
    usage["usage_known"] = result is not None
    usage["result_subtype"] = result.get("subtype") if result else None
    return usage


def agent_usage(lines) -> dict:
    return codex_usage(lines) if PROFILE.agent == "codex" else claude_usage(lines)


def base_record(condition, task, rep) -> dict:
    pack, name = task.split("/", 1)
    record = {"condition": condition, "benchmark": pack, "task": name, "rep": rep,
              "model": MODEL, "reasoning_effort": REASONING_EFFORT}
    if PROFILE.agent == "codex":
        record["codex_version"] = AGENT_VERSION
    else:
        record.update(agent=PROFILE.agent, agent_version=AGENT_VERSION, profile=PROFILE.name)
    return record


def finish(record: dict, usage: dict) -> dict:
    # Codex reports usage only on turn.completed; claude_usage decides for itself.
    record["usage_known"] = usage.get("usage_known", usage["turns"] > 0)
    record.update({
        "input_tokens": usage["input_tokens"], "cached_input_tokens": usage["cached_input_tokens"],
        "output_tokens": usage["output_tokens"], "reasoning_tokens": usage["reasoning_tokens"],
        "turns": usage["turns"], "cost_usd": usage["cost_usd"],
    })
    for key in ("cache_creation_input_tokens", "result_subtype"):
        if key in usage:
            record[key] = usage[key]
    if not usage["started"] and record["status"] != "infrastructure_error":
        # Same rule in both conditions: the agent never began a session (bad CLI
        # args, install failure, crash before the model was called).
        record["status"] = "infrastructure_error"
        record["error_class"] = "agent_not_started"
        return record
    if usage["api_errors"] and record["status"] != "passed":
        # Same rule in both conditions: a run cut short by the model API is infra.
        record["status"] = "infrastructure_error"
        record["error_class"] = "model_api"
        record["error_detail"] = usage["api_errors"][:3]
    return record


# ------------------------------------------------------------------ native (A)

def native_command(task: str, out: Path) -> list[str]:
    pack, name = task.split("/", 1)
    task_dir = UPSTREAM_TASKS[pack] / name
    common = ["-p", str(task_dir), "-m", PROFILE.native_model, "--ak", f"version={AGENT_VERSION}",
              "--ak", f"reasoning_effort={REASONING_EFFORT}", "-e", "docker", "-o", str(out),
              "-n", "1", "-y", "-q", "--env-file", str(ENV_FILE)]
    if pack == "deep-swe":
        base = tomllib.loads((task_dir / "task.toml").read_text())["metadata"]["base_commit_hash"]
        return [str(NATIVE_BIN / "pier"), "run", *common,
                "--agent-import-path", f"{PROFILE.native_agents}:{PROFILE.pier_agent}",
                "--ak", f"base_commit={base}"]
    row = json.loads((CONFIGS / "securebench" / pack / name / "task.jsonl").read_text())
    paths = ",".join(entry["path"] for entry in row["verification"]["candidate"]["files"])
    return [str(NATIVE_BIN / "harbor"), "run", *common,
            "--agent-import-path", f"{PROFILE.native_agents}:{PROFILE.harbor_agent}",
            "--ak", f"capture_paths={paths}"]


def _seconds(start, end) -> float | None:
    from datetime import datetime
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 1)


def native_record(task: str, rep: int, out: Path, wall: float, exit_code: int) -> dict:
    record = base_record("native", task, rep)
    record["wall_time_s"] = round(wall, 1)
    trials = list(out.glob("*/*/result.json"))
    if len(trials) != 1:
        record.update(status="infrastructure_error", passed=False, score=None,
                      error_class="harness", error_detail=f"{len(trials)} trial results, exit {exit_code}")
        return finish(record, agent_usage([]))
    trial = trials[0].parent
    result = json.loads(trials[0].read_text())
    record["trial_dir"] = str(trial.relative_to(ROOT))
    agent = result.get("agent_execution") or {}
    verifier = result.get("verifier") or {}
    record["agent_time_s"] = _seconds(agent.get("started_at"), agent.get("finished_at"))
    record["verify_time_s"] = _seconds(verifier.get("started_at"), verifier.get("finished_at"))
    reward = None
    detail = {}
    if (trial / "verifier" / "reward.json").exists():
        detail = json.loads((trial / "verifier" / "reward.json").read_text())
        reward = detail.get("reward")
    elif (trial / "verifier" / "reward.txt").exists():
        try:
            reward = float((trial / "verifier" / "reward.txt").read_text().strip())
        except ValueError:
            reward = None
    exception = result.get("exception_info") or {}
    exception_type = exception.get("exception_type") if isinstance(exception, dict) else str(exception)
    record["reward_detail"] = detail
    if reward is None or (isinstance(reward, (int, float)) and reward < 0):
        record.update(status="infrastructure_error", passed=False, score=None,
                      error_class=f"native:{exception_type or 'no_reward'}")
    else:
        passed = float(reward) >= 1.0
        record.update(status="passed" if passed else "failed", passed=passed, score=float(reward),
                      error_class=f"agent:{exception_type}" if exception_type else None)
    agent_log = trial / "agent" / PROFILE.native_log
    lines = agent_log.read_text(errors="replace").splitlines() if agent_log.exists() else []
    record["candidate_committed_patch"] = _rel(trial / "artifacts" / "model.patch")
    record["candidate_worktree_patch"] = _rel(trial / "agent" / "campaign" / "worktree.patch")
    record["candidate_final_state"] = _rel(trial / "agent" / "campaign" / "final-state.tar")
    return finish(record, agent_usage(lines))


def _rel(path: Path) -> str | None:
    return str(path.relative_to(ROOT)) if path.exists() else None


def child_env(**extra: str) -> dict[str, str]:
    env = dict(os.environ, **extra)
    if PROFILE.agent == "claude_code":
        # Subscription only: an API key in the shell would take precedence over
        # the OAuth token in .env and bill the API instead.
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(name, None)
        env["CLAUDE_FORCE_OAUTH"] = "1"  # Harbor: use CLAUDE_CODE_OAUTH_TOKEN
    return env


def run_native(task: str, rep: int, out: Path) -> dict:
    started = time.time()
    completed = subprocess.run(native_command(task, out), cwd=ROOT, capture_output=True, text=True,
                               env=child_env(PYTHONPATH=str(ROOT)))
    out.mkdir(parents=True, exist_ok=True)
    (out / "cli.log").write_text(completed.stdout[-50000:] + "\n--- stderr\n" + completed.stderr[-50000:])
    return native_record(task, rep, out, time.time() - started, completed.returncode)


# ------------------------------------------------------------------ securebench (B)

def securebench_record(task: str, rep: int, out: Path, wall: float, exit_code: int) -> dict:
    record = base_record("securebench", task, rep)
    record["wall_time_s"] = round(wall, 1)
    results = out / "results.jsonl"
    rows = [json.loads(l) for l in results.read_text().splitlines() if l.strip()] if results.exists() else []
    events = [json.loads(l) for l in (out / "campaign-events.jsonl").read_text().splitlines()] \
        if (out / "campaign-events.jsonl").exists() else []
    times = {}
    for event in events:
        times.setdefault(event["event"], event["t"])
        times[event["event"] + ":last"] = event["t"]
        if event["event"] == "producer_done":
            # "failed": the agent exited non-zero or timed out; nothing is captured (S-09).
            record["producer_status"] = event.get("status", "ok")
        elif event["event"] == "candidate_capture_done":
            record["capture_status"] = event.get("status")
            if event.get("reason"):
                record["capture_reason"] = event["reason"]
    if "producer_start" in times and "producer_done" in times:
        record["agent_time_s"] = round(times["producer_done"] - times["producer_start"], 1)
    if "candidate_capture_start" in times and "candidate_capture_done:last" in times:
        record["capture_time_s"] = round(times["candidate_capture_done:last"] - times["candidate_capture_start"], 1)
    if "verification_start" in times and "task_done" in times:
        record["verify_time_s"] = round(times["task_done"] - times["verification_start"], 1)
    if len(rows) != 1:
        record.update(status="infrastructure_error", passed=False, score=None,
                      error_class="harness", error_detail=f"{len(rows)} results, exit {exit_code}")
    else:
        row = rows[0]
        status = row.get("status")
        record.update(status=status, passed=bool(row.get("passed")), score=row.get("score"),
                      error_class=(row.get("public_diagnostics") or {}).get("failure_categories") or None)
        record["candidate_digest"] = (row.get("candidate") or {}).get("digest")
    raw = out / "campaign-agent-raw.jsonl"
    lines = [json.loads(l).get("line") or "" for l in raw.read_text().splitlines()] if raw.exists() else []
    return finish(record, agent_usage(lines))


def run_securebench(task: str, rep: int, out: Path) -> dict:
    pack, name = task.split("/", 1)
    config = CONFIGS / "securebench" / pack / name / "config.yaml"
    started = time.time()
    completed = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "tools.native_baseline.sb_run",
         "--config", str(config), "--output-dir", str(out), "--env-file", str(ENV_FILE), "--resume"],
        cwd=ROOT, capture_output=True, text=True, env=child_env(**PROFILE.agent_env))
    (out / "cli.log").write_text(completed.stdout[-50000:] + "\n--- stderr\n" + completed.stderr[-50000:])
    return securebench_record(task, rep, out, time.time() - started, completed.returncode)


# ------------------------------------------------------------------ driver

def _lock(out: Path) -> Path | None:
    """One driver per run directory: a pid lock beside it, taken over if stale."""
    lock = out.with_name(f".{out.name}.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            pid = int(lock.read_text().strip() or 0)
            if pid <= 0:
                raise ValueError("empty lock")  # e.g. created while the disk was full
            os.kill(pid, 0)
            return None  # another live driver owns this run
        except (ValueError, ProcessLookupError, PermissionError):
            lock.unlink(missing_ok=True)
            return _lock(out)
    with os.fdopen(fd, "w") as handle:
        handle.write(str(os.getpid()))
    return lock


def run_one(condition: str, task: str, rep: int) -> dict:
    out = run_dir(condition, task, rep)
    if (out / "record.json").exists():
        return json.loads((out / "record.json").read_text())
    lock = _lock(out)
    if lock is None:
        return {"status": "skipped-locked", "condition": condition, "task": task, "rep": rep}
    try:
        return _run_one_locked(condition, task, rep, out)
    finally:
        lock.unlink(missing_ok=True)


# Subscription usage limits: a run that ended on one is set aside and redone
# after the reset without using a retry, and no new run starts before then.
USAGE_LIMIT_MARKERS = ("usage limit", "hit your limit", "limit reached")
USAGE_LIMIT_DEFAULT_WAIT_S = 1800
_limit_until = 0.0


def usage_limit_reset(record: dict) -> float | None:
    """Reset time (epoch s) if the run ended on a subscription usage limit."""
    detail = " ".join(map(str, record.get("error_detail") or []))
    if record.get("error_class") != "model_api" or not any(m in detail for m in USAGE_LIMIT_MARKERS):
        return None
    import re
    stamp = re.search(r"limit reached\|(\d{10})", detail)
    if stamp and int(stamp.group(1)) < time.time():
        stamp = None  # stale or missing resetsAt  # "Claude AI usage limit reached|<epoch>"
    return float(stamp.group(1)) + 60 if stamp else time.time() + USAGE_LIMIT_DEFAULT_WAIT_S


def wait_for_usage_limit() -> None:
    while (remaining := _limit_until - time.time()) > 0:
        time.sleep(min(remaining, 60))


def _run_one_locked(condition: str, task: str, rep: int, out: Path) -> dict:
    global _limit_until
    if (out / "record.json").exists():
        return json.loads((out / "record.json").read_text())
    attempt = 0
    while attempt <= MAX_RETRIES:
        wait_for_usage_limit()
        if out.exists() and not (out / "record.json").exists() and any(out.iterdir()):
            # A crashed or infra attempt: keep it aside, start clean.
            shutil.move(str(out), str(out.with_name(f"{out.name}.attempt-{attempt}-{int(time.time())}")))
        out.mkdir(parents=True, exist_ok=True)
        record = (run_native if condition == "native" else run_securebench)(task, rep, out)
        record["attempt"] = attempt
        reset = usage_limit_reset(record)
        if reset is not None:
            _limit_until = max(_limit_until, reset)
            with (CAMPAIGN / "retries.jsonl").open("a") as handle:
                handle.write(json.dumps({"time": time.time(), "condition": condition, "task": task,
                                         "rep": rep, "attempt": attempt, "error_class": "usage_limit",
                                         "resume_after": reset,
                                         "error_detail": record.get("error_detail")}, default=str) + "\n")
            (out / "record.json").write_text(json.dumps(record, indent=2, default=str))
            shutil.move(str(out), str(out.with_name(f"{out.name}.usage-limit-{int(time.time())}")))
            print(f"usage limit: {condition} {task} set aside; pausing until "
                  f"{time.strftime('%H:%M', time.localtime(reset))}", flush=True)
            continue
        if record["status"] != "infrastructure_error" or attempt == MAX_RETRIES:
            (out / "record.json").write_text(json.dumps(record, indent=2, default=str))
            return record
        with (CAMPAIGN / "retries.jsonl").open("a") as handle:
            handle.write(json.dumps({"time": time.time(), "condition": condition, "task": task,
                                     "rep": rep, "attempt": attempt,
                                     "error_class": record.get("error_class"),
                                     "error_detail": record.get("error_detail")}, default=str) + "\n")
        (out / "record.json").write_text(json.dumps(record, indent=2, default=str))
        shutil.move(str(out), str(out.with_name(f"{out.name}.attempt-{attempt}-{int(time.time())}")))
        attempt += 1
    raise AssertionError("unreachable")


def cmd_run(args) -> None:
    tasks = args.tasks or all_tasks()
    plan = schedule(args.rep, tasks, args.conditions, args.seed)
    (CAMPAIGN / "schedules").mkdir(parents=True, exist_ok=True)
    (CAMPAIGN / "schedules" / f"rep{args.rep}-{int(time.time())}.json").write_text(json.dumps(plan))
    if args.dry_run:
        for index, (task, condition) in enumerate(plan, 1):
            print(f"{index:4d} {condition:12s} {task}")
        return
    # Workers take plan items in order, so the interleaving holds up to the
    # worker count. A memory budget (GB, upstream memory_mb per task) keeps
    # concurrent containers within host RAM.
    import threading
    from concurrent.futures import ThreadPoolExecutor
    budget = threading.Semaphore(args.memory_gb)

    def task_gb(task: str) -> int:
        pack, name = task.split("/", 1)
        row = tomllib.loads((UPSTREAM_TASKS[pack] / name / "task.toml").read_text())
        return max(1, -(-int(row["environment"]["memory_mb"]) // 1024))

    def work(item):
        index, (task, condition) = item
        need = min(task_gb(task), args.memory_gb)
        wait_for_usage_limit()
        for _ in range(need):
            budget.acquire()
        try:
            record = run_one(condition, task, args.rep)
        except Exception as exc:  # one run must never end the whole rep (see ISSUES I-28)
            print(f"[{index}/{len(plan)}] rep{args.rep} {condition:11s} {task}: DRIVER ERROR "
                  f"{type(exc).__name__}: {exc}", flush=True)
            return
        finally:
            for _ in range(need):
                budget.release()
        print(f"[{index}/{len(plan)}] rep{args.rep} {condition:11s} {task}: {record['status']} "
              f"score={record.get('score')} wall={record.get('wall_time_s')}s "
              f"tok={record.get('input_tokens')}/{record.get('output_tokens')} "
              f"cost=${record.get('cost_usd')}{'' if PRICE else ' (notional)'}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, enumerate(plan, 1)))
    cmd_records(args)


def cmd_repair(args) -> None:
    """Re-apply the current infra rule to retried attempts and restore any that
    were not infrastructure errors (the first such attempt is the counted run)."""
    for main in sorted(CAMPAIGN.glob("*/*/rep*/*/record.json")):
        out = main.parent
        if "." in out.name:
            continue
        attempts = sorted(out.parent.glob(f"{out.name}.attempt-*"), key=lambda d: int(d.name.rsplit("-", 1)[1]))
        for attempt in attempts:
            old_path = attempt / "record.json"
            if not old_path.exists():
                continue
            old = json.loads(old_path.read_text())
            if old.get("error_class") not in {"model_api"}:
                continue
            condition, task, rep = old["condition"], f"{old['benchmark']}/{old['task']}", old["rep"]
            rebuild = native_record if condition == "native" else securebench_record
            record = rebuild(task, rep, attempt, old.get("wall_time_s") or 0.0, 0)
            record["attempt"] = old.get("attempt", 0)
            if record["status"] == "infrastructure_error":
                continue
            record["note"] = "restored by repair: API error was recovered within the session"
            stamp = int(time.time())
            shutil.move(str(out), str(out.with_name(f"{out.name}.superseded-retry-{stamp}")))
            shutil.move(str(attempt), str(out))
            record = rebuild(task, rep, out, old.get("wall_time_s") or 0.0, 0)  # paths under the restored dir
            record["attempt"] = old.get("attempt", 0)
            record["note"] = "restored by repair: API error was recovered within the session"
            (out / "record.json").write_text(json.dumps(record, indent=2, default=str))
            with (CAMPAIGN / "retries.jsonl").open("a") as handle:
                handle.write(json.dumps({"time": time.time(), "condition": condition, "task": task, "rep": rep,
                                         "attempt": record["attempt"], "error_class": "repair:restored",
                                         "error_detail": f"{attempt.name} restored; retry superseded"}) + "\n")
            print(f"[repair] restored {condition} {task} rep{rep} from {attempt.name}: {record['status']}")
            break


def cmd_rebuild(args) -> None:
    """Re-derive every counted record.json with the current parser (verdicts must not change)."""
    for path in sorted(CAMPAIGN.glob("*/*/rep*/*/record.json")):
        out = path.parent
        if "." in out.name:
            continue
        old = json.loads(path.read_text())
        rebuild = native_record if old["condition"] == "native" else securebench_record
        new = rebuild(f"{old['benchmark']}/{old['task']}", old["rep"], out, old.get("wall_time_s") or 0.0, 0)
        for key in ("attempt", "note"):
            if key in old:
                new[key] = old[key]
        if (new["status"], new["score"]) != (old["status"], old["score"]):
            print(f"[rebuild] VERDICT CHANGED, kept old: {old['condition']} {old['task']} rep{old['rep']} "
                  f"{old['status']} -> {new['status']}")
            continue
        path.write_text(json.dumps(new, indent=2, default=str))
    cmd_records(args)


def cmd_records(args) -> None:
    records = []
    for path in sorted(CAMPAIGN.glob("*/*/rep*/*/record.json")):
        if "." in path.parent.name:
            # Retried attempts and runs set aside (``<task>.<reason>``); no task name has a dot.
            continue
        records.append(json.loads(path.read_text()))
    with (CAMPAIGN / "records.jsonl").open("w") as handle:
        for record in records:
            handle.write(json.dumps(record, default=str) + "\n")
    print(f"[records] {len(records)} -> {CAMPAIGN / 'records.jsonl'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="step", required=True)
    run = sub.add_parser("run")
    run.add_argument("--rep", type=int, required=True)
    run.add_argument("--tasks", nargs="*")
    run.add_argument("--conditions", nargs="+", default=["native", "securebench"],
                     choices=["native", "securebench"])
    run.add_argument("--seed", type=int, default=20260924)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--memory-gb", type=int, default=24,
                     help="total upstream memory_mb (GB) of concurrently running tasks")
    sub.add_parser("records")
    sub.add_parser("rebuild")
    sub.add_parser("repair")
    args = parser.parse_args()
    {"run": cmd_run, "records": cmd_records, "repair": cmd_repair, "rebuild": cmd_rebuild}[args.step](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
