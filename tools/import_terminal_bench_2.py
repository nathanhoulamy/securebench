#!/usr/bin/env python3
"""Import Terminal-Bench 2.0 tasks into a SecureBench terminal_task pack."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any


DEFAULT_REPO = "https://github.com/harbor-framework/terminal-bench-2.git"
DEFAULT_REVISION = "2fd12b88aafdd04a52c298e3940bcb189f9766d6"
DEFAULT_OUTPUT = Path("benchmarks/terminal-bench")
DEFAULT_IMAGE_PREFIX = "securebench-terminal-bench"
WORKDIR = "/app"
EXPECTED_UPSTREAM_TASKS = 89
EXCLUDED_TASKS = {
    "adaptive-rejection-sampler": "installs R outside /app and the checker invokes Rscript",
    "build-cython-ext": "installs the built package into the system Python environment",
    "build-pmars": "installs the candidate binary under /usr/local/bin",
    "build-pov-ray": "installs the candidate binary under /usr/local/bin",
    "caffe-cifar-10": "depends on agent-installed system build and runtime packages",
    "compile-compcert": "builds the candidate under /tmp/CompCert",
    "configure-git-webserver": "verifies live SSH and HTTP services plus state under /git",
    "git-multibranch": "verifies live SSH and HTTPS services plus state under /git",
    "hf-model-inference": "verifies a server process left running by the agent",
    "install-windows-3.11": "verifies a QEMU process left running by the agent",
    "kv-store-grpc": "verifies a gRPC process and system packages left by the agent",
    "mailman": "verifies live system services and state under /etc and /var",
    "mcmc-sampling-stan": "installs RStan into the system R environment",
    "nginx-request-logging": "verifies live nginx state under /etc and /var",
    "pypi-server": "verifies a package server process left running by the agent",
    "qemu-alpine-ssh": "verifies a QEMU and SSH process left running by the agent",
    "qemu-startup": "verifies a QEMU process left running by the agent",
    "sqlite-with-gcov": "installs the candidate sqlite3 executable into PATH outside /app",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Existing terminal-bench-2 checkout to import")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image-prefix", default=DEFAULT_IMAGE_PREFIX)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.revision) is None:
        raise SystemExit("--revision must be a full lowercase 40-character Git commit hash")

    source = args.source or clone_source(args.repo, args.revision)
    tasks = task_dirs(source)
    if len(tasks) != EXPECTED_UPSTREAM_TASKS:
        raise SystemExit(
            f"Expected {EXPECTED_UPSTREAM_TASKS} Terminal-Bench 2.0 tasks, "
            f"got {len(tasks)} from {source}"
        )
    missing_exclusions = sorted(set(EXCLUDED_TASKS) - {task.name for task in tasks})
    if missing_exclusions:
        raise SystemExit(
            "Excluded Terminal-Bench task ids were not found upstream: "
            + ", ".join(missing_exclusions)
        )

    write_pack(
        source=source,
        tasks=tasks,
        output=args.output,
        image_prefix=args.image_prefix,
        repo=args.repo,
        revision=args.revision,
    )
    included = len(tasks) - len(EXCLUDED_TASKS)
    print(
        f"Wrote {included} supported Terminal-Bench 2.0 tasks to {args.output}; "
        f"excluded {len(EXCLUDED_TASKS)} rows incompatible with isolated verification"
    )
    return 0


def clone_source(repo: str, revision: str) -> Path:
    target = Path("/tmp/securebench-terminal-bench-2")
    if target.exists():
        shutil.rmtree(target)
    subprocess.run(["git", "clone", "--depth", "1", repo, str(target)], check=True)
    subprocess.run(["git", "fetch", "--depth", "1", "origin", revision], cwd=target, check=True)
    subprocess.run(["git", "checkout", revision], cwd=target, check=True)
    return target


def task_dirs(source: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in source.iterdir()
            if path.is_dir()
            and (path / "environment" / "Dockerfile").exists()
            and (path / "tests" / "test.sh").exists()
            and (path / "instruction.md").exists()
            and (path / "task.toml").exists()
        ),
        key=lambda path: path.name,
    )


def write_pack(
    *,
    source: Path,
    tasks: list[Path],
    output: Path,
    image_prefix: str,
    repo: str,
    revision: str,
) -> None:
    docker_root = output / "docker"
    hidden_root = output / "hidden"
    for path in (docker_root, hidden_root):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)

    rows = []
    for source_index, task_dir in enumerate(tasks):
        if task_dir.name in EXCLUDED_TASKS:
            continue
        rows.append(
            convert_task(
                source_index=source_index,
                task_dir=task_dir,
                docker_root=docker_root,
                hidden_root=hidden_root,
                image_prefix=image_prefix,
                repo=repo,
                revision=revision,
            )
        )

    with (output / "tasks.jsonl").open("w") as file:
        for row in rows:
            file.write(json.dumps(row, sort_keys=True))
            file.write("\n")


def convert_task(
    *,
    source_index: int,
    task_dir: Path,
    docker_root: Path,
    hidden_root: Path,
    image_prefix: str,
    repo: str,
    revision: str,
) -> dict[str, Any]:
    task_id = task_dir.name
    task_toml = tomllib.loads((task_dir / "task.toml").read_text())
    metadata = task_toml["metadata"]
    verifier = task_toml["verifier"]
    agent = task_toml["agent"]
    environment = task_toml["environment"]

    docker_task = docker_root / task_id
    hidden_task = hidden_root / task_id
    shutil.copytree(task_dir / "environment", docker_task)
    shutil.copytree(task_dir / "tests", hidden_task / "tests")
    write_run_tests(task_dir / "tests" / "test.sh", hidden_task / "run-tests.sh")

    needed_commands = []
    if tests_need_chroot(task_dir / "tests"):
        needed_commands.append("chroot")

    eval_data: dict[str, Any] = {
        "checker": {
            "path": f"{task_id}/run-tests.sh",
            "source": "script",
            "timeout_seconds": float(verifier["timeout_sec"]),
        }
    }
    if needed_commands:
        eval_data["needed_commands"] = needed_commands

    return {
        "environment": {
            "build_context": f"docker/{task_id}",
            "image": f"{image_prefix}-{task_id}:{revision[:12]}",
            "materialize_workdir_from_image": True,
            "timeout_seconds": float(agent["timeout_sec"]),
            "workdir": WORKDIR,
        },
        "eval": eval_data,
        "id": f"terminal-bench/{task_id}",
        "input": {
            "instructions": (task_dir / "instruction.md").read_text().strip(),
        },
        "metadata": {
            "author_email": metadata.get("author_email"),
            "author_name": metadata.get("author_name"),
            "category": metadata.get("category"),
            "difficulty": metadata.get("difficulty"),
            "expert_time_estimate_min": metadata.get("expert_time_estimate_min"),
            "junior_time_estimate_min": metadata.get("junior_time_estimate_min"),
            "max_agent_timeout_sec": float(agent["timeout_sec"]),
            "max_test_timeout_sec": float(verifier["timeout_sec"]),
            "source_dataset": "Terminal-Bench 2.0",
            "source_repository": repo,
            "source_revision": revision,
            "source_index": source_index,
            "source_task_id": task_id,
            "tags": metadata.get("tags", []),
            "upstream_docker_image": environment.get("docker_image"),
        },
    }


def write_run_tests(source: Path, target: Path) -> None:
    script = source.read_text()
    script = script.replace("/tests", "${TEST_DIR}")
    script = script.replace("/logs/verifier", "${SECUREBENCH_WORKSPACE}/.securebench-verifier")
    target.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "mkdir -p \"${SECUREBENCH_WORKSPACE}/.securebench-verifier\"\n"
        "mkdir -p /logs\n"
        "rm -rf /tests /logs/verifier\n"
        "ln -s \"${TEST_DIR}\" /tests\n"
        "ln -s \"${SECUREBENCH_WORKSPACE}/.securebench-verifier\" /logs/verifier\n"
        + script.removeprefix("#!/bin/bash\n")
    )
    target.chmod(0o755)


def tests_need_chroot(tests_dir: Path) -> bool:
    for path in tests_dir.rglob("*"):
        if path.is_file() and "chroot" in path.read_text(errors="ignore"):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
