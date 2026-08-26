"""Versioned contracts for protocol adapters and trusted helpers."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from typing_extensions import Annotated

from securebench.schemas.benchmark import ArtifactLimits, TrustedHelperSpec
from securebench.verification.json_data import canonical_json_bytes
from securebench.verification.models import VerificationInfrastructureError


ADAPTER_FORMAT_V2 = "securebench.adapter/v2"
ADAPTER_REQUEST_FORMAT_V2 = "securebench.adapter-request/v2"
ADAPTER_RESPONSE_FORMAT_V2 = "securebench.adapter-response/v2"
TRUSTED_HELPER_CONTRACT_FORMAT_V1 = "securebench.trusted-helper-contract/v1"
MAX_SCHEMA_DEPTH = 16
MAX_SCHEMA_NODES = 256

ContractName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$",
    ),
]
ContractType = Annotated[str, StringConstraints(min_length=1, max_length=256)]
ContractPath = Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class JsonValueSchema(ContractModel):
    """Small closed schema language for finite adapter and helper JSON values."""

    type: Literal["object", "array", "string", "integer", "number", "boolean", "null"]
    properties: dict[ContractName, "JsonValueSchema"] = Field(default_factory=dict)
    required: tuple[ContractName, ...] = ()
    allow_extra_fields: bool = False
    items: "JsonValueSchema | None" = None
    max_fields: int | None = Field(default=None, gt=0)
    max_items: int | None = Field(default=None, gt=0)
    max_utf8_bytes: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def fields_match_type(self) -> "JsonValueSchema":
        if len(set(self.required)) != len(self.required):
            raise ValueError("value schema required fields must be unique")
        if self.type == "object":
            unknown = set(self.required) - set(self.properties)
            if unknown:
                raise ValueError("value schema required fields must be declared properties")
            if self.items is not None or self.max_items is not None or self.max_utf8_bytes is not None:
                raise ValueError("object value schema contains fields for another value type")
        elif self.type == "array":
            if self.items is None:
                raise ValueError("array value schema requires items")
            if (
                self.properties
                or self.required
                or self.allow_extra_fields
                or self.max_fields is not None
                or self.max_utf8_bytes is not None
            ):
                raise ValueError("array value schema contains fields for another value type")
        elif self.type == "string":
            if (
                self.properties
                or self.required
                or self.allow_extra_fields
                or self.items is not None
                or self.max_fields is not None
                or self.max_items is not None
            ):
                raise ValueError("string value schema contains fields for another value type")
        elif (
            self.properties
            or self.required
            or self.allow_extra_fields
            or self.items is not None
            or self.max_fields is not None
            or self.max_items is not None
            or self.max_utf8_bytes is not None
        ):
            raise ValueError("scalar value schema contains fields for another value type")
        _validate_schema_bounds(self)
        return self


class EvaluationParticipant(ContractModel):
    name: ContractName
    type: Literal["candidate"]
    instances: int = Field(gt=0, le=16)


class TrustedHelperUse(ContractModel):
    name: ContractName
    type: ContractType


class OutputArtifactContract(ContractModel):
    name: ContractName
    path: ContractPath
    kind: Literal["regular_file", "directory_tree"]
    maximum_limits: ArtifactLimits

    @field_validator("path")
    @classmethod
    def path_is_canonical(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("output artifact path may not contain a NUL byte")
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("output artifact path must be valid UTF-8") from exc
        path = PurePosixPath(value)
        if value != str(path):
            raise ValueError("output artifact path must use canonical POSIX spelling")
        return value

    @model_validator(mode="after")
    def path_and_limits_match(self) -> "OutputArtifactContract":
        path = PurePosixPath(self.path)
        if (
            not self.path
            or path.is_absolute()
            or ".." in path.parts
            or str(path) in {"", "."}
            or "\\" in self.path
        ):
            raise ValueError("output artifact path must be repository-relative and contained")
        if self.kind == "regular_file" and self.maximum_limits.max_bytes is None:
            raise ValueError("regular-file output artifact requires maximum byte limits")
        if self.kind == "directory_tree" and self.maximum_limits.max_files is None:
            raise ValueError("directory-tree output artifact requires maximum tree limits")
        return self


class AdapterMaximums(ContractModel):
    seconds_per_challenge: float = Field(gt=0, allow_inf_nan=False)
    challenge_bytes: int = Field(gt=0)
    observation_bytes: int = Field(gt=0)


class AdapterManifestV2(ContractModel):
    format: Literal[ADAPTER_FORMAT_V2]
    protocol: ContractType
    command: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    challenge_schema: JsonValueSchema
    observation_schema: JsonValueSchema
    evaluation_participants: Annotated[
        tuple[EvaluationParticipant, ...], Field(min_length=1, max_length=16)
    ]
    uses_trusted_helpers: Annotated[tuple[TrustedHelperUse, ...], Field(max_length=32)] = ()
    output_artifacts: Annotated[
        tuple[OutputArtifactContract, ...], Field(max_length=64)
    ] = ()
    maximums: AdapterMaximums

    @model_validator(mode="after")
    def local_names_are_unique(self) -> "AdapterManifestV2":
        _unique((item.name for item in self.evaluation_participants), "evaluation participant")
        _unique((item.name for item in self.uses_trusted_helpers), "trusted helper")
        _unique((item.name for item in self.output_artifacts), "output artifact")
        return self


class TrustedHelperContract(ContractModel):
    """Fixed capabilities and evidence rules for one registered Trusted Helper."""

    format: Literal[TRUSTED_HELPER_CONTRACT_FORMAT_V1]
    type: ContractType
    capabilities: tuple[ContractName, ...]
    helper_access: Literal["http", "none"]
    settings_schema: JsonValueSchema
    limits_schema: JsonValueSchema
    maximum_limits: dict[ContractName, int]
    evidence_schema: JsonValueSchema
    reset: Literal["fresh_per_evaluation"]
    credentials: Literal["fresh_per_evaluation", "none"]

    @model_validator(mode="after")
    def contract_is_consistent(self) -> "TrustedHelperContract":
        _unique(self.capabilities, "trusted helper capability")
        if self.settings_schema.type != "object" or self.limits_schema.type != "object":
            raise ValueError("trusted helper settings and limits schemas must be objects")
        if any(
            schema.allow_extra_fields
            for schema in (self.settings_schema, self.limits_schema, self.evidence_schema)
            if schema.type == "object"
        ):
            raise ValueError("trusted helper object schemas must reject unknown fields")
        if set(self.maximum_limits) != set(self.limits_schema.properties):
            raise ValueError("trusted helper maximum limits must match its limit fields")
        if any(schema.type != "integer" for schema in self.limits_schema.properties.values()):
            raise ValueError("trusted helper limits must be integers")
        if any(isinstance(value, bool) or value <= 0 for value in self.maximum_limits.values()):
            raise ValueError("trusted helper maximum limits must be positive integers")
        if self.helper_access == "http" and self.credentials != "fresh_per_evaluation":
            raise ValueError("HTTP trusted helpers require fresh per-Evaluation credentials")
        if self.helper_access == "none" and self.credentials != "none":
            raise ValueError("host-only trusted helpers may not declare guest credentials")
        return self


class TrustedHelperCatalog:
    """Host-owned catalog of reviewed Trusted Helper contracts."""

    def __init__(
        self,
        contracts: tuple[TrustedHelperContract, ...] = (),
        runtime_factories: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        self._contracts: dict[str, TrustedHelperContract] = {}
        for contract in contracts:
            if contract.type in self._contracts:
                raise ValueError(f"duplicate trusted helper type: {contract.type}")
            self._contracts[contract.type] = contract
        self._runtime_factories = dict(runtime_factories or {})
        unknown_runtime_types = set(self._runtime_factories) - set(self._contracts)
        if unknown_runtime_types:
            raise ValueError(
                "trusted helper runtimes require registered contracts: "
                + ", ".join(sorted(unknown_runtime_types))
            )
        if any(not callable(factory) for factory in self._runtime_factories.values()):
            raise ValueError("trusted helper runtime factories must be callable")

    def contract(self, helper_type: str) -> TrustedHelperContract:
        try:
            return self._contracts[helper_type]
        except KeyError as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_unavailable",
                f"Trusted Helper type {helper_type!r} is not registered",
                source="trusted_helper",
            ) from exc

    def validate_declaration(self, helper: TrustedHelperSpec) -> TrustedHelperContract:
        contract = self.contract(helper.type)
        try:
            validate_json_value(contract.limits_schema, helper.limits)
        except ValueError as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_limits_invalid",
                f"Trusted Helper {helper.name!r} limits do not match its contract",
                source="trusted_helper",
            ) from exc
        for name, value in helper.limits.items():
            maximum = contract.maximum_limits[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value > maximum
            ):
                raise VerificationInfrastructureError(
                    "trusted_helper_limits_exceeded",
                    f"Trusted Helper {helper.name!r} exceeds its registered maximums",
                    source="trusted_helper",
                )
        return contract

    def validate_settings(self, contract: TrustedHelperContract, value: Any) -> None:
        try:
            validate_json_value(contract.settings_schema, value)
        except ValueError as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_settings_invalid",
                f"Trusted Helper type {contract.type!r} settings do not match its contract",
                source="trusted_helper",
            ) from exc

    def validate_evidence(self, contract: TrustedHelperContract, value: Any) -> None:
        try:
            validate_json_value(contract.evidence_schema, value)
        except ValueError as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_evidence_invalid",
                f"Trusted Helper type {contract.type!r} evidence does not match its contract",
                source="trusted_helper",
            ) from exc

    def runtime_factory(self, helper_type: str) -> Callable[..., Any]:
        """Return the reviewed runtime bound to a registered helper contract."""
        self.contract(helper_type)
        try:
            return self._runtime_factories[helper_type]
        except KeyError as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_runtime_unavailable",
                f"Trusted Helper type {helper_type!r} has no executable runtime",
                source="trusted_helper",
            ) from exc

    def validate_runtime_settings(self, helper_type: str, value: Any) -> None:
        """Apply semantic settings checks owned by the reviewed runtime."""
        factory = self.runtime_factory(helper_type)
        validator = getattr(factory, "validate_settings", None)
        if validator is None:
            return
        try:
            validator(value)
        except VerificationInfrastructureError:
            raise
        except (TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_settings_invalid",
                f"Trusted Helper type {helper_type!r} settings are invalid",
                source="trusted_helper",
            ) from exc

    def validate_runtime_declaration(
        self,
        helper: TrustedHelperSpec,
        settings: Any,
    ) -> None:
        """Apply runtime checks that depend on both row limits and host settings."""
        factory = self.runtime_factory(helper.type)
        validator = getattr(factory, "validate_declaration", None)
        if validator is None:
            return
        try:
            validator(helper, settings)
        except VerificationInfrastructureError:
            raise
        except (TypeError, ValueError) as exc:
            raise VerificationInfrastructureError(
                "trusted_helper_settings_invalid",
                f"Trusted Helper type {helper.type!r} settings exceed row limits",
                source="trusted_helper",
            ) from exc


@dataclass(frozen=True)
class AdapterResponseV2:
    status: Literal["observed", "candidate_error"]
    observation: Any = None
    failure_code: str | None = None
    failure_message: str | None = None


def adapter_request_v2(
    *,
    challenge_id: str,
    evaluation_id: str,
    challenge: Any,
    trusted_helpers: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "format": ADAPTER_REQUEST_FORMAT_V2,
        "challenge_id": challenge_id,
        "evaluation_id": evaluation_id,
        "challenge": challenge,
        "trusted_helpers": trusted_helpers,
    }


def parse_adapter_response_v2(value: Any) -> AdapterResponseV2:
    if not isinstance(value, dict):
        raise ValueError("adapter response must be an object")
    status = value.get("status")
    if value.get("format") != ADAPTER_RESPONSE_FORMAT_V2:
        raise ValueError("adapter response format is invalid")
    if status == "observed":
        if set(value) != {"format", "status", "observation"}:
            raise ValueError("observed adapter response has an invalid shape")
        return AdapterResponseV2(status="observed", observation=value["observation"])
    if status == "candidate_error":
        if set(value) != {"format", "status", "failure"}:
            raise ValueError("candidate-error adapter response has an invalid shape")
        failure = value["failure"]
        if (
            not isinstance(failure, dict)
            or set(failure) != {"code", "message"}
            or not all(isinstance(item, str) and item for item in failure.values())
        ):
            raise ValueError("candidate-error adapter response failure is invalid")
        return AdapterResponseV2(
            status="candidate_error",
            failure_code=failure["code"],
            failure_message=failure["message"],
        )
    raise ValueError("adapter response status is invalid")


def validate_json_value(schema: JsonValueSchema, value: Any, *, path: str = "$") -> None:
    """Validate finite JSON data against the closed SecureBench value schema."""
    if schema.type == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        if schema.max_fields is not None and len(value) > schema.max_fields:
            raise ValueError(f"{path} has too many fields")
        missing = set(schema.required) - set(value)
        if missing:
            raise ValueError(f"{path} is missing required fields")
        extra = set(value) - set(schema.properties)
        if extra and not schema.allow_extra_fields:
            raise ValueError(f"{path} contains unknown fields")
        for name, child in schema.properties.items():
            if name in value:
                validate_json_value(child, value[name], path=f"{path}.{name}")
    elif schema.type == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        if schema.max_items is not None and len(value) > schema.max_items:
            raise ValueError(f"{path} has too many items")
        assert schema.items is not None
        for index, item in enumerate(value):
            validate_json_value(schema.items, item, path=f"{path}[{index}]")
    elif schema.type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        if schema.max_utf8_bytes is not None and len(value.encode("utf-8")) > schema.max_utf8_bytes:
            raise ValueError(f"{path} is too large")
    elif schema.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer")
    elif schema.type == "number":
        try:
            finite_number = (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
            )
        except (OverflowError, ValueError):
            finite_number = False
        if not finite_number:
            raise ValueError(f"{path} must be a finite number")
    elif schema.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean")
    elif value is not None:
        raise ValueError(f"{path} must be null")
    canonical_json_bytes(value)


def _validate_schema_bounds(root: JsonValueSchema) -> None:
    pending = [(root, 1)]
    nodes = 0
    while pending:
        schema, depth = pending.pop()
        nodes += 1
        if depth > MAX_SCHEMA_DEPTH or nodes > MAX_SCHEMA_NODES:
            raise ValueError("value schema exceeds its structural bound")
        pending.extend((child, depth + 1) for child in schema.properties.values())
        if schema.items is not None:
            pending.append((schema.items, depth + 1))


def _unique(values: Any, context: str) -> None:
    collected = tuple(values)
    if len(set(collected)) != len(collected):
        raise ValueError(f"{context} names must be unique")
