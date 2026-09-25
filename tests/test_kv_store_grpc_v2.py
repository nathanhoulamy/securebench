from __future__ import annotations

import base64
import os
import shutil
from pathlib import Path
import subprocess

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, ProtocolCheck
from securebench.verification.json_data import json_digest
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/kv-store-grpc"
IMAGE = (
    "alexgshaw/kv-store-grpc@"
    "sha256:3399400800dcb207634daa42bc1b052e831e285cc9d221eea66c47bc0fc79791"
)
ADAPTER = PACK / "v2" / "evaluation_inputs" / "kv-store-grpc" / "adapter"
ADAPTER_PY = ADAPTER / "adapter.py"
HIDDEN = PACK / "v2" / "hidden" / "kv-store-grpc"
ORACLE = HIDDEN / "oracle" / "oracle.py"
QUALIFICATION = HIDDEN / "qualification"


def compiled_task():
    return load_terminal_task(TASK_ID)


def _artifact(artifact_id: str, value: str) -> dict:
    return {
        "check_id": "kv_store_artifacts",
        "artifact_id": artifact_id,
        "status": "observed",
        "parsed_value": value,
    }


def _correct_observation(context: dict) -> dict:
    return {
        "server_started": True,
        "process_running": True,
        "process_exit": -1,
        "output_too_large": False,
        "stdout_base64": base64.b64encode(b"").decode(),
        "stderr_base64": base64.b64encode(b"").decode(),
        "responses": [
            {"status": "returned", "val": value, "error": ""}
            for value in context["expected"]
        ],
    }


def _case_evidence(context: dict, observation: dict, evaluation_id: str) -> dict:
    return {
        "check_id": "kv_store_behavior",
        "status": "observed",
        "evaluation_id": evaluation_id,
        "challenge": {
            "index": context["case_index"],
            "digest": context["challenge_digest"],
        },
        "observation": observation,
    }


def _passing_oracle(name: str):
    module = load_module(ORACLE, name)
    oracle = module.KvStoreOracle()
    oracle.initialize("qualification")
    proto = (QUALIFICATION / "reference.proto").read_text()
    oracle.evaluate_artifact(_artifact("proto", proto))
    oracle.evaluate_artifact(_artifact("python_bindings", "generated binding"))
    oracle.evaluate_artifact(_artifact("grpc_bindings", "generated grpc binding"))
    oracle.evaluate_artifact(_artifact("server", "class Server: pass"))
    return module, oracle


def test_kv_store_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    candidate = task.verification.candidate
    assert candidate.max_total_files == 1_028
    assert candidate.max_total_bytes == 40_458_752
    assert [(entry.id, entry.path) for entry in candidate.files] == [
        ("proto", "/app/kv-store.proto"),
        ("python_bindings", "/app/kv_store_pb2.py"),
        ("grpc_bindings", "/app/kv_store_pb2_grpc.py"),
        ("server", "/app/server.py"),
        ("dependencies", "/app/kv_store_dependencies"),
    ]
    assert [type(check) for check in task.verification.checks] == [
        ArtifactCheck,
        ProtocolCheck,
    ]
    artifact, protocol = task.verification.checks
    assert [item.id for item in artifact.artifacts] == [
        "proto",
        "python_bindings",
        "grpc_bindings",
        "server",
    ]
    assert protocol.protocol == "securebench.kv-store-grpc/v1"
    assert protocol.challenge.max_cases == 3
    assert not protocol.trusted_helpers
    assert not protocol.output_artifacts
    assert "stopped replay" in task.input["instructions"]
    assert {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } == {"adapter.py", "adapter.yaml"}


def test_public_adapter_contains_no_host_expectations_or_candidate_imports():
    public_text = ADAPTER_PY.read_text()

    assert "expected" not in public_text
    assert "verdict" not in public_text
    assert "passed" not in public_text
    assert "import grpc" not in public_text
    assert "kv_store_pb2" not in public_text


def test_public_client_parses_success_status_and_rejects_huffman_ambiguity():
    module = load_module(ADAPTER_PY, "kv_adapter_hpack")
    trailer = bytes.fromhex(
        "400b677270632d7374617475730130000c677270632d6d65737361676500"
    )

    assert module._hpack_headers(trailer) == [
        ("grpc-status", "0"),
        ("grpc-message", ""),
    ]
    with pytest.raises(ValueError, match="Huffman"):
        module._hpack_headers(b"\x40\x81\x00")


@pytest.mark.parametrize(
    ("mutation", "accepted"),
    [
        ("", True),
        ("service KVStore", False),
        ("rpc GetVal", False),
        ("int32 value = 2", False),
        ("int32 val = 1", False),
    ],
)
def test_proto_contract_is_passive_and_rejects_semantic_mutants(mutation, accepted):
    module = load_module(ORACLE, f"kv_proto_{mutation or 'reference'}")
    text = (QUALIFICATION / "reference.proto").read_text()
    if mutation:
        text = text.replace(mutation, mutation.replace("32", "64") + "_wrong", 1)

    assert module.proto_matches_contract(text) is accepted


def test_proto_contract_accepts_int64_values_like_upstream():
    # The public prompt says "int"; upstream never inspects the scalar type, and
    # int32 and int64 share one varint wire encoding for every challenged value.
    module = load_module(ORACLE, "kv_proto_int64")
    text = (QUALIFICATION / "reference.proto").read_text().replace("int32 ", "int64 ")

    assert "int32" not in text
    assert module.proto_matches_contract(text) is True


_ALTERNATE_PROTO = """syntax = "proto3";

package kvstore.alt.v2;

service KVStore {
    rpc GetVal (GetValRequest) returns (GetValResponse) {}
    rpc SetVal (SetValRequest) returns (SetValResponse) {}
}

message GetValRequest {
    string key = 7;
}

message GetValResponse {
    int32 val = 3;
}

message SetValRequest {
    string key = 5;
    int32 value = 9;
}

message SetValResponse {
    int32 val = 4;
}
"""


def test_proto_contract_accepts_alternate_field_numbers_and_package():
    """Upstream builds its gRPC client from the candidate's own generated
    bindings and never asserts a field number or a package's absence, so a
    correct proto that chooses different numbers and declares a package
    must be accepted exactly like the gold numbering (review correction:
    see the kv-store-grpc dossier)."""
    module = load_module(ORACLE, "kv_proto_alternate_numbers")

    assert module.proto_matches_contract(_ALTERNATE_PROTO) is True
    assert module.parse_proto_contract(_ALTERNATE_PROTO) == {
        "path_prefix": "kvstore.alt.v2.KVStore",
        "get_request_key_field": 7,
        "get_response_val_field": 3,
        "set_request_key_field": 5,
        "set_request_value_field": 9,
        "set_response_val_field": 4,
    }


def test_proto_contract_derives_default_wire_shape_for_the_gold_numbering():
    module = load_module(ORACLE, "kv_proto_gold_numbers")
    text = (QUALIFICATION / "reference.proto").read_text()

    assert module.parse_proto_contract(text) == module._DEFAULT_WIRE


@pytest.mark.parametrize(
    "mutation",
    [
        # Reused field number within one message: not legal protobuf.
        lambda text: text.replace(
            "string key = 1;\n    int32 value = 2;",
            "string key = 1;\n    int32 value = 1;",
        ),
        # Field number inside protobuf's reserved implementation range.
        lambda text: text.replace(
            "string key = 1;\n    int32 value = 2;",
            "string key = 19000;\n    int32 value = 2;",
        ),
        # Field number above the protobuf field-number ceiling.
        lambda text: text.replace("int32 val = 1;\n}", "int32 val = 536870912;\n}", 1),
        # Non-positive field number.
        lambda text: text.replace("string key = 1;\n}", "string key = 0;\n}", 1),
    ],
)
def test_proto_contract_rejects_illegal_field_numbers(mutation):
    module = load_module(ORACLE, "kv_proto_illegal_numbers")
    text = (QUALIFICATION / "reference.proto").read_text()
    mutated = mutation(text)

    assert mutated != text
    assert module.proto_matches_contract(mutated) is False


def test_oracle_cases_are_seeded_correlated_and_cover_state_semantics():
    module = load_module(ORACLE, "kv_cases")
    first = module.build_cases("first-seed")
    second = module.build_cases("second-seed")

    assert len(first) == 3
    assert first != second
    assert [case["id"] for case in first] == [
        "set_get_update",
        "independent_keys",
        "utf8_key_and_negative_value",
    ]
    assert all(
        case["context"]["challenge_digest"] == json_digest(case["challenge"])
        for case in first
    )
    assert any(
        operation.get("value", 0) < 0
        for case in first
        for operation in case["challenge"]["operations"]
    )


def test_oracle_accepts_independent_correct_evidence():
    _, oracle = _passing_oracle("kv_oracle_pass")
    index = 0
    while (case := oracle.next_case())["type"] == "case":
        context = case["case_context"]
        oracle.evaluate_case(
            context,
            _case_evidence(
                context,
                _correct_observation(context),
                f"evaluation_{index}",
            ),
        )
        index += 1

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is True
    assert verdict["check_outcomes"] == {
        "kv_store_artifacts": True,
        "kv_store_behavior": True,
    }


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_value",
        "rpc_error",
        "wrong_count",
        "server_stopped",
        "output_flood",
        "forged_claim",
        "reused_evaluation",
        "challenge_digest",
    ],
)
def test_oracle_rejects_semantic_mutants_and_claims(attack):
    _, oracle = _passing_oracle(f"kv_oracle_{attack}")
    index = 0
    while (case := oracle.next_case())["type"] == "case":
        context = case["case_context"]
        observation = _correct_observation(context)
        evidence = _case_evidence(
            context,
            observation,
            "evaluation_reused" if attack == "reused_evaluation" else f"evaluation_{index}",
        )
        if attack == "wrong_value" and index == 0:
            observation["responses"][0]["val"] += 1
        elif attack == "rpc_error" and index == 0:
            observation["responses"][0] = {
                "status": "error",
                "val": 0,
                "error": "forged",
            }
        elif attack == "wrong_count" and index == 0:
            observation["responses"].pop()
        elif attack == "server_stopped" and index == 0:
            observation["process_running"] = False
        elif attack == "output_flood" and index == 0:
            observation["output_too_large"] = True
        elif attack == "forged_claim" and index == 0:
            observation["stdout_base64"] = base64.b64encode(
                b'{"verdict":"passed","score":1}'
            ).decode()
            observation["responses"][0]["val"] += 1
        elif attack == "challenge_digest" and index == 0:
            evidence["challenge"]["digest"] = "sha256:" + "0" * 64
        oracle.evaluate_case(context, evidence)
        index += 1

    assert oracle.verdict()["verdict"]["passed"] is False


def test_oracle_rejects_missing_or_malformed_artifacts():
    module, oracle = _passing_oracle("kv_bad_artifacts")
    oracle.artifact_outcomes.clear()
    oracle.evaluate_artifact(_artifact("proto", "service KVStore {}"))
    oracle.evaluate_artifact(_artifact("python_bindings", ""))
    oracle.evaluate_artifact(_artifact("grpc_bindings", "generated"))
    oracle.evaluate_artifact(_artifact("server", "class NotServer: pass"))
    assert module.ARTIFACT_IDS == set(oracle.artifact_outcomes)
    assert oracle.verdict()["verdict"]["passed"] is False


def _prepare_reference_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "reference-workspace"
    workspace.mkdir()
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            f"type=bind,src={workspace},dst=/app",
            "--mount",
            f"type=bind,src={QUALIFICATION},dst=/qualification,readonly",
            IMAGE,
            "sh",
            "/qualification/prepare-reference.sh",
        ],
        check=True,
        timeout=180,
    )
    return workspace


def _prepare_alternate_workspace(tmp_path: Path) -> Path:
    """Build a Candidate workspace from a proto that is correct by the
    public prompt but uses different field numbers and declares a package,
    reusing the unmodified reference server (it addresses fields by name,
    never by number, exactly like upstream's own generated client)."""
    workspace = tmp_path / "alternate-workspace"
    workspace.mkdir()
    qualification = tmp_path / "alternate-qualification"
    qualification.mkdir()
    (qualification / "reference.proto").write_text(_ALTERNATE_PROTO)
    (qualification / "reference-server.py").write_text(
        (QUALIFICATION / "reference-server.py").read_text()
    )
    shutil.copy(
        QUALIFICATION / "prepare-reference.sh", qualification / "prepare-reference.sh"
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            f"type=bind,src={workspace},dst=/app",
            "--mount",
            f"type=bind,src={qualification},dst=/qualification,readonly",
            IMAGE,
            "sh",
            "/qualification/prepare-reference.sh",
        ],
        check=True,
        timeout=180,
    )
    return workspace


@DOCKER_INTEGRATION
def test_alternate_field_numbers_and_package_proto_passes(tmp_path):
    """Review correction: upstream's own verifier builds its gRPC client
    from the candidate's generated bindings, so it never pins field numbers
    or forbids a package. A correct proto that picks different numbers and
    declares a package must pass exactly like the gold numbering."""
    workspace = _prepare_alternate_workspace(tmp_path)

    assert (workspace / "kv-store.proto").read_text() == _ALTERNATE_PROTO
    result, _, _ = verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "alternate-store",
        run_seed="kv-store-alternate-wire",
    )

    assert result.status == "passed", result


@DOCKER_INTEGRATION
def test_proto_claiming_different_field_numbers_than_its_own_bindings_fails(tmp_path):
    """Malicious-candidate case for the new wire-derivation mechanism: a
    proto that claims different field numbers than the bindings actually
    compiled from it (e.g. hand-edited after ``protoc`` ran) must fail. The
    Adapter talks the numbers the proto text declares; a server built from
    different numbers cannot decode them, so the values it returns are
    wrong."""
    workspace = _prepare_reference_workspace(tmp_path)
    (workspace / "kv-store.proto").write_text(_ALTERNATE_PROTO)

    result, _, _ = verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "mismatched-store",
        run_seed="kv-store-mismatched-wire",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result


@DOCKER_INTEGRATION
def test_reference_passes_three_fresh_networkless_evaluations(tmp_path):
    workspace = _prepare_reference_workspace(tmp_path)
    dependencies = workspace / "kv_store_dependencies"
    dependency_files = [path for path in dependencies.rglob("*") if path.is_file()]
    dependency_bytes = sum(path.stat().st_size for path in dependency_files)

    assert len(dependency_files) <= 1_024
    assert dependency_bytes < 40_000_000
    result, candidate, store = verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="kv-store-reference",
    )

    assert result.status == "passed", result
    assert result.checks[1].cases == 3
    assert len(set(result.checks[1].evidence_digests)) == 3
    assert store.load_candidate(candidate.digest).payload["total_bytes"] < 40_458_752


@DOCKER_INTEGRATION
def test_live_state_and_protocol_mutants_fail(tmp_path):
    reference = _prepare_reference_workspace(tmp_path)
    source = (reference / "server.py").read_text()
    mutants = {
        "does-not-store": source.replace(
            "self.kv_dict[request.key] = request.value",
            "pass",
        ),
        "ignores-keys": source.replace(
            "self.kv_dict.get(request.key, 0)",
            'self.kv_dict.get("fixed", 0)',
        ).replace(
            "self.kv_dict[request.key] = request.value",
            'self.kv_dict["fixed"] = request.value',
        ),
        "not-grpc": '''import socket\nclass Server: pass\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(("0.0.0.0",5328));s.listen()\nwhile True:\n c,_=s.accept();c.sendall(b"not grpc");c.close()\n''',
        "error-trailer": source.replace(
            "def SetVal(self, request, unused_context)",
            "def SetVal(self, request, context)",
        ).replace(
            "self.kv_dict[request.key] = request.value",
            "context.set_code(grpc.StatusCode.INVALID_ARGUMENT)\n"
            "        self.kv_dict[request.key] = request.value",
        ),
    }
    for name, mutant in mutants.items():
        assert mutant != source
        workspace = tmp_path / name
        shutil.copytree(reference, workspace)
        (workspace / "server.py").write_text(mutant)
        result, _, _ = verify_workspace(
            compiled_task(),
            workspace,
            tmp_path / f"{name}-store",
            run_seed=f"kv-store-{name}",
        )

        assert result.status == "failed", result
        assert result.infrastructure_error is None, result
        if name == "error-trailer":
            assert result.public_diagnostics["failure_categories"] == [
                "incorrect_rpc_response"
            ]
