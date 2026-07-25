import subprocess

import pytest

from securebench.dangerous_commands import VerificationPolicy
from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, HostSandbox, Sandbox
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
    def __init__(
        self,
        *,
        image=None,
        mounts=(),
        head="abc123\n",
        actual_paths=("app.py",),
        untracked_paths=(),
        apply_results=(),
        check_result=(0, "passed", ""),
    ):
        self.image = image
        self.mounts = tuple(mounts)
        self.head = head
        self.actual_paths = tuple(actual_paths)
        self.untracked_paths = tuple(untracked_paths)
        self.apply_results = list(apply_results)
        self.check_result = check_result
        self.commands = []
        self.stdins = []
        self.files = {}

    def run(self, command, *, workdir=None, timeout=None, stdin=None):
        normalized = tuple(command) if not isinstance(command, str) else ("sh", "-lc", command)
        self.commands.append((command, workdir, timeout))
        self.stdins.append(stdin)
        if normalized == ("git", "rev-parse", "HEAD"):
            return CommandResult(normalized, 0, self.head, "")
        if normalized == ("git", "apply", "--binary") and self.apply_results:
            result = self.apply_results.pop(0)
            return CommandResult(normalized, result[0], result[1], result[2])
        if normalized == ("git", "diff", "--name-only", "--no-ext-diff", "--no-renames", "-z", "HEAD", "--"):
            return CommandResult(normalized, 0, "".join(f"{path}\0" for path in self.actual_paths), "")
        if normalized == ("git", "ls-files", "--others", "--exclude-standard", "-z", "--"):
            return CommandResult(normalized, 0, "".join(f"{path}\0" for path in self.untracked_paths), "")
        if normalized[:3] == ("python", "-m", "pytest"):
            if isinstance(self.check_result, CommandResult):
                return self.check_result
            return CommandResult(normalized, self.check_result[0], self.check_result[1], self.check_result[2])
        return CommandResult(normalized, 0, "", "")

    def write_file(self, path, content):
        self.files[str(path)] = content

    def read_file(self, path):
        return self.files[str(path)]

    def extract_file(self, path):
        return self.files[str(path)].encode()


def make_task(*, image="repo-image:latest", workdir="/testbed", base_commit="abc123", tests=None, policy=None):
    resources = {
        "repo": {"value": "example/project", "visibility": "public"},
        "base_commit": {"value": base_commit, "visibility": "public"},
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
    tests = command_tests(make_task(tests={"source": "command", "command": ["pytest", "-q"], "timeout_seconds": 12}))

    assert tests.command == ("pytest", "-q")
    assert tests.timeout_seconds == 12.0
    assert tests.test_patch is None


def test_command_tests_reject_shell_string_command():
    with pytest.raises(ConfigError, match="non-empty string array"):
        command_tests(make_task(tests={"source": "command", "command": "pytest -q"}))


def test_candidate_policy_parses_eval_policy_resource():
    policy = candidate_policy(
        make_task(
            tests={"source": "command", "command": ["pytest", "-q"]},
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


def test_changed_paths_from_patch_decodes_git_c_style_escapes():
    patch = 'diff --git "a/tests\\057test_bug.py" "b/tests\\057test_bug.py"\n'

    assert changed_paths_from_patch(patch) == ("tests/test_bug.py",)


def test_candidate_patch_policy_accepts_quoted_git_path_with_space():
    decision = evaluate_candidate_patch_policy('diff --git "a/src/file name.py" "b/src/file name.py"\n')

    assert decision.allowed is True
    assert decision.paths == ("src/file name.py",)


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_bug.py",
        "app/tests/test_bug.py",
        "pyproject.toml",
        "package.json",
        "pytest/__main__.py",
        "requirements.txt",
        ".github/workflows/ci.yml",
        "scripts/run_tests.sh",
        "securebench/evaluation_inputs/test.patch",
        "sitecustomize.py",
        "usercustomize.py",
    ],
)
def test_candidate_patch_policy_rejects_sensitive_paths(path):
    decision = evaluate_candidate_patch_policy(f"diff --git a/{path} b/{path}\n")

    assert decision.allowed is False
    assert decision.denied_paths == (path,)


def test_candidate_patch_policy_rejects_git_c_style_sensitive_path():
    patch = 'diff --git "a/tests\\057test_bug.py" "b/tests\\057test_bug.py"\n'

    decision = evaluate_candidate_patch_policy(patch)

    assert decision.allowed is False
    assert decision.denied_paths == ("tests/test_bug.py",)


def test_candidate_patch_policy_allows_application_yaml_by_default():
    decision = evaluate_candidate_patch_policy("diff --git a/config/routes.yaml b/config/routes.yaml\n")

    assert decision.allowed is True


def test_candidate_patch_policy_allows_sensitive_paths_when_explicit():
    decision = evaluate_candidate_patch_policy(
        "diff --git a/tests/test_bug.py b/tests/test_bug.py\n",
        candidate_policy(
            make_task(
                tests={"source": "command", "command": ["pytest", "-q"]},
                policy={"allow_sensitive_paths": ["tests/test_bug.py"]},
            )
        ),
    )

    assert decision.allowed is True
    assert decision.denied_paths == ()


def test_candidate_patch_policy_enforces_allow_paths():
    policy = candidate_policy(
        make_task(
            tests={"source": "command", "command": ["pytest", "-q"]},
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
            tests={"source": "command", "command": ["pytest", "-q"]},
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
            tests={"source": "command", "command": ["pytest", "-q"]},
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
            tests={"source": "command", "command": ["pytest", "-q"]},
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
    sandbox = FakeSandbox()
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox, timeout_seconds=99)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert sandbox.image is None
    assert sandbox.commands == [
        (["git", "rev-parse", "HEAD"], "/testbed", 99.0),
        (["git", "apply", "--binary"], "/testbed", 99.0),
        (["git", "add", "--all", "--"], "/testbed", 99.0),
        (
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
            "/testbed",
            99.0,
        ),
        (["git", "apply", "--binary"], "/testbed", 99.0),
        (["git", "diff", "--name-only", "--no-ext-diff", "--no-renames", "-z", "HEAD", "--"], "/testbed", 99.0),
        (["git", "ls-files", "--others", "--exclude-standard", "-z", "--"], "/testbed", 99.0),
        (["git", "apply", "--binary"], "/testbed", 99.0),
        (("python", "-m", "pytest", "tests/test_bug.py"), "/testbed", 99.0),
    ]
    assert [value for value in sandbox.stdins if value is not None] == [
        "diff --git a/bug.py b/bug.py\n",
        "diff --git a/app.py b/app.py\n",
        "diff --git a/tests/test_bug.py b/tests/test_bug.py\n",
    ]
    assert result.status == "passed"
    assert result.passed is True
    assert result.metadata["verifier"] == "repo_patch"
    assert result.metadata["image"] == "repo-image:latest"
    assert result.metadata["phase"] == "checks"
    assert result.metadata["candidate_patch_paths"] == ("app.py",)
    assert result.metadata["actual_candidate_patch_paths"] == ("app.py",)
    assert result.metadata["candidate_allow_paths_configured"] is False
    assert result.metadata["containment_profile"] == "shared_runtime"
    assert result.metadata["hidden_test_runtime_secrecy"] is False


def test_repo_patch_verifier_does_not_mount_trusted_eval_patches():
    created = {}

    def sandbox_factory(**kwargs):
        created.update(kwargs)
        return FakeSandbox()

    verifier = RepoPatchVerifier(sandbox_factory=sandbox_factory)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "passed"
    assert created == {"image": "repo-image:latest", "network": "none"}


def test_repo_patch_verifier_allows_network_when_tester_opts_in():
    created = {}

    def sandbox_factory(**kwargs):
        created.update(kwargs)
        return FakeSandbox()

    verifier = RepoPatchVerifier(sandbox_factory=sandbox_factory)

    result = verifier.verify(
        make_task(),
        "diff --git a/app.py b/app.py\n",
        verification_policy={"allow_network": True},
    )

    assert result.status == "passed"
    assert created == {"image": "repo-image:latest", "network": "bridge"}


def test_repo_patch_verifier_accepts_parsed_verification_policy():
    created = {}

    def sandbox_factory(**kwargs):
        created.update(kwargs)
        return FakeSandbox()

    verifier = RepoPatchVerifier(sandbox_factory=sandbox_factory)

    result = verifier.verify(
        make_task(),
        "diff --git a/app.py b/app.py\n",
        verification_policy=VerificationPolicy(allow_network=True),
    )

    assert result.status == "passed"
    assert created == {"image": "repo-image:latest", "network": "bridge"}


def test_repo_patch_verifier_applies_trusted_patches_over_stdin_without_workspace_copy():
    sandbox = FakeSandbox()
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "passed"
    assert sandbox.files == {}
    assert [value for value in sandbox.stdins if value is not None] == [
        "diff --git a/bug.py b/bug.py\n",
        "diff --git a/app.py b/app.py\n",
        "diff --git a/tests/test_bug.py b/tests/test_bug.py\n",
    ]


def test_repo_patch_verifier_applies_candidate_over_stdin_in_real_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SecureBench Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "securebench@example.invalid"], cwd=repo, check=True)
    (repo / "app.py").write_text("old\n")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    task = make_task(
        workdir=".",
        base_commit=base_commit,
        tests={"source": "command", "command": ["sh", "-c", "test \"$(cat app.py)\" = new"]},
    )
    candidate = "\n".join(
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
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: HostSandbox(root=repo))

    result = verifier.verify(task, candidate)

    assert result.status == "passed"
    assert result.metadata["actual_candidate_patch_paths"] == ("app.py",)
    assert (repo / "app.py").read_text() == "new\n"
    assert (repo / "securebench" / "candidate.patch").exists() is False


def test_repo_patch_verifier_reports_candidate_patch_failure():
    sandbox = FakeSandbox(apply_results=[(0, "", ""), (1, "", "bad patch")])
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.stderr == "bad patch"
    assert result.metadata["phase"] == "candidate_patch"
    assert result.metadata["candidate_patch_paths"] == ("app.py",)
    assert result.metadata["applied_candidate_patch_paths"] == ("app.py",)
    assert result.metadata["stripped_candidate_patch_paths"] == ()


def test_repo_patch_verifier_rejects_headerless_candidate_patch():
    sandbox = FakeSandbox()
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "--- a/app.py\n+++ b/app.py\n")

    assert result.status == "failed"
    assert result.metadata["phase"] == "candidate_policy"
    assert result.metadata["failure_reason"] == "noncanonical_candidate_patch"
    assert sandbox.commands == [(["git", "rev-parse", "HEAD"], "/testbed", 300.0)]


def test_repo_patch_verifier_rejects_ambiguous_git_section_header():
    sandbox = FakeSandbox()
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/file name.py b/file name.py\n")

    assert result.status == "failed"
    assert result.metadata["failure_reason"] == "noncanonical_candidate_patch"


def test_repo_patch_verifier_rejects_base_commit_mismatch_before_apply():
    sandbox = FakeSandbox(head="different\n")
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.metadata["phase"] == "base_commit"
    assert result.metadata["failure_reason"] == "base_commit_mismatch"
    assert sandbox.commands == [(["git", "rev-parse", "HEAD"], "/testbed", 300.0)]


def test_repo_patch_verifier_rejects_sensitive_candidate_patch_before_apply():
    sandbox = FakeSandbox()
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/tests/test_bug.py b/tests/test_bug.py\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.metadata["phase"] == "candidate_policy"
    assert result.metadata["failure_reason"] == "candidate_patch_policy_violation"
    assert result.metadata["denied_candidate_patch_paths"] == ("tests/test_bug.py",)
    assert sandbox.commands == [(["git", "rev-parse", "HEAD"], "/testbed", 300.0)]


def test_repo_patch_verifier_allows_sensitive_candidate_patch_when_explicit():
    sandbox = FakeSandbox(actual_paths=("tests/test_bug.py",))
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
    assert "diff --git a/tests/test_bug.py b/tests/test_bug.py\n" in sandbox.stdins


def test_repo_patch_verifier_applies_filtered_candidate_patch():
    sandbox = FakeSandbox()
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
    assert "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "",
        ]
    ) in sandbox.stdins
    assert result.metadata["candidate_patch_paths"] == ("app.py", "tests/test_bug.py")
    assert result.metadata["applied_candidate_patch_paths"] == ("app.py",)
    assert result.metadata["stripped_candidate_patch_paths"] == ("tests/test_bug.py",)


def test_repo_patch_verifier_fails_when_filtered_candidate_patch_is_empty():
    sandbox = FakeSandbox()
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)
    task = make_task(policy={"patch_preserved_paths": ["tests/"]})

    result = verifier.verify(task, "diff --git a/tests/test_bug.py b/tests/test_bug.py\n")

    assert result.status == "failed"
    assert result.metadata["phase"] == "candidate_policy"
    assert result.metadata["failure_reason"] == "empty_filtered_candidate_patch"
    assert result.metadata["candidate_patch_paths"] == ("tests/test_bug.py",)
    assert result.metadata["applied_candidate_patch_paths"] == ()
    assert result.metadata["stripped_candidate_patch_paths"] == ("tests/test_bug.py",)
def test_repo_patch_verifier_reports_empty_candidate_patch_as_failed_result():
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: FakeSandbox())

    result = verifier.verify(make_task(), "")

    assert result.status == "failed"
    assert result.passed is False
    assert result.stderr == "empty candidate patch"
    assert result.metadata["phase"] == "candidate_patch"
    assert result.metadata["failure_reason"] == "empty_candidate_patch"


def test_repo_patch_verifier_reports_failed_checks():
    sandbox = FakeSandbox(check_result=(1, "", "failed"))
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
    sandbox = FakeSandbox(check_result=timeout_result)
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox, timeout_seconds=99)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["failure_reason"] == "verifier_timeout"
    assert result.metadata["timed_out"] is True
    assert result.metadata["timeout_seconds"] == 99


def test_repo_patch_verifier_rejects_post_apply_sensitive_path():
    sandbox = FakeSandbox(actual_paths=("app.py", "tests/injected.py"))
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.metadata["phase"] == "candidate_policy"
    assert result.metadata["failure_reason"] == "candidate_patch_policy_violation"
    assert result.metadata["denied_candidate_patch_paths"] == ("tests/injected.py",)
    assert result.metadata["actual_candidate_patch_paths"] == ("app.py", "tests/injected.py")


def test_repo_patch_verifier_rejects_post_apply_path_mismatch():
    sandbox = FakeSandbox(actual_paths=("other.py",))
    verifier = RepoPatchVerifier(sandbox_factory=lambda **kwargs: sandbox)

    result = verifier.verify(make_task(), "diff --git a/app.py b/app.py\n")

    assert result.status == "failed"
    assert result.metadata["failure_reason"] == "candidate_patch_path_mismatch"
    assert result.metadata["actual_candidate_patch_paths"] == ("other.py",)
