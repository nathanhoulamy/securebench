"""Verifier for image-backed repo-patch benchmark-pack tasks."""

from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from typing import Any, Callable

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, DockerSandbox, Sandbox
from securebench.tasks import SecureBenchTask, resource_text, resource_value
from securebench.verifiers.base import VerificationResult, Verifier, timeout_metadata
from securebench.verifiers.code_completion import environment_image_for_task


SandboxFactory = Callable[..., Sandbox]
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
    "sitecustomize.py",
    "tox.ini",
    "usercustomize.py",
    "yarn.lock",
}
DEFAULT_DENIED_PATH_SUFFIXES = (
    ".lock",
    ".pth",
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
        workspace_mount_target: str = "/securebench-workspace",
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.timeout_seconds = timeout_seconds
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
        sandbox = self._sandbox(image)
        close_sandbox = self.sandbox_factory is None
        try:
            return self._verify_in_sandbox(
                task,
                tests,
                sandbox,
                image=image,
                workdir=workdir,
                timeout=timeout,
                policy=policy,
                policy_decision=policy_decision,
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
        policy: "CandidatePatchPolicy",
        policy_decision: "CandidatePatchPolicyDecision",
    ) -> VerificationResult:
        base_commit = resource_text(task, "base_commit")
        head = sandbox.run(["git", "rev-parse", "HEAD"], workdir=workdir, timeout=timeout)
        if head.exit_code != 0:
            return _failed_result(task, "repo_patch", image, workdir, "base_commit", head)
        image_commit = head.stdout.strip()
        if image_commit != base_commit:
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "base_commit",
                CommandResult(("base_commit",), 1, "", "benchmark image HEAD does not match declared base commit"),
                base_commit=base_commit,
                image_commit=image_commit,
                failure_reason="base_commit_mismatch",
            )

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
                image_commit=image_commit,
                **_containment_metadata(policy, policy_decision),
                denied_candidate_patch_paths=policy_decision.denied_paths,
                failure_reason=policy_decision.failure_reason or "candidate_patch_policy_violation",
            )

        if tests.setup_patch is not None:
            apply_setup = sandbox.run(
                ["git", "apply", "--binary"],
                workdir=workdir,
                timeout=timeout,
                stdin=tests.setup_patch,
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
                    image_commit=image_commit,
                )

        baseline = _commit_verifier_baseline(sandbox, workdir=workdir, timeout=timeout)
        if baseline.exit_code != 0:
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "verifier_baseline",
                baseline,
                base_commit=base_commit,
                image_commit=image_commit,
            )

        apply_candidate = sandbox.run(
            ["git", "apply", "--binary"],
            workdir=workdir,
            timeout=timeout,
            stdin=policy_decision.filtered_patch,
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
                image_commit=image_commit,
                **_containment_metadata(policy, policy_decision),
            )

        actual_paths_result, actual_paths = _actual_candidate_paths(sandbox, workdir=workdir, timeout=timeout)
        if actual_paths_result is not None:
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "candidate_paths",
                actual_paths_result,
                base_commit=base_commit,
                image_commit=image_commit,
                **_containment_metadata(policy, policy_decision),
            )
        actual_policy_decision = evaluate_candidate_paths_policy(actual_paths, policy)
        if not actual_policy_decision.allowed:
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "candidate_policy",
                CommandResult(("candidate_policy",), 1, "", candidate_policy_error(actual_policy_decision)),
                base_commit=base_commit,
                image_commit=image_commit,
                **_containment_metadata(policy, policy_decision, actual_paths=actual_paths),
                denied_candidate_patch_paths=actual_policy_decision.denied_paths,
                failure_reason=actual_policy_decision.failure_reason or "candidate_patch_policy_violation",
            )
        if set(actual_paths) != set(policy_decision.applied_paths):
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "candidate_policy",
                CommandResult(("candidate_policy",), 1, "", "candidate patch paths differ from post-apply repository paths"),
                base_commit=base_commit,
                image_commit=image_commit,
                **_containment_metadata(policy, policy_decision, actual_paths=actual_paths),
                failure_reason="candidate_patch_path_mismatch",
            )

        if tests.test_patch is not None:
            apply_tests = sandbox.run(
                ["git", "apply", "--binary"],
                workdir=workdir,
                timeout=timeout,
                stdin=tests.test_patch,
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
                    image_commit=image_commit,
                    **_containment_metadata(policy, policy_decision, actual_paths=actual_paths),
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
                "image_commit": image_commit,
                "command": result.command,
                "exit_code": result.exit_code,
                "phase": "checks",
                **_containment_metadata(policy, policy_decision, actual_paths=actual_paths),
                **timeout_metadata(result),
            },
        )

    def _sandbox(self, image: str) -> Sandbox:
        if self.sandbox_factory is not None:
            return self.sandbox_factory(image=image)
        return DockerSandbox(
            image=image,
            network="none",
            read_only=False,
            workspace_mount_target=self.workspace_mount_target,
        )


class CommandTests:
    def __init__(
        self,
        *,
        command: tuple[str, ...],
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
    paths = _canonical_patch_paths(candidate)
    if paths is None:
        return CandidatePatchPolicyDecision(
            paths=changed_paths_from_patch(candidate),
            applied_paths=(),
            stripped_paths=(),
            denied_paths=(),
            filtered_patch=candidate,
            failure_reason="noncanonical_candidate_patch",
        )

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

    decision = evaluate_candidate_paths_policy(applied_paths, policy)
    decision.paths = paths
    decision.stripped_paths = stripped_paths
    decision.filtered_patch = filtered_patch
    return decision


def evaluate_candidate_paths_policy(
    paths: tuple[str, ...],
    policy: CandidatePatchPolicy | None = None,
) -> CandidatePatchPolicyDecision:
    """Return whether repository paths stay inside the candidate edit policy."""
    policy = policy or CandidatePatchPolicy()
    hard_denied = tuple(path for path in paths if _is_hard_denied_candidate_path(path))
    denied = list(hard_denied)
    for path in paths:
        if path in hard_denied:
            continue
        if policy.allow_paths and not _matches_any(path, policy.allow_paths):
            denied.append(path)
            continue
        if _is_sensitive_candidate_path(path) and not _matches_any(path, policy.allow_sensitive_paths):
            denied.append(path)
    return CandidatePatchPolicyDecision(
        paths=paths,
        applied_paths=paths,
        stripped_paths=(),
        denied_paths=tuple(denied),
        filtered_patch="",
        failure_reason="candidate_patch_policy_violation" if denied else None,
    )


def candidate_policy_error(decision: CandidatePatchPolicyDecision) -> str:
    if decision.failure_reason == "noncanonical_candidate_patch":
        return "candidate patch must contain unambiguous canonical 'diff --git' file sections"
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


def _canonical_patch_paths(patch: str) -> tuple[str, ...] | None:
    preamble, sections = _git_file_diff_sections(patch)
    if preamble.strip() or not sections:
        return None
    for section in sections:
        lines = section.splitlines()
        if not lines or _diff_git_paths(lines[0]) is None:
            return None
    paths = changed_paths_from_patch(patch)
    return paths or None


def _paths_from_patch_line(line: str) -> tuple[str, ...]:
    if line.startswith("diff --git "):
        return _diff_git_paths(line) or ()
    if line.startswith("rename from ") or line.startswith("rename to "):
        return (line.split(" ", 2)[2],)
    if line.startswith("--- ") or line.startswith("+++ "):
        value = line[4:].split("\t", 1)[0]
        if value == "/dev/null":
            return ()
        return (value,)
    return ()


def _diff_git_paths(line: str) -> tuple[str, str] | None:
    tokens = _git_header_tokens(line.removeprefix("diff --git "))
    if tokens is None:
        return None
    left, right = tokens
    if not left.startswith("a/") or not right.startswith("b/"):
        return None
    paths = (left[2:], right[2:])
    if any(_normalize_patch_path(path) is None for path in paths):
        return None
    return paths


def _git_header_tokens(value: str) -> tuple[str, str] | None:
    tokens: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == " ":
            return None
        if value[index] == '"':
            index += 1
            token: list[str] = []
            while index < len(value) and value[index] != '"':
                if value[index] == "\\":
                    if index + 1 >= len(value):
                        return None
                    token.extend(value[index : index + 2])
                    index += 2
                    continue
                token.append(value[index])
                index += 1
            if index >= len(value) or value[index] != '"':
                return None
            index += 1
            tokens.append("".join(token))
        else:
            end = value.find(" ", index)
            if end == -1:
                end = len(value)
            tokens.append(value[index:end])
            index = end
        if index == len(value):
            break
        if value[index] != " ":
            return None
        index += 1
    if len(tokens) != 2 or not all(tokens):
        return None
    return tokens[0], tokens[1]


def _normalize_patch_path(path: str) -> str | None:
    raw = _decode_git_patch_path(path.strip().strip('"'))
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
    if parts and parts[0] == "pytest":
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


def _decode_git_patch_path(path: str) -> str:
    """Decode Git-style C escapes so policy checks match paths git applies."""
    def replace(match: re.Match[str]) -> str:
        value = match.group(1)
        if value is not None:
            return chr(int(value, 8))
        escaped = match.group(2)
        return {
            "a": "\a",
            "b": "\b",
            "f": "\f",
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "v": "\v",
            "\\": "\\",
            '"': '"',
        }.get(escaped, escaped)

    return re.sub(r"\\([0-7]{1,3})|\\(.)", replace, path)


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


def _commit_verifier_baseline(sandbox: Sandbox, *, workdir: str, timeout: float) -> CommandResult:
    staged = sandbox.run(["git", "add", "--all", "--"], workdir=workdir, timeout=timeout)
    if staged.exit_code != 0:
        return staged
    return sandbox.run(
        [
            "git",
            "-c",
            "user.name=SecureBench",
            "-c",
            "user.email=securebench@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--no-verify",
            "--allow-empty",
            "-m",
            "securebench verifier baseline",
        ],
        workdir=workdir,
        timeout=timeout,
    )


def _actual_candidate_paths(
    sandbox: Sandbox,
    *,
    workdir: str,
    timeout: float,
) -> tuple[CommandResult | None, tuple[str, ...]]:
    tracked = sandbox.run(
        ["git", "diff", "--name-only", "--no-ext-diff", "--no-renames", "-z", "HEAD", "--"],
        workdir=workdir,
        timeout=timeout,
    )
    if tracked.exit_code != 0:
        return tracked, ()
    untracked = sandbox.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"],
        workdir=workdir,
        timeout=timeout,
    )
    if untracked.exit_code != 0:
        return untracked, ()
    try:
        paths = _nul_paths(tracked.stdout + untracked.stdout)
    except ValueError as exc:
        return CommandResult(("candidate_paths",), 1, "", str(exc)), ()
    return None, paths


def _nul_paths(output: str) -> tuple[str, ...]:
    paths: list[str] = []
    for value in output.split("\x00"):
        if not value:
            continue
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"post-apply repository path is unsafe: {value!r}")
        normalized = str(candidate)
        if normalized not in paths:
            paths.append(normalized)
    return tuple(paths)


def _containment_metadata(
    policy: CandidatePatchPolicy,
    decision: CandidatePatchPolicyDecision,
    *,
    actual_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "candidate_patch_paths": decision.paths,
        "applied_candidate_patch_paths": decision.applied_paths,
        "stripped_candidate_patch_paths": decision.stripped_paths,
        "actual_candidate_patch_paths": actual_paths,
        "candidate_allow_paths_configured": bool(policy.allow_paths),
        "containment_profile": "shared_runtime",
        "hidden_test_runtime_secrecy": False,
    }


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


def _command(value: object, task_id: str) -> tuple[str, ...]:
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(value)
    raise ConfigError(f"repo_patch task {task_id!r} requires tests.command as a non-empty string array")


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
