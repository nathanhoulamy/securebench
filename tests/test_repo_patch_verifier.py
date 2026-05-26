import pytest

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import task_from_spec
from securebench.verifiers.repo_patch import (
    RepoPatchVerifier,
    candidate_policy,
    changed_paths_from_patch,
    command_tests,
    environment_workdir_for_task,
    evaluate_candidate_patch_policy,
)


class FakeSandbox(Sandbox):
    def __init__(self, *, image=None, results=None, mounts=()):
        self.image = image
        self.results = list(results or [])
        self.mounts = tuple(mounts)
        self.commands = []
        self.files = {}

    def run(self, command, *, workdir=None, timeout=None):
        normalized = tuple(command) if not isinstance(command, str) else ("sh", "-lc", command)
        self.commands.append((command, workdir, timeout))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, CommandResult):
                return result
            return CommandResult(normalized, result[0], result[1], result[2])
        return CommandResult(normalized, 0, "", "")

    def write_file(self, path, content):
        self.files[str(path)] = content

    def read_file(self, path):
        return self.files[str(path)]

    def extract_file(self, path):
        return self.files[str(path)].encode()


def make_task(*, image="repo-image:latest", workdir="/testbed", tests=None, policy=None):
    resources = {
        "repo": {"value": "example/project", "visibility": "public"},
        "base_commit": {"value": "abc123", "visibility": "public"},
        "instructions": {"value": "Fix the bug.", "visibility": "public"},
        "tests": {
            "value": tests
            if tests is not None
            else {
                "source": "command",
                "command": ["python", "-m", "pytest", "tests/test_bug.py"],
                "test_patch": {
                    "source": "inline",
                    "patch": "diff --git a/tests/test_bug.py b/tests/test_bug.py\n",
                },
                "setup_patch": {
                    "source": "inline",
                    "patch": "diff --git a/bug.py b/bug.py\n",
                },
            },
            "visibility": "evaluation_inputs",
        },
    }
    if policy is not None:
        resources["candidate_policy"] = {"value": policy, "visibility": "evaluation_inputs"}
    return task_from_spec(
        {
            "id": "repo-pack/fix-bug",
            "benchmark_id": "repo-pack",
            "task_type": "repo_patch",
            "metadata": {
                "environment": {"image": image, "workdir": workdir},
            },
            "resources": resources,
        }
    )


def test_command_tests_parse_command_test_shape():
    tests = command_tests(make_task(tests={"source": "command", "command": "pytest -q", "timeout_seconds": 12}))

    assert tests.command == "pytest -q"
    assert tests.timeout_seconds == 12.0
    assert tests.test_patch is None


def test_candidate_policy_parses_eval_policy_resource():
    policy = candidate_policy(
        make_task(
            tests={"source": "command", "command": "pytest -q"},
            policy={
                "allow_paths": ["src/"],
                "allow_sensitive_paths": ["src/project/tests/fixture.py"],
                "patch_preserved_paths": ["tests/public_test.py"],
            },
        )
    )

    assert policy.allow_paths == ("src/",)
    assert policy.allow_sensitive_paths == ("src/project/tests/fixture.py",)
    assert policy.patch_preserved_paths == ("tests/public_test.py",)


def test_changed_paths_from_patch_extracts_git_diff_paths():
    patch = "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "diff --git a/old.py b/new.py",
            "rename from old.py",
            "rename to new.py",
        ]
    )

    assert changed_paths_from_patch(patch) == ("app.py", "old.py", "new.py")


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_bug.py",
        "app/tests/test_bug.py",
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        ".github/workflows/ci.yml",
        "scripts/run_tests.sh",
        "securebench/evaluation_inputs/test.patch",
    ],
)
def test_candidate_patch_policy_rejects_sensitive_paths(path):
    decision = evaluate_candidate_patch_policy(f"diff --git a/{path} b/{path}\n")

    assert decision.allowed is False
    assert decision.denied_paths == (path,)


def test_candidate_patch_policy_allows_application_yaml_by_default():
    decision = evaluate_candidate_patch_policy("diff --git a/config/routes.yaml b/config/routes.yaml\n")

    assert decision.allowed is True


def test_candidate_patch_policy_allows_sensitive_paths_when_explicit():
    decision = evaluate_candidate_patch_policy(
        "diff --git a/tests/test_bug.py b/tests/test_bug.py\n",
        candidate_policy(
            make_task(
                tests={"source": "command", "command": "pytest -q"},
                policy={"allow_sensitive_paths": ["tests/test_bug.py"]},
            )
        ),
    )

    assert decision.allowed is True
    assert decision.denied_paths == ()


def test_candidate_patch_policy_enforces_allow_paths():
    policy = candidate_policy(
        make_task(
            tests={"source": "command", "command": "pytest -q"},
            policy={"allow_paths": ["src/"]},
        )
    )

    allowed = evaluate_candidate_patch_policy("diff --git a/src/app.py b/src/app.py\n", policy)
    denied = evaluate_candidate_patch_policy("diff --git a/app.py b/app.py\n", policy)

    assert allowed.allowed is True
    assert denied.allowed is False
    assert denied.denied_paths == ("app.py",)


def test_candidate_patch_policy_strips_preserved_file_diffs():
    patch = "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "diff --git a/tests/test_app.py b/tests/test_app.py",
            "--- a/tests/test_app.py",
            "+++ b/tests/test_app.py",
            "@@ -1 +1 @@",
            "-assert old",
            "+assert new",
            "",
        ]
    )
    policy = candidate_policy(
        make_task(
            tests={"source": "command", "command": "pytest -q"},
            policy={"patch_preserved_paths": ["tests/test_app.py"]},
        )
    )

    decision = evaluate_candidate_patch_policy(patch, policy)

    assert decision.allowed is True
    assert decision.paths == ("src/app.py", "tests/test_app.py")
    assert decision.applied_paths == ("src/app.py",)
    assert decision.stripped_paths == ("tests/test_app.py",)
    assert "diff --git a/src/app.py b/src/app.py" in decision.filtered_patch
    assert "diff --git a/tests/test_app.py b/tests/test_app.py" not in decision.filtered_patch


def test_candidate_patch_policy_fails_when_all_file_diffs_are_stripped():
    policy = candidate_policy(
        make_task(
            tests={"source": "command", "command": "pytest -q"},
            policy={"patch_preserved_paths": ["tests/"]},
        )
    )

    decision = evaluate_candidate_patch_policy("diff --git a/tests/test_app.py b/tests/test_app.py\n", policy)

    assert decision.allowed is False
    assert decision.failure_reason == "empty_filtered_candidate_patch"
    assert decision.denied_paths == ()
    assert decision.applied_paths == ()
    assert decision.stripped_paths == ("tests/test_app.py",)


def test_candidate_patch_policy_hard_denies_framework_paths_even_when_allowed():
    policy = candidate_policy(
        make_task(
            tests={"source": "command", "command": "pytest -q"},
            policy={
                "allow_sensitive_paths": ["securebench/evaluation_inputs/test.patch"],
                "patch_preserved_paths": ["securebench/evaluation_inputs/test.patch"],
            },
        )
    )

    decision = evaluate_candidate_patch_policy(
        "diff --git a/securebench/evaluation_inputs/test.patch b/securebench/evaluation_inputs/test.patch\n",
        policy,
    )

    assert decision.allowed is False
    assert decision.denied_paths == ("securebench/evaluation_inputs/test.patch",)
    assert decision.stripped_paths == ()


def test_environment_workdir_for_task_requires_workdir():
    assert environment_workdir_for_task(make_task(workdir="/repo")) == "/repo"

    with pytest.raises(ConfigError, match="environment.workdir"):
        environment_workdir_for_task(make_task(workdir=""))


def test_repo_patch_verifier_applies_candidate_and_test_patch_then_runs_checks():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "passed", "")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox, timeout_seconds=99)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert sandbox.image is None
    assert sandbox.files["securebench/candidate.patch"] == "diff --git a/app.py b/app.py\n"
    assert sandbox.commands == [
        (["git", "rev-parse", "HEAD"], "/testbed", 99.0),
        (["git", "apply", "--binary", "/opt/securebench/evaluation_inputs/setup.patch"], "/testbed", 99.0),
        (["git", "apply", "--binary", "/securebench-workspace/securebench/candidate.patch"], "/testbed", 99.0),
        (["git", "apply", "--binary", "/opt/securebench/evaluation_inputs/test.patch"], "/testbed", 99.0),
        (("python", "-m", "pytest", "tests/test_bug.py"), "/testbed", 99.0),
    ]
    assert result.status == "passed"
    assert result.passed is True
    assert result.metadata["verifier"] == "repo_patch"
    assert result.metadata["image"] == "repo-image:latest"
    assert result.metadata["phase"] == "checks"
    assert result.metadata["candidate_patch_paths"] == ("app.py",)


def test_repo_patch_verifier_mounts_trusted_eval_patches_read_only():
    created = {}

    def sandbox_factory(**kwargs):
        created.update(kwargs)
        mount_source = kwargs["mounts"][0].source
        created["setup_patch"] = (mount_source / "setup.patch").read_text()
        created["test_patch"] = (mount_source / "test.patch").read_text()
        return FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "passed", "")])

    verifier = RepoPatchVerifier(sandbox_factory=sandbox_factory)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "passed"
    mounts = created["mounts"]
    assert len(mounts) == 1
    assert mounts[0].target == "/opt/securebench/evaluation_inputs"
    assert mounts[0].read_only is True
    assert created["setup_patch"].startswith("diff --git")
    assert created["test_patch"].startswith("diff --git")


def test_repo_patch_verifier_applies_trusted_patch_from_protected_mount_not_workspace_copy():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "passed", "")])
    sandbox.files["securebench/evaluation_inputs/test.patch"] = "malicious workspace replacement"
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "passed"
    assert sandbox.files["securebench/evaluation_inputs/test.patch"] == "malicious workspace replacement"
    assert all(
        "/securebench-workspace/securebench/evaluation_inputs/test.patch" not in tuple(command)
        for command, _, _ in sandbox.commands
        if not isinstance(command, str)
    )
    assert (
        ["git", "apply", "--binary", "/opt/securebench/evaluation_inputs/test.patch"],
        "/testbed",
        300.0,
    ) in sandbox.commands


def test_repo_patch_verifier_reports_candidate_patch_failure():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (1, "", "bad patch")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "not a patch")

    assert result.status == "failed"
    assert result.passed is False
    assert result.stderr == "bad patch"
    assert result.metadata["phase"] == "candidate_patch"
    assert result.metadata["candidate_patch_paths"] == ()
    assert result.metadata["applied_candidate_patch_paths"] == ()
    assert result.metadata["stripped_candidate_patch_paths"] == ()


def test_repo_patch_verifier_rejects_sensitive_candidate_patch_before_apply():
    sandbox = FakeSandbox(results=[(0, "abc123\n", "")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/tests/test_bug.py b/tests/test_bug.py\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.metadata["phase"] == "candidate_policy"
    assert result.metadata["failure_reason"] == "candidate_patch_policy_violation"
    assert result.metadata["denied_candidate_patch_paths"] == ("tests/test_bug.py",)
    assert "securebench/candidate.patch" not in sandbox.files
    assert sandbox.commands == [(["git", "rev-parse", "HEAD"], "/testbed", 300.0)]


def test_repo_patch_verifier_allows_sensitive_candidate_patch_when_explicit():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "passed", "")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)
    task = make_task(
        tests={
            "source": "command",
            "command": ["python", "-m", "pytest", "tests/test_bug.py"],
            "setup_patch": {"source": "inline", "patch": "diff --git a/bug.py b/bug.py\n"},
            "test_patch": {"source": "inline", "patch": "diff --git a/tests/test_bug.py b/tests/test_bug.py\n"},
        },
        policy={"allow_sensitive_paths": ["tests/test_bug.py"]},
    )

    result = verifier.verify(task, "diff --git a/tests/test_bug.py b/tests/test_bug.py\n")

    assert result.status == "passed"
    assert sandbox.files["securebench/candidate.patch"] == "diff --git a/tests/test_bug.py b/tests/test_bug.py\n"


def test_repo_patch_verifier_applies_filtered_candidate_patch():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "passed", "")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)
    task = make_task(policy={"patch_preserved_paths": ["tests/test_bug.py"]})
    candidate = "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "diff --git a/tests/test_bug.py b/tests/test_bug.py",
            "--- a/tests/test_bug.py",
            "+++ b/tests/test_bug.py",
            "@@ -1 +1 @@",
            "-assert old",
            "+assert new",
            "",
        ]
    )

    result = verifier.verify(task, candidate)

    assert result.status == "passed"
    assert sandbox.files["securebench/candidate.patch"] == "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "",
        ]
    )
    assert result.metadata["candidate_patch_paths"] == ("app.py", "tests/test_bug.py")
    assert result.metadata["applied_candidate_patch_paths"] == ("app.py",)
    assert result.metadata["stripped_candidate_patch_paths"] == ("tests/test_bug.py",)


def test_repo_patch_verifier_fails_when_filtered_candidate_patch_is_empty():
    sandbox = FakeSandbox(results=[(0, "abc123\n", "")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)
    task = make_task(policy={"patch_preserved_paths": ["tests/"]})

    result = verifier.verify(task, "diff --git a/tests/test_bug.py b/tests/test_bug.py\n")

    assert result.status == "failed"
    assert result.metadata["phase"] == "candidate_policy"
    assert result.metadata["failure_reason"] == "empty_filtered_candidate_patch"
    assert result.metadata["candidate_patch_paths"] == ("tests/test_bug.py",)
    assert result.metadata["applied_candidate_patch_paths"] == ()
    assert result.metadata["stripped_candidate_patch_paths"] == ("tests/test_bug.py",)
    assert "securebench/candidate.patch" not in sandbox.files


def test_repo_patch_verifier_reports_empty_candidate_patch_as_failed_result():
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: FakeSandbox())

    result = verifier.verify(make_task(), "")

    assert result.status == "failed"
    assert result.passed is False
    assert result.stderr == "empty candidate patch"
    assert result.metadata["phase"] == "candidate_patch"
    assert result.metadata["failure_reason"] == "empty_candidate_patch"


def test_repo_patch_verifier_reports_failed_checks():
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), (1, "", "failed")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0
    assert result.stderr == "failed"
    assert result.metadata["exit_code"] == 1


def test_repo_patch_verifier_reports_timeout_metadata():
    timeout_result = CommandResult(
        ("python", "-m", "pytest", "tests/test_bug.py"),
        124,
        "partial out",
        "partial err",
        timed_out=True,
        timeout_seconds=99,
    )
    sandbox = FakeSandbox(results=[(0, "abc123\n", ""), (0, "", ""), (0, "", ""), (0, "", ""), timeout_result])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox, timeout_seconds=99)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["failure_reason"] == "verifier_timeout"
    assert result.metadata["timed_out"] is True
    assert result.metadata["timeout_seconds"] == 99
