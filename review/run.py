"""Run independent-review adversarial agents against SecureBench benchmark packs."""

from __future__ import annotations

import argparse
import json
import shutil
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates.extraction import default_extraction_spec, extract_candidate
from securebench.errors import ConfigError
from securebench.harnesses.codex import CODEX_DUMMY_API_KEY, CODEX_PROVIDER_RELAY_SPEC
from securebench.harnesses.network import (
    HarnessEgress,
    docker_provider_relay_policy,
    relay_decision_summary,
)
from securebench.harnesses.shared import (
    agent_task_json,
    close_sandbox,
    container_image_for_task,
    container_workspace_path,
    materialize_workdir_from_image_if_requested,
    reject_task_file_collision,
    run_timeout_seconds,
    task_workdir,
    workspace_dir_name,
    workspace_mount_target_for_task,
)
from securebench.sandboxes import DockerSandbox, HostSandbox, Sandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.tester_run import candidate_record, verify_candidate
from securebench.workspaces.materialization import VisibilityAwareMaterializer, docker_read_only_mounts


REVIEW_ROOT = Path(__file__).resolve().parent
AGENTS_ROOT = REVIEW_ROOT / "agents"
AGENTS_TARGET = "/opt/securebench/review-agents"
DEFAULT_TASK_FILE = "review_task.json"
DEFAULT_TRACE_FILE = "review-agent-trace.json"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
ADVERSARY_MODES = {"live_openai", "external"}
ADVERSARY_PROFILES = {
    "auto",
    "artifact_forgery",
    "evaluator_escape",
    "leak_probe",
    "network_exfil",
    "output_only",
    "repo_tamper",
    "terminal_poison",
}


@dataclass(frozen=True)
class ReviewRunSection:
    id: str
    output_dir: Path


@dataclass(frozen=True)
class ReviewBenchmarkSection:
    manifest: Path
    tasks: Path
    limit: int | None = None


@dataclass(frozen=True)
class ReviewAdversarySection:
    mode: str
    profile: str = "auto"
    command: str | tuple[str, ...] | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_steps: int = 4


@dataclass(frozen=True)
class ReviewProviderSection:
    model: str = DEFAULT_OPENAI_MODEL
    allow_external_tools: bool = False
    enabled: bool = False


@dataclass(frozen=True)
class ReviewConfig:
    run: ReviewRunSection
    benchmark: ReviewBenchmarkSection
    adversary: ReviewAdversarySection
    provider: ReviewProviderSection = field(default_factory=ReviewProviderSection)


@dataclass(frozen=True)
class ReviewRunSummary:
    run_id: str
    output_dir: str
    total: int
    verified: int
    passed: int
    adversary_violations: int


def load_review_config(path: str | Path) -> ReviewConfig:
    config_path = Path(path)
    loaded = yaml.safe_load(config_path.read_text())
    if not isinstance(loaded, dict):
        raise ConfigError("review config root must be an object")
    return parse_review_config(loaded, base_dir=config_path.parent)


def parse_review_config(data: dict[str, Any], *, base_dir: str | Path | None = None) -> ReviewConfig:
    base = None if base_dir is None else Path(base_dir)
    _reject_unknown(data, {"run", "benchmark", "adversary", "provider"}, "root")
    run_data = _required_dict(data, "run", "root")
    benchmark_data = _required_dict(data, "benchmark", "root")
    adversary_data = _required_dict(data, "adversary", "root")
    provider_data = _optional_dict(data.get("provider"), "provider")
    _reject_unknown(run_data, {"id", "output_dir"}, "run")
    _reject_unknown(benchmark_data, {"manifest", "tasks", "limit"}, "benchmark")
    _reject_unknown(adversary_data, {"mode", "profile", "command", "timeout_seconds", "max_steps"}, "adversary")
    _reject_unknown(provider_data, {"model", "allow_external_tools", "enabled"}, "provider")

    mode = _literal(_required_str(adversary_data, "mode", "adversary"), ADVERSARY_MODES, "adversary.mode")
    profile = _literal(adversary_data.get("profile", "auto"), ADVERSARY_PROFILES, "adversary.profile")
    command = _optional_command(adversary_data.get("command"), "adversary.command")
    if mode == "external" and command is None:
        raise ConfigError("adversary.command is required when adversary.mode is 'external'")
    if mode != "external" and command is not None:
        raise ConfigError("adversary.command is only supported when adversary.mode is 'external'")

    provider_enabled = bool(provider_data.get("enabled", mode == "live_openai"))
    provider = ReviewProviderSection(
        model=_optional_str(provider_data.get("model"), "provider.model", DEFAULT_OPENAI_MODEL),
        allow_external_tools=_optional_bool(provider_data.get("allow_external_tools"), "provider.allow_external_tools", False),
        enabled=provider_enabled,
    )
    if mode == "live_openai" and not provider.enabled:
        raise ConfigError("provider.enabled may not be false for live_openai mode")

    return ReviewConfig(
        run=ReviewRunSection(
            id=_required_str(run_data, "id", "run"),
            output_dir=_config_path(_required_str(run_data, "output_dir", "run"), base),
        ),
        benchmark=ReviewBenchmarkSection(
            manifest=_config_path(_required_str(benchmark_data, "manifest", "benchmark"), base),
            tasks=_config_path(_required_str(benchmark_data, "tasks", "benchmark"), base),
            limit=_optional_positive_int(benchmark_data.get("limit"), "benchmark.limit"),
        ),
        adversary=ReviewAdversarySection(
            mode=mode,
            profile=profile,
            command=command,
            timeout_seconds=_optional_positive_number(
                adversary_data.get("timeout_seconds"),
                "adversary.timeout_seconds",
                DEFAULT_TIMEOUT_SECONDS,
            ),
            max_steps=_optional_positive_int(adversary_data.get("max_steps"), "adversary.max_steps") or 4,
        ),
        provider=provider,
    )


class ReviewRunner:
    """Orchestrate one independent-review adversarial run."""

    def __init__(
        self,
        config: ReviewConfig,
        *,
        sandbox_factory: type[DockerSandbox] | None = None,
        provider_relay_factory: Any = docker_provider_relay_policy,
    ) -> None:
        self.config = config
        self.sandbox_factory = sandbox_factory or DockerSandbox
        self.provider_relay_factory = provider_relay_factory
        self.materializer = VisibilityAwareMaterializer()

    def run(self) -> ReviewRunSummary:
        output_dir = self.config.run.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        results_path = output_dir / "results.jsonl"
        workspace_root = output_dir / "workspaces"
        traces_root = output_dir / "traces"
        traces_root.mkdir(parents=True, exist_ok=True)

        pack = load_benchmark_pack(self.config.benchmark.manifest, self.config.benchmark.tasks)
        tasks = list(compile_benchmark_pack(pack, limit=self.config.benchmark.limit))
        total = verified = passed = adversary_violations = 0

        with results_path.open("w") as results_file:
            for task in tasks:
                total += 1
                task_workspace = (workspace_root / workspace_dir_name(task)).resolve()
                _reset_workspace(workspace_root, task_workspace)
                task_workspace.mkdir(parents=True, exist_ok=True)
                candidate, trace, relay_summary = self._produce_candidate(task, task_workspace)
                verification = verify_candidate(task, candidate)
                if verification is not None:
                    verified += 1
                    if verification.passed:
                        passed += 1
                violations = trace.get("violations") if isinstance(trace, dict) else None
                if isinstance(violations, list) and violations:
                    adversary_violations += 1
                record = candidate_record(self.config.run.id, task, candidate, verification)
                record["review_adversary"] = {
                    "mode": self.config.adversary.mode,
                    "profile": self.config.adversary.profile,
                    "trace": trace,
                    **relay_summary,
                }
                results_file.write(json.dumps(record, sort_keys=True) + "\n")
                results_file.flush()
                (traces_root / f"{workspace_dir_name(task)}.json").write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n")

        summary = ReviewRunSummary(
            run_id=self.config.run.id,
            output_dir=str(output_dir),
            total=total,
            verified=verified,
            passed=passed,
            adversary_violations=adversary_violations,
        )
        (output_dir / "summary.json").write_text(json.dumps(summary.__dict__, indent=2, sort_keys=True) + "\n")
        return summary

    def _produce_candidate(self, task: Any, task_workspace: Path):
        materialize_workdir_from_image_if_requested(task, task_workspace)
        staging = HostSandbox(root=task_workspace)
        plan = self.materializer.materialize(task, staging, "agent")
        reject_task_file_collision(DEFAULT_TASK_FILE, plan)
        staging.write_file(DEFAULT_TASK_FILE, agent_task_json(task))

        egress_context = self._egress_context()
        with egress_context as egress:
            env = self._adversary_env(task, egress)
            sandbox = self.sandbox_factory(
                image=container_image_for_task(task),
                root=task_workspace,
                env=env,
                network=egress.network,
                read_only=False,
                mounts=(
                    *docker_read_only_mounts(plan, task_workspace),
                    DockerBindMount(source=AGENTS_ROOT, target=AGENTS_TARGET, read_only=True),
                ),
                workspace_mount_target=workspace_mount_target_for_task(task),
            )
            try:
                timeout = run_timeout_seconds(
                    task,
                    fallback_timeout=self.config.adversary.timeout_seconds,
                )
                result = sandbox.run(
                    self._adversary_command(task),
                    workdir=task_workdir(task) or workspace_mount_target_for_task(task),
                    timeout=timeout,
                )
                candidate = extract_candidate(
                    sandbox,
                    result,
                    default_extraction_spec(task),
                    timeout=timeout,
                )
                trace = _read_trace(sandbox, DEFAULT_TRACE_FILE)
                relay_summary = relay_decision_summary(egress.relay_log_dir)
                return candidate, trace, relay_summary
            finally:
                close_sandbox(sandbox)

    def _egress_context(self):
        if not self.config.provider.enabled:
            return nullcontext(HarnessEgress(network="none", env={}, allowed_domains=()))
        return self.provider_relay_factory(
            CODEX_PROVIDER_RELAY_SPEC,
            (),
            allow_external_tools=self.config.provider.allow_external_tools,
        )

    def _adversary_env(self, task: Any, egress: HarnessEgress) -> dict[str, str]:
        workspace_target = workspace_mount_target_for_task(task)
        env = {
            **egress.env,
            "REVIEW_TASK_FILE": container_workspace_path(DEFAULT_TASK_FILE, mount_target=workspace_target),
            "REVIEW_PROFILE": self.config.adversary.profile,
            "REVIEW_MODE": self.config.adversary.mode,
            "REVIEW_MAX_STEPS": str(self.config.adversary.max_steps),
            "REVIEW_TRACE_FILE": container_workspace_path(DEFAULT_TRACE_FILE, mount_target=workspace_target),
            "REVIEW_TASK_TYPE": task.task_type,
            "SECUREBENCH_WORKSPACE": workspace_target,
            "SECUREBENCH_WORKDIR": task_workdir(task) or workspace_target,
        }
        if self.config.provider.enabled:
            if egress.provider_base_url is None:
                raise ConfigError("provider relay did not provide a base URL")
            env.update(
                {
                    "OPENAI_API_KEY": CODEX_DUMMY_API_KEY,
                    "CODEX_API_KEY": CODEX_DUMMY_API_KEY,
                    "OPENAI_BASE_URL": egress.provider_base_url,
                    "REVIEW_OPENAI_MODEL": self.config.provider.model,
                    "REVIEW_ALLOW_EXTERNAL_TOOLS": str(self.config.provider.allow_external_tools).lower(),
                }
            )
        return env

    def _adversary_command(self, task: Any) -> str | tuple[str, ...]:
        if self.config.adversary.mode == "external":
            assert self.config.adversary.command is not None
            return self.config.adversary.command
        return (
            "python3",
            f"{AGENTS_TARGET}/agent.py",
            "--mode",
            "live_openai",
            "--profile",
            self.config.adversary.profile,
            "--task-file",
            container_workspace_path(DEFAULT_TASK_FILE, mount_target=workspace_mount_target_for_task(task)),
            "--trace-file",
            container_workspace_path(DEFAULT_TRACE_FILE, mount_target=workspace_mount_target_for_task(task)),
            "--max-steps",
            str(self.config.adversary.max_steps),
        )


def run_config(path: str | Path) -> ReviewRunSummary:
    return ReviewRunner(load_review_config(path)).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run independent-review adversarial SecureBench checks")
    parser.add_argument("--config", required=True, help="Path to a review adversarial config")
    args = parser.parse_args(argv)
    try:
        summary = run_config(args.config)
    except ConfigError as exc:
        print(f"review run failed: {exc}")
        return 1
    print(
        "review run: "
        f"run_id={summary.run_id} total={summary.total} verified={summary.verified} "
        f"passed={summary.passed} adversary_violations={summary.adversary_violations} "
        f"output_dir={summary.output_dir}"
    )
    return 0


def _read_trace(sandbox: Sandbox, path: str) -> dict[str, Any]:
    try:
        raw = sandbox.extract_file(path).decode(errors="replace")
        loaded = json.loads(raw)
    except Exception as exc:
        return {"status": "missing_or_invalid", "error": str(exc), "errors": ["missing_trace"], "violations": []}
    return loaded if isinstance(loaded, dict) else {"status": "invalid", "errors": ["invalid_trace_shape"], "violations": []}


def _reset_workspace(root: Path, task_workspace: Path) -> None:
    root_resolved = root.resolve()
    if not task_workspace.is_relative_to(root_resolved):
        raise ConfigError(f"task workspace escapes workspace root: {task_workspace}")
    if task_workspace.exists():
        shutil.rmtree(task_workspace)


def _required_dict(data: dict[str, Any], key: str, section: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{section}.{key} must be an object")
    return value


def _optional_dict(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be an object")
    return dict(value)


def _required_str(data: dict[str, Any], key: str, section: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{section}.{key} must be a non-empty string")
    return value


def _optional_str(value: Any, field: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string")
    return value


def _optional_bool(value: Any, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"{field} must be a boolean")
    return value


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{field} must be a positive integer")
    return value


def _optional_positive_number(value: Any, field: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{field} must be a positive number")
    return float(value)


def _optional_command(value: Any, field: str) -> str | tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(value)
    raise ConfigError(f"{field} must be a non-empty string or string array")


def _literal(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ConfigError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return value


def _config_path(value: str, base_dir: Path | None) -> Path:
    path = Path(value)
    if base_dir is not None and not path.is_absolute():
        return base_dir / path
    return path


def _reject_unknown(data: dict[str, Any], allowed: set[str], section: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{section} contains unsupported field(s): {', '.join(unknown)}")


if __name__ == "__main__":
    raise SystemExit(main())
