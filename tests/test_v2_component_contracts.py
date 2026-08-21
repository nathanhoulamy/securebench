from __future__ import annotations

import pytest

from securebench.schemas.benchmark import ProtocolCheck, TrustedHelperSpec
from securebench.verification.component_contracts import (
    AdapterManifestV2,
    JsonValueSchema,
    TrustedHelperCatalog,
    TrustedHelperContract,
    parse_adapter_response_v2,
    validate_json_value,
)
from securebench.verification.models import (
    ChallengeEvidence,
    OutputArtifactEvidence,
    TrustedHelperEvidence,
    VerificationInfrastructureError,
)
from securebench.verification.protocol import (
    LoadedAdapter,
    require_supported_protocol_features,
)


def object_schema(properties, *, required=()):
    return JsonValueSchema.model_validate(
        {
            "type": "object",
            "properties": properties,
            "required": required,
            "max_fields": max(1, len(properties)),
        }
    )


def protocol_check(**updates):
    value = {
        "id": "behavior",
        "type": "protocol",
        "adapter": "runtime.adapter",
        "protocol": "securebench.example/v1",
        "challenge": {
            "source": "host.challenges",
            "max_cases": 4,
            "max_case_bytes": 1024,
        },
        "limits": {
            "seconds_per_case": 2,
            "observation_bytes_per_case": 1024,
        },
    }
    value.update(updates)
    return ProtocolCheck.model_validate(value)


def adapter_contract(**updates):
    value = {
        "format": "securebench.adapter/v2",
        "protocol": "securebench.example/v1",
        "command": ["python3", "./adapter.py"],
        "challenge_schema": {"type": "object"},
        "observation_schema": {"type": "object"},
        "evaluation_participants": [
            {"name": "candidate", "type": "candidate", "instances": 1}
        ],
        "maximums": {
            "seconds_per_challenge": 2,
            "challenge_bytes": 1024,
            "observation_bytes": 1024,
        },
    }
    value.update(updates)
    contract = AdapterManifestV2.model_validate(value, strict=False)
    return LoadedAdapter(command=contract.command, contract=contract)


def test_closed_value_schema_rejects_wrong_types_and_unknown_fields():
    schema = object_schema(
        {
            "value": {"type": "integer"},
            "label": {"type": "string", "max_utf8_bytes": 8},
        },
        required=("value",),
    )

    validate_json_value(schema, {"value": 3, "label": "ok"})
    with pytest.raises(ValueError, match="unknown fields"):
        validate_json_value(schema, {"value": 3, "unexpected": True})
    with pytest.raises(ValueError, match="must be an integer"):
        validate_json_value(schema, {"value": True})
    with pytest.raises(ValueError, match="too large"):
        validate_json_value(schema, {"value": 3, "label": "too-large"})


def test_adapter_v2_response_distinguishes_observation_from_candidate_failure():
    observed = parse_adapter_response_v2(
        {
            "format": "securebench.adapter-response/v2",
            "status": "observed",
            "observation": {"answer": 4},
        }
    )
    rejected = parse_adapter_response_v2(
        {
            "format": "securebench.adapter-response/v2",
            "status": "candidate_error",
            "failure": {"code": "candidate_timeout", "message": "Candidate timed out"},
        }
    )

    assert observed.observation == {"answer": 4}
    assert rejected.failure_code == "candidate_timeout"
    with pytest.raises(ValueError, match="invalid shape"):
        parse_adapter_response_v2(
            {
                "format": "securebench.adapter-response/v2",
                "status": "observed",
                "observation": {},
                "passed": True,
            }
        )


def test_trusted_helper_catalog_enforces_contract_and_reduced_limits():
    contract = TrustedHelperContract.model_validate(
        {
            "format": "securebench.trusted-helper-contract/v1",
            "type": "securebench.http-request-recorder/v1",
            "capabilities": ["record_requests"],
            "helper_access": "http",
            "settings_schema": {
                "type": "object",
                "properties": {"path": {"type": "string", "max_utf8_bytes": 128}},
                "required": ["path"],
                "max_fields": 1,
            },
            "limits_schema": {
                "type": "object",
                "properties": {
                    "max_requests": {"type": "integer"},
                    "max_body_bytes": {"type": "integer"},
                },
                "required": ["max_requests", "max_body_bytes"],
                "max_fields": 2,
            },
            "maximum_limits": {"max_requests": 128, "max_body_bytes": 65536},
            "evidence_schema": {
                "type": "object",
                "properties": {"requests": {"type": "array", "items": {"type": "object"}, "max_items": 128}},
                "required": ["requests"],
                "max_fields": 1,
            },
            "reset": "fresh_per_evaluation",
            "credentials": "fresh_per_evaluation",
        },
        strict=False,
    )
    catalog = TrustedHelperCatalog((contract,))
    accepted = TrustedHelperSpec.model_validate(
        {
            "name": "request_recorder",
            "type": contract.type,
            "limits": {"max_requests": 10, "max_body_bytes": 4096},
        }
    )
    catalog.validate_declaration(accepted)
    catalog.validate_settings(contract, {"path": "/callback"})
    catalog.validate_evidence(contract, {"requests": []})
    with pytest.raises(VerificationInfrastructureError) as invalid_evidence:
        catalog.validate_evidence(contract, {"forged": []})
    assert invalid_evidence.value.code == "trusted_helper_evidence_invalid"

    excessive = accepted.model_copy(
        update={"limits": {"max_requests": 129, "max_body_bytes": 4096}}
    )
    with pytest.raises(VerificationInfrastructureError) as error:
        catalog.validate_declaration(excessive)
    assert error.value.code == "trusted_helper_limits_exceeded"
    assert error.value.source == "trusted_helper"

    non_positive = accepted.model_copy(
        update={"limits": {"max_requests": 0, "max_body_bytes": 4096}}
    )
    with pytest.raises(VerificationInfrastructureError) as error:
        catalog.validate_declaration(non_positive)
    assert error.value.code == "trusted_helper_limits_exceeded"


def test_adapter_contract_maximums_can_only_be_reduced_by_a_protocol_check():
    manifest = adapter_contract(
        maximums={
            "seconds_per_challenge": 1,
            "challenge_bytes": 1024,
            "observation_bytes": 1024,
        }
    )

    with pytest.raises(VerificationInfrastructureError) as error:
        require_supported_protocol_features(protocol_check(), manifest)

    assert error.value.code == "adapter_maximum_exceeded"


def test_preflight_matches_trusted_helpers_by_clear_name_and_registered_type():
    manifest = adapter_contract(
        uses_trusted_helpers=[
            {
                "name": "request_recorder",
                "type": "securebench.http-request-recorder/v1",
            }
        ]
    )
    mismatched = protocol_check(
        trusted_helpers=[
            {
                "name": "different_name",
                "type": "securebench.http-request-recorder/v1",
                "limits": {},
            }
        ]
    )

    with pytest.raises(VerificationInfrastructureError) as mismatch:
        require_supported_protocol_features(mismatched, manifest)
    assert mismatch.value.code == "trusted_helper_contract_mismatch"

    matching = protocol_check(
        trusted_helpers=[
            {
                "name": "request_recorder",
                "type": "securebench.http-request-recorder/v1",
                "limits": {},
            }
        ]
    )
    with pytest.raises(VerificationInfrastructureError) as unavailable:
        require_supported_protocol_features(matching, manifest)
    assert unavailable.value.code == "trusted_helper_unavailable"
    assert unavailable.value.source == "trusted_helper"


def test_preflight_rejects_output_artifact_limits_above_adapter_maximums():
    manifest = adapter_contract(
        output_artifacts=[
            {
                "name": "generated_result",
                "path": "results/result.json",
                "kind": "regular_file",
                "maximum_limits": {"max_bytes": 1024},
            }
        ]
    )
    check = protocol_check(
        output_artifacts=[
            {
                "name": "generated_result",
                "parser": "securebench.strict-json/v1",
                "limits": {"max_bytes": 2048},
            }
        ]
    )

    with pytest.raises(VerificationInfrastructureError) as error:
        require_supported_protocol_features(check, manifest)

    assert error.value.code == "output_artifact_maximum_exceeded"


def test_preflight_accepts_declared_bounded_output_artifact():
    manifest = adapter_contract(
        output_artifacts=[
            {
                "name": "generated_result",
                "path": "results/result.json",
                "kind": "regular_file",
                "maximum_limits": {"max_bytes": 2048},
            }
        ]
    )
    check = protocol_check(
        output_artifacts=[
            {
                "name": "generated_result",
                "parser": "securebench.strict-json/v1",
                "limits": {"max_bytes": 1024},
            }
        ]
    )

    require_supported_protocol_features(check, manifest)


def test_preflight_rejects_output_artifact_kind_reserved_path_and_backend_bound():
    mismatched = adapter_contract(
        output_artifacts=[
            {
                "name": "generated_result",
                "path": "results",
                "kind": "directory_tree",
                "maximum_limits": {"max_files": 4, "max_total_bytes": 2048},
            }
        ]
    )
    regular_check = protocol_check(
        output_artifacts=[
            {
                "name": "generated_result",
                "parser": "securebench.strict-json/v1",
                "limits": {"max_bytes": 1024},
            }
        ]
    )
    with pytest.raises(VerificationInfrastructureError) as kind_error:
        require_supported_protocol_features(regular_check, mismatched)
    assert kind_error.value.code == "output_artifact_kind_mismatch"

    reserved = adapter_contract(
        output_artifacts=[
            {
                "name": "generated_result",
                "path": "securebench/evaluation_inputs/private.json",
                "kind": "regular_file",
                "maximum_limits": {"max_bytes": 2048},
            }
        ]
    )
    with pytest.raises(VerificationInfrastructureError) as path_error:
        require_supported_protocol_features(regular_check, reserved)
    assert path_error.value.code == "output_artifact_path_reserved"

    excessive = 16 * 1024 * 1024 + 1
    excessive_manifest = adapter_contract(
        output_artifacts=[
            {
                "name": "generated_result",
                "path": "result.bin",
                "kind": "regular_file",
                "maximum_limits": {"max_bytes": excessive},
            }
        ]
    )
    excessive_check = protocol_check(
        output_artifacts=[
            {
                "name": "generated_result",
                "parser": "securebench.utf8-text/v1",
                "limits": {"max_bytes": excessive},
            }
        ]
    )
    with pytest.raises(VerificationInfrastructureError) as bound_error:
        require_supported_protocol_features(excessive_check, excessive_manifest)
    assert bound_error.value.code == "output_artifact_bound_unsupported"


def test_challenge_evidence_requires_host_identities_and_explicit_failure_source():
    observed = ChallengeEvidence(
        check_id="behavior",
        challenge_id="challenge-1",
        evaluation_id="evaluation-1",
        challenge_index=0,
        challenge_digest="sha256:" + "a" * 64,
        status="observed",
        observation={"answer": 4},
    )
    assert observed.internal_record()["challenge"]["id"] == "challenge-1"
    assert observed.internal_record()["evaluation_id"] == "evaluation-1"
    assert observed.internal_record()["format"] == "securebench.challenge-evidence/v1"

    with pytest.raises(ValueError, match="candidate failure source"):
        ChallengeEvidence(
            check_id="behavior",
            challenge_id="challenge-1",
            evaluation_id="evaluation-1",
            challenge_index=0,
            challenge_digest="sha256:" + "a" * 64,
            status="candidate_error",
            failure_source="adapter",
            failure_code="adapter_failed",
            failure_message="Adapter failed",
        )

    infrastructure = ChallengeEvidence(
        check_id="behavior",
        challenge_id="challenge-1",
        evaluation_id="evaluation-1",
        challenge_index=0,
        challenge_digest="sha256:" + "a" * 64,
        status="infrastructure_error",
        failure_source="trusted_helper",
        failure_code="helper_failed",
        failure_message="Trusted Helper failed",
    )
    assert infrastructure.internal_record()["failure"]["source"] == "trusted_helper"


def test_challenge_evidence_rejects_mis_correlated_trusted_helper_evidence():
    wrong_evaluation = TrustedHelperEvidence(
        name="request_recorder",
        type="securebench.http-request-recorder/v1",
        challenge_id="challenge-1",
        evaluation_id="evaluation-other",
        value={"requests": []},
    )

    with pytest.raises(ValueError, match="another Evaluation"):
        ChallengeEvidence(
            check_id="behavior",
            challenge_id="challenge-1",
            evaluation_id="evaluation-1",
            challenge_index=0,
            challenge_digest="sha256:" + "a" * 64,
            status="observed",
            observation={"answer": 4},
            trusted_helper_evidence=(wrong_evaluation,),
        )

    wrong_artifact = OutputArtifactEvidence(
        name="generated_result",
        challenge_id="challenge-other",
        evaluation_id="evaluation-1",
        status="observed",
        digest="sha256:" + "b" * 64,
        size=2,
        parser="securebench.strict-json/v1",
        parsed_value={},
    )
    with pytest.raises(ValueError, match="another Evaluation"):
        ChallengeEvidence(
            check_id="behavior",
            challenge_id="challenge-1",
            evaluation_id="evaluation-1",
            challenge_index=0,
            challenge_digest="sha256:" + "a" * 64,
            status="observed",
            observation={"answer": 4},
            output_artifacts=(wrong_artifact,),
        )
