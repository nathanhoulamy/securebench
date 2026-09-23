"""Real captured-patch qualification; no candidate code executes on the host."""
from pathlib import Path
import json
import subprocess

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import CandidateStore, capture_git_patch_workspace
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.shared import materialize_image_workdir
from securebench.verification import VerificationEngine
from securebench.verification.oracle import OracleProcessSession
from tests.qualification_support import DOCKER_INTEGRATION, verify_command_candidate


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks/deep-swe"
HIDDEN = PACK / "v2/hidden/go-critic-doc-link-checker"


def task():
    pack = load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
    return next(t for t in compile_benchmark_pack(pack)
                if t.id == "deep-swe/go-critic-doc-link-checker")


def test_go_critic_conversion_preflight_and_visibility():
    row = task()
    validate_executable_task(row)
    assert row.input["base_commit"] == "9aea378c4dccd6f4394196ad8f0873b3e84678c8"
    assert row.environment.agent_network.mode == "none"
    # The reference patch is not declared as an Agent or Evaluation resource.
    for role in ("agent", "evaluation_runtime"):
        assert "reference.patch" not in str(row.view_for(role))


class RecordingOracle(OracleProcessSession):
    def __init__(self):
        super().__init__(HIDDEN / "oracle")
        self.evidence = []

    def evaluate_challenge(self, check_id, challenge_context, evidence):
        self.evidence.append(evidence)
        super().evaluate_challenge(check_id, challenge_context, evidence)


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("go-critic-baseline") / "app"
    materialize_image_workdir(task(), root)
    return root


def verify_patch(tmp_path, baseline, *, reference=False, mutate=None):
    row = task()
    workspace = tmp_path / "workspace"
    subprocess.run(["git", "clone", "--quiet", str(baseline), str(workspace)], check=True)
    if reference:
        subprocess.run(["git", "-C", str(workspace), "apply", "--whitespace=nowarn",
                        str(HIDDEN / "qualification/reference.patch")], check=True)
    if mutate is not None:
        mutate(workspace)
    store = CandidateStore(tmp_path / "store")
    candidate = capture_git_patch_workspace(
        workspace, baseline, row.verification.candidate, store,
        baseline_digest=row.baseline_digest, base_commit=row.input["base_commit"],
    )
    with RecordingOracle() as oracle:
        result = VerificationEngine().verify(
            row, candidate, store, run_seed="paper-go-critic-qualification", oracle=oracle,
        )
        evidence = oracle.evidence
    assert result.candidate_digest == candidate.digest
    assert store.reference(candidate.digest) == candidate
    (tmp_path / "qualification-summary.json").write_text(json.dumps({
        "status": result.status, "candidate_digest": candidate.digest,
        "row_digest": row.row_digest, "baseline_digest": row.baseline_digest,
        "verification_digest": row.verification_digest,
        "evaluations": [{"evaluation_id": e.evaluation_id, "challenge_id": e.challenge_id,
                         "evidence_digest": e.digest, "status": e.status} for e in evidence],
    }, indent=2) + "\n")
    return result, candidate, evidence


@DOCKER_INTEGRATION
def test_go_critic_base_fails_real_captured_patch(tmp_path, baseline):
    result, _, evidence = verify_patch(tmp_path, baseline)
    assert result.status == "failed", result
    assert evidence
    assert all(e.status != "infrastructure_error" for e in evidence)


@DOCKER_INTEGRATION
def test_go_critic_command_agent_smoke(tmp_path):
    result, candidate, store = verify_command_candidate(
        task(), tmp_path, command=("sh", "-c", "true"), run_seed="paper-go-critic-agent-smoke")
    assert result.status == "failed", result
    assert result.candidate_digest == candidate.digest
    assert store.reference(candidate.digest) == candidate


@DOCKER_INTEGRATION
def test_go_critic_reference_passes_fresh_evaluations(tmp_path, baseline):
    result, _, evidence = verify_patch(tmp_path, baseline, reference=True)
    assert result.status == "passed", (result, [e.observation for e in evidence
                                               if e.observation and e.observation.get("status") != "observed"])
    assert len(evidence) >= 2
    ids = [e.evaluation_id for e in evidence]
    assert len(ids) == len(set(ids))
    assert all(e.status == "observed" for e in evidence)


@DOCKER_INTEGRATION
def test_go_critic_dropped_diagnostics_mutant_fails(tmp_path, baseline):
    def mutate(workspace):
        path = workspace / "checkers/brokenDocLink_checker.go"
        text = path.read_text()
        # Preserve registration and compilation while dropping every diagnostic.
        old = 'c.ctx.Warn(node, "[%s]: "+format, allArgs...)'
        assert old in text
        path.write_text(text.replace(old, 'if len(allArgs) == 0 { ' + old + ' }', 1))
    result, _, evidence = verify_patch(tmp_path, baseline, reference=True, mutate=mutate)
    assert result.status == "failed", result
    assert all(e.status != "infrastructure_error" for e in evidence)


@DOCKER_INTEGRATION
@pytest.mark.parametrize("message_format", [
    "unknown symbol %q in current package", "type %q not found in current package",
    "%q is not a type", "package %q is not imported", "%q not found in package %q",
    "type %q not found in package %q", "type %q has no method or field %q",
], ids=["local", "local_type", "not_type", "alias", "imported_symbol", "imported_type", "member"])
def test_go_critic_semantic_mutants_fail(tmp_path, baseline, message_format):
    def mutate(workspace):
        path = workspace / "checkers/brokenDocLink_checker.go"
        original = path.read_text()
        # Omit one diagnostic category while retaining a registered, compiling checker.
        marker = 'func (c *brokenDocLinkChecker) emitDiagnostic(node ast.Node, link *comment.DocLink, format string, args ...interface{}) {'
        assert original.count(marker) == 1
        path.write_text(original.replace(marker, marker + '\nif format == ' + json.dumps(message_format) + ' { return }'))
    result, _, evidence = verify_patch(tmp_path, baseline, reference=True, mutate=mutate)
    assert result.status == "failed", result
    assert any(e.observation and e.observation.get("status") == "observed" for e in evidence)
    assert all(e.status != "infrastructure_error" for e in evidence)


@DOCKER_INTEGRATION
@pytest.mark.parametrize("attack", ["regression", "comment_location"])
def test_go_critic_regression_and_location_mutants_fail(tmp_path, baseline, attack):
    def mutate(workspace):
        if attack == "regression":
            path = workspace / "checkers/builtinShadow_checker.go"
            old = 'c.ctx.Warn(ident, "shadowing of predeclared identifier: %s", ident)'
            replacement = "return"
        else:
            path = workspace / "checkers/brokenDocLink_checker.go"
            old = 'c.ctx.Warn(node, "[%s]: "+format, allArgs...)'
            replacement = 'c.ctx.WarnWithPos(node.Pos()-2, "[%s]: "+format, allArgs...)'
        text = path.read_text()
        assert text.count(old) == 1
        path.write_text(text.replace(old, replacement))
    result, _, evidence = verify_patch(tmp_path, baseline, reference=True, mutate=mutate)
    assert result.status == "failed", result
    assert all(e.status != "infrastructure_error" for e in evidence)
    assert any(e.observation and e.observation.get("status") == "observed" for e in evidence)


@DOCKER_INTEGRATION
@pytest.mark.parametrize("attack", ["empty", "duplicate", "oversized"])
def test_go_critic_forged_success_fails(tmp_path, baseline, attack):
    def mutate(workspace):
        payload = '{"status":"observed","diagnostics":[],"error":""}'
        if attack == "duplicate":
            payload = '{"status":"candidate_error","status":"observed","diagnostics":[],"error":""}'
        elif attack == "oversized":
            payload = "x" * 65000
        (workspace / "checkers/zz_forged.go").write_text(
            'package checkers\nimport ("fmt"; "os")\n'
            'func init() { fmt.Println(' + json.dumps(payload) + '); os.Exit(0) }\n'
        )
    result, _, evidence = verify_patch(tmp_path, baseline, mutate=mutate)
    assert result.status == "failed", result
    assert all(e.status != "infrastructure_error" for e in evidence)
