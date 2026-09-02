from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ProtocolCheck
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
MODEL_FILES = {"config.json", "model.safetensors", "tokenizer_config.json", "vocab.txt"}


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


def test_hf_model_row_is_bounded_split_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    candidate = task.verification.candidate
    assert candidate.max_total_files == 81
    assert candidate.max_total_bytes == 268_331_072
    assert [(entry.id, entry.path) for entry in candidate.files] == [
        ("application", "/app/app.py"),
        ("model_cache", "/app/model_cache/sentiment_model"),
        ("dependencies", "/app/hf_service_dependencies"),
    ]
    protocol = task.verification.checks[0]
    assert isinstance(protocol, ProtocolCheck)
    assert protocol.protocol == "securebench.hf-sentiment-service/v1"
    assert protocol.challenge.max_cases == 3
    assert not protocol.trusted_helpers
    assert not protocol.output_artifacts
    assert "268,200,000 bytes" in task.input["instructions"]

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
    assert verdict["check_outcomes"] == {"sentiment_service_behavior": True}


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
    workspace = _prepare_reference_workspace(tmp_path)
    model_path = workspace / "model_cache" / "sentiment_model"

    assert {path.name for path in model_path.iterdir()} == MODEL_FILES
    assert sum(path.stat().st_size for path in model_path.iterdir()) == 268_066_033
    result, candidate, store = verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="hf-model-reference",
    )

    assert result.status == "passed", result
    assert result.checks[0].cases == 3
    assert len(set(result.checks[0].evidence_digests)) == 3
    assert store.load_candidate(candidate.digest).payload["total_bytes"] < 268_331_072


@DOCKER_INTEGRATION
def test_live_semantic_and_malicious_service_mutants_fail(tmp_path):
    constant = b'''from flask import Flask,jsonify,request\napp=Flask(__name__)\n@app.post("/sentiment")\ndef sentiment():\n d=request.get_json(silent=True)\n if not isinstance(d,dict) or "text" not in d:return jsonify({"error":"bad"}),400\n return jsonify({"sentiment":"positive","confidence":{"positive":0.9,"negative":0.1}})\napp.run(host="0.0.0.0",port=5000)\n'''
    loopback = b'''from flask import Flask,jsonify,request\napp=Flask(__name__)\n@app.post("/sentiment")\ndef sentiment():\n d=request.get_json(silent=True)\n if not isinstance(d,dict) or "text" not in d:return jsonify({"error":"bad"}),400\n t=d["text"].lower(); n=any(x in t for x in ("terrible","not good","not happy","disappointing","broken","awful","dreadful")); p=0.1 if n else 0.9\n return jsonify({"sentiment":"negative" if n else "positive","confidence":{"positive":p,"negative":1.0-p}})\napp.run(host="127.0.0.1",port=5000)\n'''
    mutants = {
        "constant-positive": constant,
        "loopback-only": loopback,
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
