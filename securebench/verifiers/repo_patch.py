"""Verifier for image-backed repo-patch benchmark-pack tasks."""

from __future__ import annotations

import fnmatch
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, DockerBindMount, DockerSandbox, Sandbox
from securebench.tasks import SecureBenchTask, resource_text, resource_value
from securebench.verifiers.base import VerificationResult, Verifier, timeout_metadata
from securebench.verifiers.code_completion import environment_image_for_task


SandboxFactory = Callable[..., Sandbox]
DEFAULT_CANDIDATE_PATCH = "securebench/candidate.patch"
DEFAULT_SETUP_PATCH = "setup.patch"
DEFAULT_TEST_PATCH = "test.patch"
DEFAULT_EVALUATION_INPUTS_TARGET = "/opt/securebench/evaluation_inputs"
DEFAULT_DENIED_PATH_NAMES = {
    "cargo.lock",
    "cargo.toml",
    "conftest.py",
    "go.mod",
    "go.sum",
    "package.json",
    "package-lock.json",
    "pipfile",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "yarn.lock",
}
DEFAULT_DENIED_PATH_SUFFIXES = (
    ".lock",
)
DEFAULT_DENIED_ROOTS = (
    ".github",
    ".gitlab",
    "ci",
    "securebench",
)
DEFAULT_DENIED_PARTS = (
    "__pycache__",
    "test",
    "tests",
)
DEFAULT_DENIED_SHELL_SUFFIXES = (
    ".bash",
    ".sh",
    ".zsh",
)


class RepoPatchVerifier(Verifier):
    """Apply a candidate patch in a benchmark image and run declared checks."""

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory | None = None,
        timeout_seconds: float = 300.0,
        candidate_patch_path: str = DEFAULT_CANDIDATE_PATCH,
        test_patch_path: str = DEFAULT_TEST_PATCH,
        evaluation_inputs_target: str = DEFAULT_EVALUATION_INPUTS_TARGET,
        workspace_mount_target: str = "/securebench-workspace",
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.timeout_seconds = timeout_seconds
        self.candidate_patch_path = candidate_patch_path
        self.test_patch_path = test_patch_path
        self.evaluation_inputs_target = _absolute_container_path(
            evaluation_inputs_target,
            "evaluation_inputs_target",
        )
        self.workspace_mount_target = workspace_mount_target

    def verify(self, task: SecureBenchTask, candidate: str, **context: Any) -> VerificationResult:
        if task.task_type != "repo_patch":
            raise TypeError(f"RepoPatchVerifier requires repo_patch task, got {task.task_type!r}")

        tests = command_tests(task)
        policy = candidate_policy(task)
        image = environment_image_for_task(task)
        workdir = tests.workdir or environment_workdir_for_task(task)
        timeout = float(context.get("timeout_seconds", tests.timeout_seconds or self.timeout_seconds))
        policy_decision = evaluate_candidate_patch_policy(candidate, policy)
        if not candidate.strip():
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "candidate_patch",
                CommandResult(("candidate_patch",), 1, "", "empty candidate patch"),
                failure_reason="empty_candidate_patch",
            )
        with tempfile.TemporaryDirectory(prefix="securebench-repo-patch-eval-") as eval_dir:
            eval_root = Path(eval_dir)
            setup_patch_path = None
            test_patch_path = None
            if tests.setup_patch is not None:
                setup_patch_path = str(context.get("setup_patch_path", DEFAULT_SETUP_PATCH))
                _write_trusted_patch(eval_root, setup_patch_path, tests.setup_patch)
            if tests.test_patch is not None:
                test_patch_path = str(context.get("test_patch_path", self.test_patch_path))
                _write_trusted_patch(eval_root, test_patch_path, tests.test_patch)

            sandbox = self._sandbox(
                image,
                mounts=(
                    DockerBindMount(
                        source=eval_root,
                        target=self.evaluation_inputs_target,
                        read_only=True,
                    ),
                ),
            )
            close_sandbox = self.sandbox_factory is None

            try:
                return self._verify_in_sandbox(
                    task,
                    tests,
                    sandbox,
                    image=image,
                    workdir=workdir,
                    timeout=timeout,
                    policy_decision=policy_decision,
                    setup_patch_path=setup_patch_path,
                    test_patch_path=test_patch_path,
                    context=context,
                )
            finally:
                if close_sandbox:
                    _close_sandbox(sandbox)

    def _verify_in_sandbox(
        self,
        task: SecureBenchTask,
        tests: "CommandTests",
        sandbox: Sandbox,
        *,
        image: str,
        workdir: str,
        timeout: float,
        policy_decision: "CandidatePatchPolicyDecision",
        setup_patch_path: str | None,
        test_patch_path: str | None,
        context: dict[str, Any],
    ) -> VerificationResult:
        base_commit = resource_text(task, "base_commit")
        head = sandbox.run(["git", "rev-parse", "HEAD"], workdir=workdir, timeout=timeout)
        if head.exit_code != 0:
            return _failed_result(task, "repo_patch", image, workdir, "base_commit", head)

        if not policy_decision.allowed:
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "candidate_policy",
                CommandResult(
                    ("candidate_policy",),
                    1,
                    "",
                    candidate_policy_error(policy_decision),
                ),
                base_commit=base_commit,
                image_commit=head.stdout.strip(),
                candidate_patch_paths=policy_decision.paths,
                applied_candidate_patch_paths=policy_decision.applied_paths,
                stripped_candidate_patch_paths=policy_decision.stripped_paths,
                denied_candidate_patch_paths=policy_decision.denied_paths,
                failure_reason=policy_decision.failure_reason or "candidate_patch_policy_violation",
            )

        if setup_patch_path is not None:
            apply_setup = sandbox.run(
                ["git", "apply", "--binary", self._evaluation_input_path(setup_patch_path)],
                workdir=workdir,
                timeout=timeout,
            )
            if apply_setup.exit_code != 0:
                return _failed_result(
                    task,
                    "repo_patch",
                    image,
                    workdir,
                    "setup_patch",
                    apply_setup,
                    base_commit=base_commit,
                    image_commit=head.stdout.strip(),
                )

        candidate_path = str(context.get("candidate_patch_path", self.candidate_patch_path))
        sandbox.write_file(candidate_path, policy_decision.filtered_patch)
        apply_candidate = sandbox.run(
            ["git", "apply", "--binary", self._workspace_path(candidate_path)],
            workdir=workdir,
            timeout=timeout,
        )
        if apply_candidate.exit_code != 0:
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "candidate_patch",
                apply_candidate,
                base_commit=base_commit,
                image_commit=head.stdout.strip(),
                candidate_patch_paths=policy_decision.paths,
                applied_candidate_patch_paths=policy_decision.applied_paths,
                stripped_candidate_patch_paths=policy_decision.stripped_paths,
            )

        if test_patch_path is not None:
            apply_tests = sandbox.run(
                ["git", "apply", "--binary", self._evaluation_input_path(test_patch_path)],
                workdir=workdir,
                timeout=timeout,
            )
            if apply_tests.exit_code != 0:
                return _failed_result(
                    task,
                    "repo_patch",
                    image,
                    workdir,
                    "test_patch",
                    apply_tests,
                    base_commit=base_commit,
                    image_commit=head.stdout.strip(),
                )

        result = sandbox.run(tests.command, workdir=workdir, timeout=timeout)
        passed = result.exit_code == 0
        return VerificationResult(
            task_id=task.id,
            status="passed" if passed else "failed",
            passed=passed,
            score=1.0 if passed else 0.0,
            stdout=result.stdout,
            stderr=result.stderr,
            metadata={
                "verifier": "repo_patch",
                "image": image,
                "workdir": workdir,
                "base_commit": base_commit,
                "image_commit": head.stdout.strip(),
                "command": result.command,
                "exit_code": result.exit_code,
                "phase": "checks",
                "candidate_patch_paths": policy_decision.paths,
                "applied_candidate_patch_paths": policy_decision.applied_paths,
                "stripped_candidate_patch_paths": policy_decision.stripped_paths,
                **timeout_metadata(result),
            },
        )

    def _sandbox(self, image: str, *, mounts: tuple[DockerBindMount, ...] = ()) -> Sandbox:
        if self.sandbox_factory is not None:
            return self.sandbox_factory(image=image, mounts=mounts)
        return DockerSandbox(
            image=image,
            network="none",
            read_only=False,
            mounts=mounts,
            workspace_mount_target=self.workspace_mount_target,
        )

    def _workspace_path(self, path: str) -> str:
        candidate = PurePosixPath(path)
        if candidate.is_absolute():
            return str(candidate)
        return str(PurePosixPath(self.workspace_mount_target) / candidate)

    def _evaluation_input_path(self, path: str) -> str:
        relative = _safe_relative_patch_path(path)
        return str(PurePosixPath(self.evaluation_inputs_target) / relative)


class CommandTests:
    def __init__(
        self,
        *,
        command: str | tuple[str, ...],
        workdir: str | None,
        timeout_seconds: float | None,
        setup_patch: str | None,
        test_patch: str | None,
    ) -> None:
        self.command = command
        self.workdir = workdir
        self.timeout_seconds = timeout_seconds
        self.setup_patch = setup_patch
        self.test_patch = test_patch


class CandidatePatchPolicy:
    def __init__(
        self,
        *,
        allow_paths: tuple[str, ...] = (),
        allow_sensitive_paths: tuple[str, ...] = (),
        patch_preserved_paths: tuple[str, ...] = (),
    ) -> None:
        self.allow_paths = allow_paths
        self.allow_sensitive_paths = allow_sensitive_paths
        self.patch_preserved_paths = patch_preserved_paths


class CandidatePatchPolicyDecision:
    def __init__(
        self,
        *,
        paths: tuple[str, ...],
        applied_paths: tuple[str, ...],
        stripped_paths: tuple[str, ...],
        denied_paths: tuple[str, ...],
        filtered_patch: str,
        failure_reason: str | None = None,
    ) -> None:
        self.paths = paths
        self.applied_paths = applied_paths
        self.stripped_paths = stripped_paths
        self.denied_paths = denied_paths
        self.filtered_patch = filtered_patch
        self.failure_reason = failure_reason

    @property
    def allowed(self) -> bool:
        return not self.denied_paths and self.failure_reason is None


def command_tests(task: SecureBenchTask) -> CommandTests:
    """Return structured command tests for a repo-patch task."""
    tests = resource_value(task, "tests")
    if not isinstance(tests, dict):
        raise ConfigError(f"repo_patch task {task.id!r} requires structured command tests")
    if tests.get("source") != "command":
        raise ConfigError(f"repo_patch task {task.id!r} requires tests.source='command'")
    command = _command(tests.get("command"), task.id)
    workdir = _optional_string(tests.get("workdir"), "tests.workdir")
    timeout_seconds = _optional_positive_number(tests.get("timeout_seconds"), "tests.timeout_seconds")
    setup_patch = _test_patch(tests.get("setup_patch"), task.id)
    test_patch = _test_patch(tests.get("test_patch"), task.id)
    return CommandTests(
        command=command,
        workdir=workdir,
        timeout_seconds=timeout_seconds,
        setup_patch=setup_patch,
        test_patch=test_patch,
    )


def candidate_policy(task: SecureBenchTask) -> CandidatePatchPolicy:
    """Return structured candidate patch policy for a repo-patch task."""
    return _candidate_patch_policy(resource_value(task, "candidate_policy", None))


def evaluate_candidate_patch_policy(
    candidate: str,
    policy: CandidatePatchPolicy | None = None,
) -> CandidatePatchPolicyDecision:
    """Return whether a candidate patch only touches verifier-safe paths."""
    policy = policy or CandidatePatchPolicy()
    paths = changed_paths_from_patch(candidate)

    hard_denied = tuple(path for path in paths if _is_hard_denied_candidate_path(path))
    if hard_denied:
        return CandidatePatchPolicyDecision(
            paths=paths,
            applied_paths=paths,
            stripped_paths=(),
            denied_paths=hard_denied,
            filtered_patch=candidate,
            failure_reason="candidate_patch_policy_violation",
        )

    filtered_patch, stripped_paths = _filter_preserved_file_diffs(candidate, policy.patch_preserved_paths)
    applied_paths = tuple(path for path in paths if path not in stripped_paths)
    if paths and not applied_paths:
        return CandidatePatchPolicyDecision(
            paths=paths,
            applied_paths=(),
            stripped_paths=stripped_paths,
            denied_paths=(),
            filtered_patch=filtered_patch,
            failure_reason="empty_filtered_candidate_patch",
        )

    denied = []
    for path in applied_paths:
        if policy.allow_paths and not _matches_any(path, policy.allow_paths):
            denied.append(path)
            continue
        if _is_sensitive_candidate_path(path) and not _matches_any(path, policy.allow_sensitive_paths):
            denied.append(path)
    return CandidatePatchPolicyDecision(
        paths=paths,
        applied_paths=applied_paths,
        stripped_paths=stripped_paths,
        denied_paths=tuple(denied),
        filtered_patch=filtered_patch,
        failure_reason="candidate_patch_policy_violation" if denied else None,
    )


def candidate_policy_error(decision: CandidatePatchPolicyDecision) -> str:
    if decision.failure_reason == "empty_filtered_candidate_patch":
        stripped = ", ".join(decision.stripped_paths)
        return f"candidate patch has no remaining changes after stripping preserved path(s): {stripped}"
    denied = ", ".join(decision.denied_paths)
    return f"candidate patch touches denied path(s): {denied}"


def changed_paths_from_patch(patch: str) -> tuple[str, ...]:
    """Extract repository paths mentioned as changed by a git-style patch."""
    paths: list[str] = []
    for line in patch.splitlines():
        for path in _paths_from_patch_line(line):
            normalized = _normalize_patch_path(path)
            if normalized is not None and normalized not in paths:
                paths.append(normalized)
    return tuple(paths)


def _paths_from_patch_line(line: str) -> tuple[str, ...]:
    if line.startswith("diff --git "):
        match = re.match(r"diff --git (?:\"?a/(.+?)\"?) (?:\"?b/(.+?)\"?)$", line)
        if match is None:
            return ()
        return (match.group(1), match.group(2))
    if line.startswith("rename from ") or line.startswith("rename to "):
        return (line.split(" ", 2)[2],)
    if line.startswith("--- ") or line.startswith("+++ "):
        value = line[4:].split("\t", 1)[0]
        if value == "/dev/null":
            return ()
        return (value,)
    return ()


def _normalize_patch_path(path: str) -> str | None:
    raw = path.strip().strip('"')
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    if raw in ("", "/dev/null"):
        return None
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return raw
    return str(candidate)


def _is_sensitive_candidate_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return True
    parts = tuple(part.lower() for part in candidate.parts)
    name = parts[-1] if parts else ""
    if parts and parts[0] in DEFAULT_DENIED_ROOTS:
        return True
    if any(part in DEFAULT_DENIED_PARTS for part in parts):
        return True
    if name in DEFAULT_DENIED_PATH_NAMES:
        return True
    if name.startswith("pytest.") or name.startswith("noxfile."):
        return True
    if name.endswith(DEFAULT_DENIED_SHELL_SUFFIXES):
        return True
    if name.endswith(DEFAULT_DENIED_PATH_SUFFIXES) and name not in {"readme.md"}:
        return True
    return False


def _is_hard_denied_candidate_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return True
    parts = tuple(part.lower() for part in candidate.parts)
    return bool(parts and parts[0] == "securebench")


def _filter_preserved_file_diffs(patch: str, preserved_paths: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    if not preserved_paths:
        return patch, ()

    preamble, sections = _git_file_diff_sections(patch)
    if not sections:
        return patch, ()

    kept = [preamble]
    stripped: list[str] = []
    for section in sections:
        paths = changed_paths_from_patch(section)
        if any(_matches_any(path, preserved_paths) for path in paths):
            for path in paths:
                if path not in stripped:
                    stripped.append(path)
            continue
        kept.append(section)
    return "".join(kept), tuple(stripped)


def _git_file_diff_sections(patch: str) -> tuple[str, tuple[str, ...]]:
    lines = patch.splitlines(keepends=True)
    preamble: list[str] = []
    sections: list[str] = []
    current: list[str] | None = None

    for line in lines:
        if line.startswith("diff --git "):
            if current is not None:
                sections.append("".join(current))
            current = [line]
            continue
        if current is None:
            preamble.append(line)
        else:
            current.append(line)

    if current is not None:
        sections.append("".join(current))
    return "".join(preamble), tuple(sections)


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_path_matches(path, pattern) for pattern in patterns)


def _path_matches(path: str, pattern: str) -> bool:
    normalized = str(PurePosixPath(pattern))
    if fnmatch.fnmatch(path, normalized):
        return True
    if normalized.endswith("/"):
        return path.startswith(normalized)
    return path == normalized or path.startswith(normalized + "/")


def environment_workdir_for_task(task: SecureBenchTask) -> str:
    """Return the benchmark environment workdir selected for repo-patch checks."""
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    environment = metadata.get("environment")
    workdir = environment.get("workdir") if isinstance(environment, dict) else None
    if not isinstance(workdir, str) or not workdir.strip():
        raise ConfigError(
            "repo_patch verification requires benchmark environment.workdir; "
            "set defaults.environment.workdir in the manifest or environment.workdir on the benchmark row"
        )
    return workdir.strip()


def _write_trusted_patch(root: Path, path: str, content: str) -> None:
    relative = _safe_relative_patch_path(path)
    target = root.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def _safe_relative_patch_path(path: str) -> PurePosixPath:
    if not isinstance(path, str) or not path:
        raise ConfigError("trusted patch path must be a non-empty relative path")
    if "\\" in path:
        raise ConfigError(f"trusted patch path may not contain backslashes: {path!r}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        raise ConfigError(f"trusted patch path may not be absolute: {path!r}")
    if ".." in candidate.parts:
        raise ConfigError(f"trusted patch path may not contain '..': {path!r}")
    if str(candidate) in ("", "."):
        raise ConfigError("trusted patch path must be a non-empty relative path")
    return candidate


def _absolute_container_path(path: str, field: str) -> str:
    if not isinstance(path, str) or not path:
        raise ConfigError(f"{field} must be a non-empty absolute container path")
    if "\\" in path:
        raise ConfigError(f"{field} may not contain backslashes")
    candidate = PurePosixPath(path)
    allowed_root = PurePosixPath("/opt/securebench")
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ConfigError(f"{field} must be an absolute container path without '..'")
    if not (candidate == allowed_root or candidate.is_relative_to(allowed_root)):
        raise ConfigError(f"{field} must be under {allowed_root}")
    return str(candidate)


def _command(value: object, task_id: str) -> str | tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(value)
    raise ConfigError(f"repo_patch task {task_id!r} requires tests.command as a non-empty string or string array")


def _test_patch(value: object, task_id: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict):
        patch = value.get("patch")
        if value.get("source") == "inline" and isinstance(patch, str) and patch.strip():
            return patch
    raise ConfigError(f"repo_patch task {task_id!r} has invalid tests.test_patch")


def _candidate_patch_policy(value: object) -> CandidatePatchPolicy:
    if value is None:
        return CandidatePatchPolicy()
    if not isinstance(value, dict):
        raise ConfigError("eval.candidate_policy must be an object")
    return CandidatePatchPolicy(
        allow_paths=_string_tuple(value.get("allow_paths"), "eval.candidate_policy.allow_paths"),
        allow_sensitive_paths=_string_tuple(
            value.get("allow_sensitive_paths"),
            "eval.candidate_policy.allow_sensitive_paths",
        ),
        patch_preserved_paths=_string_tuple(
            value.get("patch_preserved_paths"),
            "eval.candidate_policy.patch_preserved_paths",
        ),
    )


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(item.strip() for item in value)
    raise ConfigError(f"{field} must be a string array")


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ConfigError(f"{field} must be a non-empty string")


def _optional_positive_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    raise ConfigError(f"{field} must be a positive number")


def _failed_result(
    task: SecureBenchTask,
    verifier: str,
    image: str,
    workdir: str,
    phase: str,
    result: CommandResult,
    **metadata: object,
) -> VerificationResult:
    return VerificationResult(
        task_id=task.id,
        status="failed",
        passed=False,
        score=0.0,
        stdout=result.stdout,
        stderr=result.stderr,
        metadata={
            "verifier": verifier,
            "image": image,
            "workdir": workdir,
            "command": result.command,
            "exit_code": result.exit_code,
            "phase": phase,
            **timeout_metadata(result),
            **metadata,
        },
    )


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()
