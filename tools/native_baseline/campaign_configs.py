"""Generate per-task SecureBench campaign configs that match upstream limits.

The tester config carries one memory limit and one timeout ceiling per run, but
upstream limits vary per task, so the campaign runs every (task, rep) with its
own single-row config. Nothing in ``benchmarks/`` is edited: each config points
at the pack's own ``manifest-v2.yaml`` and at a one-row copy of the admitted row.

Usage::

    python -m tools.native_baseline.campaign_configs

Writes ``runs/campaign/configs/`` and ``runs/campaign/configs/resources.csv``.
"""

from __future__ import annotations

import csv
import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "runs" / "campaign"
CONFIGS = CAMPAIGN / "configs"
UPSTREAM = CAMPAIGN / "upstream"

CODEX_VERSION = "0.156.1"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "max"

PACKS = {
    "deep-swe": {
        "tasks": CAMPAIGN / "ds-admitted-tasks-v2.jsonl",
        "manifest": ROOT / "benchmarks" / "deep-swe" / "manifest-v2.yaml",
        "upstream": UPSTREAM / "deep-swe" / "tasks",
        "base_config": ROOT / "benchmarks" / "deep-swe" / "tester-linux.yaml",
    },
    "terminal-bench": {
        "tasks": CAMPAIGN / "tb-admitted-tasks-v2.jsonl",
        "manifest": ROOT / "benchmarks" / "terminal-bench" / "manifest-v2.yaml",
        "upstream": UPSTREAM / "tb2",
        "base_config": ROOT / "benchmarks" / "terminal-bench" / "tester-codex.yaml",
    },
}


def upstream_limits(task_dir: Path) -> dict:
    meta = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    environment = meta["environment"]
    agent = meta.get("agent", {})
    verifier = meta.get("verifier", {})
    verifier_environment = verifier.get("environment", {})
    return {
        "agent_timeout_s": float(agent["timeout_sec"]),
        "verifier_timeout_s": float(verifier.get("timeout_sec", 0)),
        "cpus": environment.get("cpus"),
        "memory_mb": int(environment["memory_mb"]),
        "verifier_cpus": verifier_environment.get("cpus", environment.get("cpus")),
        "verifier_memory_mb": verifier_environment.get("memory_mb", environment["memory_mb"]),
        "agent_network": agent.get("network_mode")
        or ("internet" if environment.get("allow_internet") else "no-network"),
        "image": environment["docker_image"],
        "storage_mb": int(environment.get("storage_mb", 0)),
    }


def securebench_config(pack: str, row: dict, limits: dict, rows_path: Path) -> dict:
    base = yaml.safe_load(PACKS[pack]["base_config"].read_text(encoding="utf-8"))
    task = row["id"].split("/", 1)[1]
    config = {
        "schema_version": "1.0",
        "run": {
            "id": f"campaign-securebench-{pack}-{task}",
            "output_dir": str(CAMPAIGN / "securebench" / pack / "unassigned" / task),
            "max_workers": 1,
        },
        "benchmark": {
            "manifest": str(PACKS[pack]["manifest"]),
            "tasks": str(rows_path),
        },
        # No max_cached_images: pruning would delete locally built images that
        # cannot be pulled again (see ISSUES.md).
        "docker": {"memory_limit": f"{limits['memory_mb']}m"},
    }
    if "network_policy" in base:
        config["network_policy"] = base["network_policy"]
    config["harness"] = {
        "type": "codex",
        "config": {
            "auth": "api_key",
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "version": CODEX_VERSION,
            "task_file": "task.json",
            # Give Codex the row's public instructions verbatim (= upstream
            # instruction.md), with no SecureBench wrapper and no task file.
            "prompt": "instructions",
            # A ceiling: the effective timeout is min(row, this).
            "timeout_seconds": int(limits["agent_timeout_s"]),
            "allow_external_tools": False,
        },
    }
    if pack == "terminal-bench":
        # Upstream has no candidate size cap, only per-task disk (storage_mb);
        # use that so the tester cap never binds before upstream's own limit.
        # Per-row declared max_bytes in the candidate spec still apply.
        config["capture"] = {"max_candidate_bytes": limits["storage_mb"] * 1024 * 1024}
    return config


def main() -> int:
    table = []
    for pack, spec in PACKS.items():
        for line in spec["tasks"].read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            task = row["id"].split("/", 1)[1]
            limits = upstream_limits(spec["upstream"] / task)
            destination = CONFIGS / "securebench" / pack / task
            destination.mkdir(parents=True, exist_ok=True)
            rows_path = destination / "task.jsonl"
            rows_path.write_text(line + "\n", encoding="utf-8")
            config = securebench_config(pack, row, limits, rows_path)
            (destination / "config.yaml").write_text(
                yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
            )
            row_timeout = float(row["environment"]["timeout_seconds"])
            network = row["environment"].get("agent_network")
            table.append({
                "pack": pack,
                "task": task,
                "upstream_agent_timeout_s": limits["agent_timeout_s"],
                "securebench_row_timeout_s": row_timeout,
                "effective_securebench_timeout_s": min(row_timeout, limits["agent_timeout_s"]),
                "upstream_verifier_timeout_s": limits["verifier_timeout_s"],
                "upstream_cpus": limits["cpus"],
                "securebench_cpus": "unlimited",
                "upstream_memory_mb": limits["memory_mb"],
                "securebench_memory": config["docker"]["memory_limit"],
                "upstream_verifier_cpus": limits["verifier_cpus"],
                "upstream_verifier_memory_mb": limits["verifier_memory_mb"],
                "upstream_agent_network": limits["agent_network"],
                "securebench_agent_network": json.dumps(network, sort_keys=True),
                "upstream_storage_mb": limits["storage_mb"],
                "securebench_capture_cap_bytes": config.get("capture", {}).get("max_candidate_bytes", ""),
                "upstream_image": limits["image"],
                "securebench_image": row["environment"]["image"],
            })
    with (CONFIGS / "resources.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    print(f"wrote {len(table)} configs under {CONFIGS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
