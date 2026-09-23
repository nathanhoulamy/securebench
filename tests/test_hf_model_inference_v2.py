from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest

from securebench.execution_profiles import MAX_FILE_BUNDLE_BYTES, validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, ProtocolCheck
from securebench.tester_config import load_tester_config
from securebench.tester_run import candidate_byte_limit
from securebench.workspaces.cleanup import remove_untrusted_tree
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/hf-model-inference"
IMAGE = (
    "alexgshaw/hf-model-inference@"
    "sha256:f96dd7d3c85c7257b404fd63ba8d24ced2478cd90232c20e297c372f953fa607"
)
ADAPTER = PACK / "v2" / "evaluation_inputs" / "hf-model-inference" / "adapter"
HIDDEN = PACK / "v2" / "hidden" / "hf-model-inference"
ORACLE = HIDDEN / "oracle" / "oracle.py"
QUALIFICATION = HIDDEN / "qualification"
# This row's candidate bound exceeds the framework default (MAX_FILE_BUNDLE_BYTES),
# so, like tests/deepswe_qualification.py's PACK_MEMORY_LIMIT, preflight must be
# qualified under the same tester policy the pack actually runs with rather than
# the bare framework default.
PACK_MAX_CANDIDATE_BYTES = load_tester_config(PACK / "tester-linux.yaml").capture.max_candidate_bytes
# The restored public instruction just says "download the model and save it", so
# the reference/qualification Candidate is the plain upstream-default export: the
# default fast tokenizer, all six files. See
# docs/benchmark-conversions/TerminalBench/hf-model-inference.md, "Review correction".
MODEL_FILES = {
    "config.json",
    "model.safetensors",
    "tokenizer_config.json",
    "vocab.txt",
    "tokenizer.json",
    "special_tokens_map.json",
}


def compiled_task():
    return load_terminal_task(TASK_ID)


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _json_response(value: object) -> str:
    return _encoded(json.dumps(value, separators=(",", ":")).encode())


def _correct_observation(context: dict) -> dict:
    responses = []
    for expected in context["expectations"]:
        if expected["kind"] == "error":
            status = 400
            body = {"error": "Please provide a text string"}
        else:
            status = 200
            label = expected["label"]
            body = {
                "sentiment": label,
                "confidence": {
                    "positive": 0.9 if label == "positive" else 0.1,
                    "negative": 0.1 if label == "positive" else 0.9,
                },
            }
        responses.append(
            {
                "status": status,
                "body_base64": _json_response(body),
                "body_too_large": False,
                "error": "",
            }
        )
    return {
        "server_started": True,
        "process_running": True,
        "process_exit": -1,
        "listen_ipv4": ["0.0.0.0"],
        "output_too_large": False,
        "stdout_base64": "",
        "stderr_base64": "",
        "responses": responses,
    }


def _node(path: str, expected: dict) -> dict:
    return {
        "path": path,
        "kind": "regular_file",
        "mode": "100644",
        "size": expected["size"],
        "blob": f"sha256:{expected['sha256']}",
    }


def _correct_identity_nodes(oracle_module) -> list[dict]:
    return [
        _node("config.json", oracle_module.CONFIG_JSON),
        _node("model.safetensors", oracle_module.MODEL_SAFETENSORS),
        _node("vocab.txt", oracle_module.VOCAB_TXT),
        _node("tokenizer_config.json", oracle_module.TOKENIZER_CONFIG_JSON),
        _node("special_tokens_map.json", oracle_module.SPECIAL_TOKENS_MAP_JSON),
    ]


def _identity_evidence(nodes: list[dict]) -> dict:
    return {
        "check_id": "model_identity_artifact",
        "artifact_id": "model_files",
        "status": "observed",
        "parsed_value": {"nodes": nodes},
    }


def test_hf_model_row_is_bounded_split_and_executable():
    task = compiled_task()

    # This row's candidate bound exceeds the framework's plain default, so
    # preflight is qualified under the pack's actual tester policy, exactly as
    # a real run would apply benchmarks/terminal-bench/tester-*.yaml before
    # validating: see securebench/tester_run.py's candidate_byte_limit and
    # tests/deepswe_qualification.py's PACK_MEMORY_LIMIT for the same pattern.
    with candidate_byte_limit(PACK_MAX_CANDIDATE_BYTES):
        validate_executable_task(task)
    assert task.environment.image == IMAGE
    candidate = task.verification.candidate
    assert candidate.max_total_files == 81
    # Raised (as tester policy, not framework code) so the plain upstream-default
    # save_pretrained() export -- fast tokenizer, all six files, 268,777,554 bytes
    # -- fits with sensible headroom. This exceeds the framework's plain default
    # (MAX_FILE_BUNDLE_BYTES); the row now depends on the pack's tester policy
    # (capture.max_candidate_bytes) raising it, matching PACK_MAX_CANDIDATE_BYTES.
    assert candidate.max_total_bytes == 300_131_072
    assert candidate.max_total_bytes > MAX_FILE_BUNDLE_BYTES
    assert candidate.max_total_bytes <= PACK_MAX_CANDIDATE_BYTES
    entries = {entry.id: entry for entry in candidate.files}
    assert [(entry.id, entry.path) for entry in candidate.files] == [
        ("application", "/app/app.py"),
        ("model_cache", "/app/model_cache/sentiment_model"),
        ("dependencies", "/app/hf_service_dependencies"),
    ]
    assert entries["model_cache"].max_total_bytes == 300_000_000
    assert (
        entries["application"].max_bytes
        + entries["model_cache"].max_total_bytes
        + entries["dependencies"].max_total_bytes
        == candidate.max_total_bytes
    )
    # The full upstream six-file export (fast tokenizer, all optional files) is
    # 268,777,554 bytes and now fits comfortably, with ~31 MB (~11.6%) of
    # headroom -- see the dossier's "Review correction" section.
    assert entries["model_cache"].max_total_bytes - 268_777_554 == 31_222_446
    assert 268_777_554 < entries["model_cache"].max_total_bytes

    checks = task.verification.checks
    identity_check = checks[0]
    protocol = checks[1]
    assert isinstance(identity_check, ArtifactCheck)
    assert identity_check.id == "model_identity_artifact"
    assert [artifact.id for artifact in identity_check.artifacts] == ["model_files"]
    assert identity_check.artifacts[0].source.entry == "model_cache"
    assert identity_check.artifacts[0].parser == "securebench.tree-manifest/v1"
    assert identity_check.artifacts[0].limits.max_total_bytes == 300_000_000
    assert identity_check.artifacts[0].limits.max_files == 16
    assert isinstance(protocol, ProtocolCheck)
    assert protocol.protocol == "securebench.hf-sentiment-service/v1"
    assert protocol.challenge.max_cases == 3
    assert not protocol.trusted_helpers
    assert not protocol.output_artifacts

    instructions = task.input["instructions"]
    # The public prompt must match upstream exactly apart from the minimal
    # split-architecture addendum; the framework-limit workaround (a byte cap
    # and a specific-file-omission instruction) must not reappear here.
    assert instructions.startswith(
        "Set up a local service to run inference with a Hugging Face transformer model."
    )
    assert "268,200,000 bytes" not in instructions
    assert "tokenizer.json" not in instructions
    assert "special_tokens_map.json" not in instructions
    assert "omit optional" not in instructions
    assert (
        "For stopped replay, put the restartable Flask application in `/app/app.py`; "
        "it must run in the foreground when invoked with the system Python."
    ) in instructions
    assert "The model directory must load fully offline." in instructions
    assert instructions.endswith(
        "Do not rely on an already-running process or packages installed during "
        "the Agent session."
    )

    adapter_files = {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert adapter_files == {"adapter.py", "adapter.yaml"}


def test_public_adapter_contains_no_oracle_expectations():
    public_text = (ADAPTER / "adapter.py").read_text()

    assert "really enjoyed" not in public_text
    assert "expected" not in public_text
    assert "verdict" not in public_text
    assert "passed" not in public_text


def test_oracle_builds_source_hidden_and_error_cases():
    oracle_module = load_module(ORACLE, "hf_model_oracle_cases")
    first = oracle_module.build_cases("first-seed")
    hidden_cases = {
        json.dumps(oracle_module.build_cases(f"seed-{index}")[1], sort_keys=True)
        for index in range(8)
    }

    assert len(first) == 3
    assert len(first[0]["challenge"]["requests"]) == 6
    assert len(first[1]["challenge"]["requests"]) == 2
    assert len(first[2]["challenge"]["requests"]) == 1
    assert len(hidden_cases) > 1
    assert {item["label"] for item in first[1]["context"]["expectations"]} == {
        "positive",
        "negative",
    }


def test_oracle_accepts_independent_correct_evidence():
    oracle_module = load_module(ORACLE, "hf_model_oracle_pass")
    oracle = oracle_module.SentimentServiceOracle()
    oracle.initialize("qualification")
    oracle.evaluate_identity_artifact(
        _identity_evidence(_correct_identity_nodes(oracle_module))
    )

    index = 0
    while (case := oracle.next_case())["type"] == "case":
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": f"evaluation_{index}",
                "observation": _correct_observation(case["case_context"]),
            },
        )
        index += 1

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is True
    assert verdict["check_outcomes"] == {
        "sentiment_service_behavior": True,
        "model_identity_artifact": True,
    }


def test_oracle_accepts_fast_tokenizer_identity_evidence_too():
    """The identity check must not be stricter than a legitimate fast-tokenizer save."""
    oracle_module = load_module(ORACLE, "hf_model_oracle_fast_tokenizer")
    oracle = oracle_module.SentimentServiceOracle()
    nodes = [
        _node("config.json", oracle_module.CONFIG_JSON),
        _node("pytorch_model.bin", oracle_module.PYTORCH_MODEL_BIN),
        _node("tokenizer.json", oracle_module.TOKENIZER_JSON),
    ]
    oracle.evaluate_identity_artifact(_identity_evidence(nodes))

    assert oracle.identity_evaluated == 1
    assert oracle.identity_passed is True


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_weights_hash",
        "wrong_config_hash",
        "missing_weights",
        "missing_tokenizer",
        "wrong_special_tokens_hash",
        "empty_directory",
        "candidate_error",
        "wrong_artifact_id",
        "not_evaluated",
    ],
)
def test_oracle_rejects_model_identity_mutants(attack):
    oracle_module = load_module(ORACLE, f"hf_model_oracle_identity_{attack}")
    oracle = oracle_module.SentimentServiceOracle()
    oracle.initialize("mutant")

    if attack == "wrong_weights_hash":
        nodes = _correct_identity_nodes(oracle_module)
        nodes[1] = {**nodes[1], "blob": "sha256:" + "0" * 64}
        oracle.evaluate_identity_artifact(_identity_evidence(nodes))
    elif attack == "wrong_config_hash":
        nodes = _correct_identity_nodes(oracle_module)
        nodes[0] = {**nodes[0], "blob": "sha256:" + "2" * 64}
        oracle.evaluate_identity_artifact(_identity_evidence(nodes))
    elif attack == "missing_weights":
        nodes = [n for n in _correct_identity_nodes(oracle_module) if n["path"] != "model.safetensors"]
        oracle.evaluate_identity_artifact(_identity_evidence(nodes))
    elif attack == "missing_tokenizer":
        nodes = [
            n
            for n in _correct_identity_nodes(oracle_module)
            if n["path"] not in {"vocab.txt", "tokenizer_config.json"}
        ]
        oracle.evaluate_identity_artifact(_identity_evidence(nodes))
    elif attack == "wrong_special_tokens_hash":
        nodes = _correct_identity_nodes(oracle_module)
        nodes[4] = {**nodes[4], "blob": "sha256:" + "1" * 64}
        oracle.evaluate_identity_artifact(_identity_evidence(nodes))
    elif attack == "empty_directory":
        oracle.evaluate_identity_artifact(_identity_evidence([]))
    elif attack == "candidate_error":
        oracle.evaluate_identity_artifact(
            {
                "check_id": "model_identity_artifact",
                "artifact_id": "model_files",
                "status": "candidate_error",
                "error": {"code": "artifact_too_large", "message": "too large"},
            }
        )
    elif attack == "wrong_artifact_id":
        evidence = _identity_evidence(_correct_identity_nodes(oracle_module))
        evidence["artifact_id"] = "something_else"
        oracle.evaluate_identity_artifact(evidence)
    elif attack == "not_evaluated":
        pass

    # A fully correct protocol run still must not make the row pass.
    index = 0
    while (case := oracle.next_case())["type"] == "case":
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": f"evaluation_{index}",
                "observation": _correct_observation(case["case_context"]),
            },
        )
        index += 1

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is False
    assert verdict["check_outcomes"]["sentiment_service_behavior"] is True
    assert verdict["check_outcomes"]["model_identity_artifact"] is False


@pytest.mark.parametrize(
    "attack",
    [
        "server_stopped",
        "loopback_only",
        "wrong_count",
        "wrong_status",
        "wrong_label",
        "integer_confidence",
        "wrong_order",
        "out_of_range",
        "malformed_json",
        "duplicate_json",
        "wrong_error",
        "output_flood",
        "forged_claim",
        "reused_evaluation",
    ],
)
def test_oracle_rejects_semantic_mutants_and_claims(attack):
    oracle_module = load_module(ORACLE, f"hf_model_oracle_{attack}")
    oracle = oracle_module.SentimentServiceOracle()
    oracle.initialize("mutant")

    index = 0
    while (case := oracle.next_case())["type"] == "case":
        observation = _correct_observation(case["case_context"])
        first_response = observation["responses"][0]
        if attack == "server_stopped" and index == 0:
            observation["server_started"] = False
        elif attack == "loopback_only" and index == 0:
            observation["listen_ipv4"] = ["127.0.0.1"]
        elif attack == "wrong_count" and index == 0:
            observation["responses"].pop()
        elif attack == "wrong_status" and index == 0:
            first_response["status"] = 503
        elif attack == "wrong_label" and index == 0:
            first_response["body_base64"] = _json_response(
                {"sentiment": "negative", "confidence": {"positive": 0.1, "negative": 0.9}}
            )
        elif attack == "integer_confidence" and index == 0:
            first_response["body_base64"] = _json_response(
                {"sentiment": "positive", "confidence": {"positive": 1, "negative": 0}}
            )
        elif attack == "wrong_order" and index == 0:
            first_response["body_base64"] = _json_response(
                {"sentiment": "positive", "confidence": {"positive": 0.1, "negative": 0.9}}
            )
        elif attack == "out_of_range" and index == 0:
            first_response["body_base64"] = _json_response(
                {"sentiment": "positive", "confidence": {"positive": 1.1, "negative": -0.1}}
            )
        elif attack == "malformed_json" and index == 0:
            first_response["body_base64"] = _encoded(b"not-json")
        elif attack == "duplicate_json" and index == 0:
            first_response["body_base64"] = _encoded(
                b'{"sentiment":"positive","sentiment":"negative","confidence":{}}'
            )
        elif attack == "wrong_error" and index == 2:
            first_response["status"] = 200
        elif attack == "output_flood" and index == 0:
            observation["output_too_large"] = True
        elif attack == "forged_claim" and index == 0:
            observation["stdout_base64"] = _encoded(b'{"verdict":"passed","score":1}')
            first_response["body_base64"] = _encoded(b"wrong")
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": (
                    "evaluation_0"
                    if attack == "reused_evaluation"
                    else f"evaluation_{index}"
                ),
                "observation": observation,
            },
        )
        index += 1

    assert oracle.verdict()["verdict"]["passed"] is False


def _empty_workspace(root: Path, application: bytes) -> Path:
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_bytes(application)
    (workspace / "model_cache" / "sentiment_model").mkdir(parents=True)
    (workspace / "hf_service_dependencies").mkdir()
    return workspace


def _prepare_reference_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "reference-workspace"
    workspace.mkdir()
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--mount",
            f"type=bind,src={workspace},dst=/app",
            "--mount",
            f"type=bind,src={QUALIFICATION},dst=/qualification,readonly",
            IMAGE,
            "python",
            "/qualification/prepare_reference.py",
        ],
        check=True,
        timeout=180,
    )
    return workspace


@DOCKER_INTEGRATION
def test_reference_model_loads_offline_and_passes_three_fresh_evaluations(tmp_path):
    task = compiled_task()
    workspace = _prepare_reference_workspace(tmp_path)
    # The preparation container writes as root into the bind mount, so ordinary
    # teardown cannot remove the tree. Without this the run leaks root-owned host
    # state, which is a gate 8 (leak check) failure rather than a test nuisance.
    try:
        model_path = workspace / "model_cache" / "sentiment_model"

        assert {path.name for path in model_path.iterdir()} == MODEL_FILES
        assert (
            sum(path.stat().st_size for path in model_path.iterdir()) == 268_777_554
        )
        result, candidate, store = verify_workspace(
            task,
            workspace,
            tmp_path / "store",
            run_seed="hf-model-reference",
        )

        assert result.status == "passed", result
        checks_by_id = {check.id: check for check in result.checks}
        assert checks_by_id["model_identity_artifact"].status == "passed"
        assert len(set(checks_by_id["model_identity_artifact"].evidence_digests)) == 1
        assert checks_by_id["sentiment_service_behavior"].cases == 3
        assert len(set(checks_by_id["sentiment_service_behavior"].evidence_digests)) == 3
        total_bytes = store.load_candidate(candidate.digest).payload["total_bytes"]
        # The plain upstream-default six-file export exceeds the framework's
        # plain default (MAX_FILE_BUNDLE_BYTES) but fits inside the row's own
        # tester-policy-raised bound.
        assert total_bytes > MAX_FILE_BUNDLE_BYTES
        assert total_bytes < task.verification.candidate.max_total_bytes
    finally:
        remove_untrusted_tree(workspace, image=task.environment.image)

    assert not workspace.exists()


@DOCKER_INTEGRATION
def test_live_semantic_and_malicious_service_mutants_fail(tmp_path):
    constant = b'''from flask import Flask,jsonify,request\napp=Flask(__name__)\n@app.post("/sentiment")\ndef sentiment():\n d=request.get_json(silent=True)\n if not isinstance(d,dict) or "text" not in d:return jsonify({"error":"bad"}),400\n return jsonify({"sentiment":"positive","confidence":{"positive":0.9,"negative":0.1}})\napp.run(host="0.0.0.0",port=5000)\n'''
    loopback = b'''from flask import Flask,jsonify,request\napp=Flask(__name__)\n@app.post("/sentiment")\ndef sentiment():\n d=request.get_json(silent=True)\n if not isinstance(d,dict) or "text" not in d:return jsonify({"error":"bad"}),400\n t=d["text"].lower(); n=any(x in t for x in ("terrible","not good","not happy","disappointing","broken","awful","dreadful")); p=0.1 if n else 0.9\n return jsonify({"sentiment":"negative" if n else "positive","confidence":{"positive":p,"negative":1.0-p}})\napp.run(host="127.0.0.1",port=5000)\n'''
    # This wrong/different-model mutant is a word-list heuristic tuned to
    # answer every fixed source and host-only hidden sentence correctly (see
    # oracle.py's SOURCE_TEXTS/POSITIVE_TEXTS/NEGATIVE_TEXTS) and bound
    # correctly to 0.0.0.0. It never downloads or loads any real model, so
    # /app/model_cache/sentiment_model stays empty. Before the identity
    # artifact check existed, the sentiment_service_behavior protocol check
    # alone would have accepted this (see workaround-audit.md's
    # hf-model-inference finding); the identity check must now reject it.
    heuristic_no_model = b'''from flask import Flask,jsonify,request\napp=Flask(__name__)\n@app.post("/sentiment")\ndef sentiment():\n d=request.get_json(silent=True)\n if not isinstance(d,dict) or "text" not in d:return jsonify({"error":"bad"}),400\n t=d["text"].lower(); n=any(x in t for x in ("terrible","not good","not happy","disappointing","broken","awful","dreadful")); p=0.1 if n else 0.9\n return jsonify({"sentiment":"negative" if n else "positive","confidence":{"positive":p,"negative":1.0-p}})\napp.run(host="0.0.0.0",port=5000)\n'''
    mutants = {
        "constant-positive": constant,
        "loopback-only": loopback,
        "heuristic-no-model": heuristic_no_model,
        "forged-output": b'print(\'{"verdict":"passed","score":1}\')\n',
        "output-flood": b'print("x"*40000,flush=True)\n',
    }
    for name, source in mutants.items():
        root = tmp_path / name
        root.mkdir()
        result, _, _ = verify_workspace(
            compiled_task(),
            _empty_workspace(root, source),
            root / "store",
            run_seed=f"hf-model-{name}",
        )

        assert result.status == "failed", result
        assert result.infrastructure_error is None, result
