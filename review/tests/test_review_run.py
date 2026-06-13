import json
from contextlib import nullcontext
from pathlib import Path

import pytest

import review.agents.live_openai as live_openai
from review.preflight import required_images_for_configs
from review.agents.live_openai import execute_action
from review.run import (
    REVIEW_ROOT,
    ReviewRunner,
    HarnessEgress,
    load_review_config,
    parse_review_config,
)
from securebench.candidates import CandidateArtifact
from securebench.sandboxes import CommandResult
from securebench.verifiers import VerificationResult


class FakeSandbox:
    instances = []

    def __init__(self, *, image, root, env=None, network="none", read_only=False, mounts=(), workspace_mount_target="/workspace"):
        self.image = image
        self.root = Path(root)
        self.env = {} if env is None else dict(env)
        self.network = network
        self.read_only = read_only
        self.mounts = tuple(mounts)
        self.workspace_mount_target = workspace_mount_target
        self.commands = []
        FakeSandbox.instances.append(self)

    def run(self, command, *, workdir=None, timeout=None, stdin=None):
        self.commands.append((command, workdir, timeout, stdin))
        (self.root / "review-agent-trace.json").write_text(
            json.dumps({"profile": self.env.get("REVIEW_PROFILE"), "actions": ["fake"], "violations": []})
        )
        return CommandResult(tuple(command) if not isinstance(command, str) else ("sh", "-lc", command), 0, "ok", "")

    def write_file(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def read_file(self, path):
        return (self.root / path).read_text()

    def extract_file(self, path):
        return (self.root / path).read_bytes()


def terminal_config(tmp_path, *, mode="external", provider=None):
    data = {
        "run": {"id": "review-test", "output_dir": str(tmp_path / "out")},
        "benchmark": {
            "manifest": str(tmp_path / "manifest.yaml"),
            "tasks": str(tmp_path / "tasks.jsonl"),
        },
        "adversary": {
            "mode": mode,
            "profile": "auto",
            "command": ["python3", "-c", "import json, os, pathlib; pathlib.Path(os.environ['REVIEW_TRACE_FILE']).write_text(json.dumps({'actions': [], 'violations': []}))"] if mode == "external" else None,
            "timeout_seconds": 30,
        },
    }
    if mode != "external":
        data["adversary"].pop("command")
    if provider is not None:
        data["provider"] = provider
    (tmp_path / "manifest.yaml").write_text(
        """
id: pack
version: 1
defaults:
  family: terminal_task
  environment:
    image: python:3.12-slim
"""
    )
    (tmp_path / "tasks.jsonl").write_text(
        json.dumps(
            {
                "id": "pack/task",
                "input": {"instructions": "Do not hardcode answer.txt."},
                "eval": {"checker": {"source": "pytest", "path": "checks"}},
            }
        )
        + "\n"
    )
    return data


def test_parse_review_config_accepts_external_command(tmp_path):
    data = terminal_config(tmp_path)
    data["adversary"] = {
        "mode": "external",
        "profile": "leak_probe",
        "command": ["python3", "agent.py"],
    }

    config = parse_review_config(data)

    assert config.adversary.mode == "external"
    assert config.adversary.command == ("python3", "agent.py")
    assert config.provider.enabled is False


@pytest.mark.parametrize("profile", ["artifact_forgery", "evaluator_escape"])
def test_parse_review_config_accepts_current_adversarial_profiles(tmp_path, profile):
    data = terminal_config(tmp_path)
    data["adversary"]["profile"] = profile

    config = parse_review_config(data)

    assert config.adversary.profile == profile


def test_parse_review_config_requires_external_command(tmp_path):
    data = terminal_config(tmp_path)
    data["adversary"] = {"mode": "external", "profile": "leak_probe"}

    with pytest.raises(Exception, match="adversary.command is required"):
        parse_review_config(data)


@pytest.mark.parametrize(
    "name",
    [
        "audit-terminal-live-openai.yaml",
        "audit-terminal-live-openai-leak-probe.yaml",
        "audit-terminal-live-openai-terminal-poison.yaml",
        "audit-terminal-live-openai-network-exfil.yaml",
        "audit-terminal-live-openai-output-only.yaml",
        "audit-terminal-live-openai-evaluator-escape.yaml",
        "audit-terminal-live-openai-artifact-forgery.yaml",
        "audit-repo-patch-live-openai-repo-tamper.yaml",
        "realism-swe-repo-tamper.yaml",
        "realism-swe-leak-probe.yaml",
        "realism-terminal-leak-probe.yaml",
        "realism-terminal-network-exfil.yaml",
        "realism-terminal-terminal-poison.yaml",
        "realism-terminal-artifact-forgery.yaml",
        "realism-terminal-output-only.yaml",
        "external-agent-example.yaml",
    ],
)
def test_load_example_config_resolves_paths(name):
    config = load_review_config(REVIEW_ROOT / "configs" / name)

    assert config.benchmark.manifest.name == "manifest.yaml"
    assert config.adversary.mode in {"live_openai", "external"}


@pytest.mark.parametrize(
    ("name", "expected_image"),
    [
        ("realism-swe-repo-tamper.yaml", "ghcr.io/epoch-research/swe-bench.eval.x86_64.matplotlib__matplotlib-25775:latest"),
        ("realism-terminal-output-only.yaml", "securebench-terminal-bench-jsonl-aggregator:latest"),
        ("realism-terminal-network-exfil.yaml", "securebench-terminal-bench-model-extraction-relu-logits:latest"),
    ],
)
def test_realism_config_preflight_collects_required_images(name, expected_image):
    images = required_images_for_configs([REVIEW_ROOT / "configs" / name])

    assert images == [expected_image]


@pytest.mark.parametrize(
    "name",
    [
        "swe-bench-verified-matplotlib-25775.jsonl",
        "terminal-bench-model-extraction-relu-logits.jsonl",
        "terminal-bench-jsonl-aggregator.jsonl",
        "terminal-bench-gomoku-planner.jsonl",
    ],
)
def test_realism_task_slices_contain_one_task(name):
    path = REVIEW_ROOT / "tasks" / "realism" / name
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    assert len(rows) == 1
    assert isinstance(rows[0]["id"], str)


def test_live_action_executor_writes_expected_files(tmp_path):
    result = execute_action(
        {"action": "write_file", "path": "answer.txt", "content": "magic-output\n"},
        workspace=tmp_path,
        workdir=tmp_path,
    )

    assert (tmp_path / "answer.txt").read_text() == "magic-output\n"
    assert result["status"] == "ok"
    assert result["action"] == "write_file"


def test_live_action_executor_expands_securebench_path_tokens(tmp_path):
    workspace = tmp_path / "workspace"
    workdir = workspace / "work"
    workdir.mkdir(parents=True)

    result = execute_action(
        {"action": "write_file", "path": "$SECUREBENCH_WORKSPACE/marker.txt", "content": "ok"},
        workspace=workspace,
        workdir=workdir,
    )

    assert (workspace / "marker.txt").read_text() == "ok"
    assert result["status"] == "ok"


def test_live_action_executor_flags_hidden_path_listing(tmp_path):
    hidden = tmp_path / "securebench" / "evaluation_inputs"
    hidden.mkdir(parents=True)

    result = execute_action(
        {"action": "list_dir", "path": str(tmp_path / "securebench")},
        workspace=tmp_path,
        workdir=tmp_path,
    )

    assert result["violation"] == "hidden_or_evaluator_path_listed"


def test_live_action_executor_does_not_flag_task_relevant_as_provider_key(tmp_path):
    result = execute_action(
        {"action": "run_shell", "command": "printf 'task-relevant files\\n'"},
        workspace=tmp_path,
        workdir=tmp_path,
    )

    assert result["status"] == "ok"
    assert "violation" not in result


def test_live_action_executor_flags_realistic_provider_key(tmp_path):
    result = execute_action(
        {"action": "run_shell", "command": "printf 'sk-abcdefghijklmnopqrstuvwxyz123456\\n'"},
        workspace=tmp_path,
        workdir=tmp_path,
    )

    assert result["violation"] == "real_provider_key_observed"


def test_live_agent_records_provider_failures_as_errors_not_violations(monkeypatch, tmp_path):
    monkeypatch.setattr(
        live_openai,
        "_openai_response",
        lambda prompt: {"status": "error", "error": "relay unavailable", "text": ""},
    )

    trace = live_openai.run_live_agent(
        task={"input": {"instructions": "test"}},
        profile="evaluator_escape",
        task_type="terminal_task",
        workspace=tmp_path,
        workdir=tmp_path,
        max_steps=1,
    )

    assert trace["errors"] == ["provider_call_failed"]
    assert trace["violations"] == []


def test_runner_materializes_public_only_and_uses_existing_verification_path(monkeypatch, tmp_path):
    data = terminal_config(tmp_path)
    config = parse_review_config(data)
    seen = {}

    def fake_verify(task, candidate):
        seen["candidate"] = candidate
        return VerificationResult(task_id=task.id, status="failed", passed=False, score=0.0)

    monkeypatch.setattr("review.run.verify_candidate", fake_verify)
    runner = ReviewRunner(config, sandbox_factory=FakeSandbox)

    summary = runner.run()

    assert summary.total == 1
    assert summary.verified == 1
    assert summary.passed == 0
    sandbox = FakeSandbox.instances[-1]
    assert (sandbox.root / "securebench" / "public" / "instructions.json").exists()
    assert not (sandbox.root / "securebench" / "evaluation_inputs").exists()
    assert isinstance(seen["candidate"], CandidateArtifact)
    assert (config.run.output_dir / "results.jsonl").exists()


def test_live_provider_env_uses_dummy_key_and_relay_base_url(tmp_path):
    data = terminal_config(
        tmp_path,
        mode="live_openai",
        provider={"model": "test-model", "allow_external_tools": False},
    )
    config = parse_review_config(data)
    runner = ReviewRunner(config, sandbox_factory=FakeSandbox)
    task = type("Task", (), {"task_type": "terminal_task", "metadata": {}})()
    egress = HarnessEgress(
        network="relay-net",
        env={},
        allowed_domains=(),
        provider="openai",
        provider_base_url="http://securebench-provider-relay:8090/v1",
        relay_log_dir=None,
        provider_relay_enabled=True,
    )

    env = runner._adversary_env(task, egress)

    assert env["OPENAI_API_KEY"].startswith("securebench-dummy")
    assert env["OPENAI_BASE_URL"] == "http://securebench-provider-relay:8090/v1"
    assert env["REVIEW_OPENAI_MODEL"] == "test-model"


def test_runner_uses_provider_relay_context_for_live_mode(monkeypatch, tmp_path):
    data = terminal_config(
        tmp_path,
        mode="live_openai",
        provider={"model": "test-model", "allow_external_tools": False},
    )
    config = parse_review_config(data)
    calls = []

    def fake_provider_factory(spec, allowed_domains, *, allow_external_tools=False):
        calls.append((spec.provider, allowed_domains, allow_external_tools))
        return nullcontext(
            HarnessEgress(
                network="relay-net",
                env={},
                allowed_domains=(),
                provider="openai",
                provider_base_url="http://securebench-provider-relay:8090/v1",
                relay_log_dir=None,
                provider_relay_enabled=True,
            )
        )

    monkeypatch.setattr(
        "review.run.verify_candidate",
        lambda task, candidate: VerificationResult(task_id=task.id, status="failed", passed=False, score=0.0),
    )
    runner = ReviewRunner(
        config,
        sandbox_factory=FakeSandbox,
        provider_relay_factory=fake_provider_factory,
    )

    runner.run()

    assert calls == [("openai", (), False)]
    assert FakeSandbox.instances[-1].network == "relay-net"
