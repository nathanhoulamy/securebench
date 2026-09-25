"""Aggregate the native-vs-SecureBench campaign into CSVs and REPORT.md.

    python -m tools.campaign_aggregate

Inputs (all under runs/campaign/): records.jsonl (Phase 4, reps >= 1),
phase1-agreement.csv, phase5-crossgrade.csv, retries.jsonl, and
docs/benchmark-conversions/f2p-audit/README.md for the DeepSWE subset.

Infrastructure errors are excluded from pass rates and counted separately.
Every table is reported for two DeepSWE scopes: all 30 rows, and the rows the
F2P audit found with no Weaker and no Missing upstream assertions.
Standard library only; bootstrap and permutation tests use a fixed seed.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "runs" / "campaign"
OUT = CAMPAIGN / "aggregate"
SEED = 20260925
BOOT = 10000
CONDITIONS = ("native", "securebench")
# The campaign was cut to 3 reps (360 runs) by user decision on 2026-09-25;
# 27 rep-5 runs made before that stay on disk but are not analysed.
REPS = (1, 2, 3)
# Rows whose upstream state cannot be rebuilt from the declared candidate files,
# so a cross-grade measures the replay, not the verifier (ISSUES I-34):
# upstream tests need a live service (kv-store-grpc gRPC on 5328, hf-model-inference
# Flask on 5000) or packages installed system-wide by the native agent
# (headless-terminal: upstream tells the agent to install into the system python).
STRUCTURAL_NA_PHASE5 = {
    "terminal-bench/kv-store-grpc": "upstream verifier needs a running gRPC server and system-wide grpcio",
    "terminal-bench/hf-model-inference": "upstream verifier needs a running Flask service on port 5000",
    "terminal-bench/headless-terminal": "native agent installs dependencies system-wide; not in the declared candidate",
}
STRUCTURAL_NA_PHASE1 = {k: v for k, v in STRUCTURAL_NA_PHASE5.items() if "headless" not in k}


def mark_structural(rows, table, task_key):
    for r in rows:
        task = task_key(r)
        if task in table:
            for key in list(r):
                if key in {"native_verdict", "securebench_verdict", "cross_verdict"}:
                    r[key + "_raw"] = r[key]
            if "cross_verdict" in r:
                r["cross_verdict"] = "n/a"
                r["reason"] = "not reconstructable: " + table[task]
            else:
                r["securebench_verdict"] = "n/a"
                r["agree"] = "n/a"
    return rows


# ------------------------------------------------------------------ inputs

def load_records() -> list[dict]:
    path = CAMPAIGN / "records.jsonl"
    if not path.exists():
        return []
    return [r for r in (json.loads(l) for l in path.read_text().splitlines() if l.strip()) if r["rep"] in REPS]


def f2p_flagged() -> set[str]:
    flagged = set()
    text = (ROOT / "docs" / "benchmark-conversions" / "f2p-audit" / "README.md").read_text()
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[1].isdigit():
            if int(cells[3]) > 0 or int(cells[5]) > 0:
                flagged.add(cells[0])
    return flagged


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as handle:
        return list(csv.DictReader(handle))


# ------------------------------------------------------------------ statistics

def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    return statistics.stdev(xs) if len(xs) > 1 else float("nan")


def bootstrap_ci(values, stat=mean, n=BOOT, seed=SEED):
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    draws = sorted(stat([rng.choice(values) for _ in values]) for _ in range(n))
    return draws[int(0.025 * n)], draws[int(0.975 * n) - 1]


def sign_flip_p(diffs, n=100000, seed=SEED):
    """Two-sided paired permutation test on the mean difference."""
    diffs = [d for d in diffs if d != 0] or [0.0]
    observed = abs(sum(diffs))
    if len(diffs) <= 20:
        count = total = 0
        for signs in product((1, -1), repeat=len(diffs)):
            total += 1
            count += abs(sum(s * d for s, d in zip(signs, diffs))) >= observed - 1e-12
        return count / total
    rng = random.Random(seed)
    count = sum(abs(sum(d if rng.random() < 0.5 else -d for d in diffs)) >= observed - 1e-12 for _ in range(n))
    return (count + 1) / (n + 1)


def wilcoxon(diffs):
    """Wilcoxon signed-rank (zeros dropped, average ranks, normal approximation with tie correction)."""
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)
    if n == 0:
        return {"W": 0.0, "n": 0, "p": 1.0}
    order = sorted(range(n), key=lambda i: abs(nonzero[i]))
    ranks = [0.0] * n
    i = 0
    ties = 0.0
    while i < n:
        j = i
        while j + 1 < n and abs(nonzero[order[j + 1]]) == abs(nonzero[order[i]]):
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    w_plus = sum(r for r, d in zip(ranks, nonzero) if d > 0)
    mu = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - ties / 48
    if var <= 0:
        return {"W": w_plus, "n": n, "p": 1.0}
    z = (w_plus - mu - math.copysign(0.5, w_plus - mu)) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    return {"W": w_plus, "n": n, "p": min(1.0, p)}


def cohen_kappa(pairs):
    pairs = [(a, b) for a, b in pairs if a in {"pass", "fail"} and b in {"pass", "fail"}]
    n = len(pairs)
    if n == 0:
        return float("nan"), {}
    counts = Counter(pairs)
    po = (counts[("pass", "pass")] + counts[("fail", "fail")]) / n
    pa = sum(1 for a, _ in pairs if a == "pass") / n
    pb = sum(1 for _, b in pairs if b == "pass") / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    return kappa, counts


def fmt(x, digits=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{digits}f}"


# ------------------------------------------------------------------ analyses

def scope_filter(scope: str, flagged: set[str]):
    def keep(benchmark: str, task: str) -> bool:
        return not (scope == "clean-f2p" and benchmark == "deep-swe" and task in flagged)
    return keep


def pass_rates(records, keep):
    per = defaultdict(list)
    infra = Counter()
    for r in records:
        if not keep(r["benchmark"], r["task"]):
            continue
        if r["status"] == "infrastructure_error":
            infra[(r["condition"], r["benchmark"])] += 1
            continue
        per[(r["benchmark"], r["task"], r["condition"])].append(1.0 if r.get("passed") else 0.0)
    return per, infra


def analyse(records, keep, label, lines, tables):
    per, infra = pass_rates(records, keep)
    tasks = sorted({(b, t) for b, t, _ in per})
    rows = []
    for b, t in tasks:
        row = {"scope": label, "benchmark": b, "task": t}
        for c in CONDITIONS:
            xs = per.get((b, t, c), [])
            row[f"{c}_n"], row[f"{c}_mean"], row[f"{c}_sd"] = len(xs), mean(xs), sd(xs)
        row["diff_b_minus_a"] = row["securebench_mean"] - row["native_mean"] \
            if row["native_n"] and row["securebench_n"] else float("nan")
        rows.append(row)
    tables[f"per_task_{label}"] = rows

    lines += [f"### Pass rates ({label})", "",
              "| benchmark | condition | tasks | runs | mean pass rate (task-averaged) | 95% bootstrap CI over tasks |",
              "|---|---|---:|---:|---:|---|"]
    summary = []
    for b in ("deep-swe", "terminal-bench"):
        for c in CONDITIONS:
            task_means = [r[f"{c}_mean"] for r in rows if r["benchmark"] == b and r[f"{c}_n"]]
            runs = sum(r[f"{c}_n"] for r in rows if r["benchmark"] == b)
            lo, hi = bootstrap_ci(task_means)
            summary.append({"scope": label, "benchmark": b, "condition": c, "tasks": len(task_means),
                            "runs": runs, "mean": mean(task_means), "ci_low": lo, "ci_high": hi})
            lines.append(f"| {b} | {c} | {len(task_means)} | {runs} | {fmt(mean(task_means))} | [{fmt(lo)}, {fmt(hi)}] |")
    tables[f"per_benchmark_{label}"] = summary

    lines += ["", f"### Paired difference B − A per task ({label})", "",
              "| benchmark | paired tasks | mean diff | 95% bootstrap CI | sign-flip p | Wilcoxon W (n≠0) p |",
              "|---|---:|---:|---|---:|---|"]
    for b in ("deep-swe", "terminal-bench"):
        diffs = [r["diff_b_minus_a"] for r in rows if r["benchmark"] == b and not math.isnan(r["diff_b_minus_a"])]
        lo, hi = bootstrap_ci(diffs)
        w = wilcoxon(diffs)
        lines.append(f"| {b} | {len(diffs)} | {fmt(mean(diffs))} | [{fmt(lo)}, {fmt(hi)}] | "
                     f"{fmt(sign_flip_p(diffs) if diffs else float('nan'), 4)} | {fmt(w['W'], 1)} ({w['n']}) {fmt(w['p'], 4)} |")
    lines += ["", f"Per-task means, SDs and differences: `aggregate/per_task_{label}.csv`.", ""]

    lines += [f"### Infrastructure errors ({label}; excluded from pass rates)", "",
              "| condition | benchmark | runs with infrastructure_error |", "|---|---|---:|"]
    for (c, b), n in sorted(infra.items()):
        lines.append(f"| {c} | {b} | {n} |")
    if not infra:
        lines.append("| - | - | 0 |")
    lines.append("")

    lines += [f"### Runtime, tokens and cost per run ({label})", "",
              "| benchmark | condition | runs | wall s (median) | agent s (median) | verify s (median) | "
              "capture s (median) | input tok (mean) | output tok (mean) | reasoning tok (mean) | cost USD (mean) | cost USD (total) |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    unknown_usage = {}
    for b in ("deep-swe", "terminal-bench"):
        for c in CONDITIONS:
            rs = [r for r in records if r["benchmark"] == b and r["condition"] == c and keep(b, r["task"])]
            known = [r for r in rs if r.get("usage_known", (r.get("turns") or 0) > 0)]
            def med(key):
                xs = [r[key] for r in rs if isinstance(r.get(key), (int, float))]
                return statistics.median(xs) if xs else float("nan")
            def avg(key):
                xs = [r[key] for r in known if isinstance(r.get(key), (int, float))]
                return mean(xs)
            total = sum(r.get("cost_usd") or 0 for r in known)
            unknown_usage[(b, c)] = len(rs) - len(known)
            lines.append(f"| {b} | {c} | {len(rs)} | {fmt(med('wall_time_s'), 0)} | {fmt(med('agent_time_s'), 0)} | "
                         f"{fmt(med('verify_time_s'), 0)} | {fmt(med('capture_time_s'), 0)} | {fmt(avg('input_tokens'), 0)} | "
                         f"{fmt(avg('output_tokens'), 0)} | {fmt(avg('reasoning_tokens'), 0)} | {fmt(avg('cost_usd'), 4)} | {fmt(total, 2)} |")
    lines += ["", "Token and cost columns use only runs whose Codex session completed a turn "
              "(usage is reported only on `turn.completed`); runs without it (timeouts, and SecureBench "
              "runs whose bounded stdout dropped the final event, ISSUES I-28) are excluded, so totals are "
              "lower bounds. Runs with unknown usage: "
              + ", ".join(f"{b}/{c} {n}" for (b, c), n in sorted(unknown_usage.items())) + ".",
              "",
              "SecureBench overhead = capture + evaluation (verify) time in B against native "
              "verification time in A; both are host wall-clock. Native verify time includes "
              "Pier/Harbor verifier container start.", ""]


def agreement(rows, left, right, label, lines, keep=None, kind_field=None):
    usable = [r for r in rows if keep is None or keep(r)]
    kappa, counts = cohen_kappa([(r[left], r[right]) for r in usable])
    comparable = sum(counts.values())
    lines += [f"#### {label}", "",
              f"Comparable pairs: {comparable} (of {len(usable)}). Cohen's κ = {fmt(kappa)}.", "",
              f"| | {right} pass | {right} fail |", "|---|---:|---:|",
              f"| {left} pass | {counts.get(('pass', 'pass'), 0)} | {counts.get(('pass', 'fail'), 0)} |",
              f"| {left} fail | {counts.get(('fail', 'pass'), 0)} | {counts.get(('fail', 'fail'), 0)} |", ""]
    disagreements = [r for r in usable if r[left] in {"pass", "fail"} and r[right] in {"pass", "fail"} and r[left] != r[right]]
    if disagreements:
        lines += ["Disagreements (accepting side named):", ""]
        for r in disagreements:
            accepted = left if r[left] == "pass" else right
            extra = f" [{r[kind_field]}]" if kind_field else ""
            ident = r.get("candidate_id") or f"{r.get('condition')} rep{r.get('rep')} {r.get('candidate')}"
            lines.append(f"- {r.get('task') if 'task' in r and '/' in str(r.get('task')) else r.get('benchmark', '') + '/' + str(r.get('task'))}"
                         f"{extra} `{ident}`: accepted by **{accepted}** only")
        lines.append("")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    records = load_records()
    flagged = f2p_flagged()
    lines = ["# Campaign report", "",
             "Native (A: upstream harness + verifier) vs SecureBench (B: split verification), "
             "Codex CLI 0.156.1, gpt-6-luna, reasoning effort max. See FREEZE.md for pins "
             "and ISSUES.md for known differences.", "",
             f"Phase 4 records (reps {', '.join(map(str, REPS))}; 60 tasks × 2 conditions × 3 reps planned = 360): "
             f"{len(records)}. DeepSWE rows flagged by the F2P audit "
             f"(Weaker or Missing > 0): {len(flagged)}; the `clean-f2p` scope drops them.", ""]
    tables: dict[str, list[dict]] = {}

    lines += ["## Phase 4: pass rates", ""]
    for scope in ("all", "clean-f2p"):
        analyse(records, scope_filter(scope, flagged), scope, lines, tables)

    lines += ["## Verifier agreement", ""]
    phase1 = mark_structural(read_csv(CAMPAIGN / "phase1-agreement.csv"), STRUCTURAL_NA_PHASE1, lambda r: r["task"])
    lines += ["### Phase 1: fixed candidates", ""]
    for scope in ("all", "clean-f2p"):
        keep = scope_filter(scope, flagged)
        subset = lambda r: keep(r["task"].split("/", 1)[0], r["task"].split("/", 1)[1])
        agreement(phase1, "native_verdict", "securebench_verdict", f"Phase 1, {scope}", lines,
                  keep=subset, kind_field="candidate_kind")
        by_kind = Counter((r["candidate_kind"], r["agree"]) for r in phase1 if subset(r))
        lines += ["| candidate kind | agree | disagree | not comparable |", "|---|---:|---:|---:|"]
        for kind in sorted({k for k, _ in by_kind}):
            lines.append(f"| {kind} | {by_kind[(kind, 'yes')]} | {by_kind[(kind, 'no')]} | {by_kind[(kind, 'n/a')]} |")
        lines.append("")

    lines += ["### Attacks: malicious fixed candidates accepted", ""]
    malicious = [r for r in phase1 if r["candidate_kind"] == "malicious"]
    for scope in ("all", "clean-f2p"):
        keep = scope_filter(scope, flagged)
        ms = [r for r in malicious if keep(*r["task"].split("/", 1))]
        native_acc = [r for r in ms if r["native_verdict"] == "pass"]
        secure_acc = [r for r in ms if r["securebench_verdict"] == "pass"]
        lines += [f"{scope}: {len(ms)} malicious candidates; accepted by native: {len(native_acc)}; "
                  f"accepted by SecureBench: {len(secure_acc)}.", ""]
        for r in native_acc + [r for r in secure_acc if r not in native_acc]:
            who = [n for n, acc in (("native", r in native_acc), ("securebench", r in secure_acc)) if acc]
            lines.append(f"- {r['task']} `{r['candidate_id']}` accepted by {' and '.join(who)}")
        lines.append("")

    phase5 = mark_structural(read_csv(CAMPAIGN / "phase5-crossgrade.csv"), STRUCTURAL_NA_PHASE5,
                             lambda r: f"{r['benchmark']}/{r['task']}")
    lines += ["Rows excluded from cross-grading as not faithfully reconstructable "
              "(ISSUES I-34): " + "; ".join(f"`{k}` ({v})" for k, v in STRUCTURAL_NA_PHASE5.items())
              + ". Phase 1 excludes only the two live-service rows.", ""]
    lines += ["### Phase 5: real agent outputs, cross-graded", ""]
    for scope in ("all", "clean-f2p"):
        keep = scope_filter(scope, flagged)
        for condition in CONDITIONS:
            subset = [r for r in phase5 if r["condition"] == condition and keep(r["benchmark"], r["task"])
                      and r["candidate"] in {"securebench-captured", "committed", "final-state"}]
            other = "native" if condition == "securebench" else "securebench"
            agreement(subset, "original_verdict", "cross_verdict",
                      f"{scope}: {condition} runs (own verdict) vs {other} verifier", lines)
        na = Counter(r["reason"] for r in phase5 if r["cross_verdict"] == "n/a" and keep(r["benchmark"], r["task"]))
        if na:
            lines += ["Not cross-graded (n/a):", ""] + [f"- {reason}: {n}" for reason, n in na.most_common()] + [""]
    worktree = [r for r in phase5 if r["candidate"] == "worktree"]
    if worktree:
        lines += [f"DeepSWE native runs whose working tree differed from the committed diff: {len(worktree)}; "
                  f"SecureBench passes the working tree in "
                  f"{sum(r['cross_verdict'] == 'pass' for r in worktree)} of them.", ""]

    retries = CAMPAIGN / "retries.jsonl"
    if retries.exists():
        counts = Counter((json.loads(l)["condition"], json.loads(l).get("error_class")) for l in retries.read_text().splitlines())
        lines += ["## Retries of infrastructure errors", "", "| condition | error class | retries |", "|---|---|---:|"]
        lines += [f"| {c} | {e} | {n} |" for (c, e), n in sorted(counts.items(), key=str)] + [""]

    for name, rows in tables.items():
        if rows:
            with (OUT / f"{name}.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    (CAMPAIGN / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {CAMPAIGN / 'REPORT.md'} and {len(tables)} CSVs in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
