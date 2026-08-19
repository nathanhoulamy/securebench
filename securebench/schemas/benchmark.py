"""SecureBench v2 benchmark-pack and benchmark-row schemas.

The Pydantic models in this module are the executable source of truth for the
checked-in JSON Schemas. Cross-document and filesystem checks that require a
pack root or component registry are intentionally performed by the compiler.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


SCHEMA_VERSION = "2.0"
EXECUTION_PROFILE_STRICT = "strict-split/v1"
EXECUTION_PROFILE_BATCHED = "batched-split/v1"

FamilyName = Literal["repo_patch", "terminal_task"]
AgentNetwork = Literal["none", "restricted", "internet"]
ComponentId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$", min_length=1, max_length=128),
]
ComponentReference = Annotated[
    str,
    StringConstraints(pattern=r"^(runtime|host)\.[A-Za-z][A-Za-z0-9_.-]*$", max_length=256),
]
ImmutableImageReference = Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class StrictModel(BaseModel):
    """Base class for closed, immutable author-facing schema objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceRoots(StrictModel):
    """Non-overlapping source roots for the three visibility lanes."""

    public: str = "assets/"
    runtime: str = "evaluation_inputs/"
    host: str = "hidden/"

    @field_validator("public", "runtime", "host")
    @classmethod
    def validate_root(cls, value: str) -> str:
        return _relative_pack_path(value, "resource root")

    @model_validator(mode="after")
    def roots_do_not_overlap(self) -> "ResourceRoots":
        roots = {
            "public": PurePosixPath(self.public),
            "runtime": PurePosixPath(self.runtime),
            "host": PurePosixPath(self.host),
        }
        for left_name, left in roots.items():
            for right_name, right in roots.items():
                if left_name >= right_name:
                    continue
                if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                    raise ValueError(
                        f"resource roots {left_name!r} and {right_name!r} may not overlap"
                    )
        return self


class AssetDefaults(StrictModel):
    read_only: bool = True


class EnvironmentDefaults(StrictModel):
    image: ImmutableImageReference | None = None
    workdir: str | None = None
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    agent_network: AgentNetwork | None = None

    @field_validator("workdir")
    @classmethod
    def validate_optional_workdir(cls, value: str | None) -> str | None:
        return None if value is None else _absolute_runtime_path(value, "environment.workdir")

    @field_validator("image")
    @classmethod
    def validate_optional_image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _immutable_image_reference(value)


class BenchmarkDefaultsV2(StrictModel):
    family: FamilyName | None = None
    environment: EnvironmentDefaults = Field(default_factory=EnvironmentDefaults)


class BenchmarkPackManifestV2(StrictModel):
    """SecureBench v2 benchmark-pack manifest."""

    schema_version: Literal[SCHEMA_VERSION]
    id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    defaults: BenchmarkDefaultsV2 = Field(default_factory=BenchmarkDefaultsV2)
    resource_roots: ResourceRoots = Field(default_factory=ResourceRoots)
    asset_defaults: AssetDefaults = Field(default_factory=AssetDefaults)


class EnvironmentSpec(StrictModel):
    image: ImmutableImageReference
    workdir: str
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    agent_network: AgentNetwork

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        return _immutable_image_reference(value)

    @field_validator("workdir")
    @classmethod
    def validate_workdir(cls, value: str) -> str:
        return _absolute_runtime_path(value, "environment.workdir")


class PublicAsset(StrictModel):
    path: str
    mount: str
    read_only: bool = True

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_pack_path(value, "asset.path")

    @field_validator("mount")
    @classmethod
    def validate_mount(cls, value: str) -> str:
        return _absolute_runtime_path(value, "asset.mount")


class RuntimeResource(StrictModel):
    path: str
    mount: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_pack_path(value, "runtime resource path")

    @field_validator("mount")
    @classmethod
    def validate_mount(cls, value: str) -> str:
        return _absolute_runtime_path(value, "runtime resource mount")


class HostResource(StrictModel):
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_pack_path(value, "host resource path")


class VerificationResources(StrictModel):
    runtime: dict[ComponentId, RuntimeResource] = Field(default_factory=dict)
    host: dict[ComponentId, HostResource] = Field(default_factory=dict)


class GitPatchCandidate(StrictModel):
    type: Literal["git_patch"]
    max_patch_bytes: Annotated[int, Field(gt=0)]
    max_changed_files: Annotated[int, Field(gt=0)]
    max_changed_bytes: Annotated[int, Field(gt=0)]
    allow_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()

    @field_validator("allow_paths", "exclude_paths")
    @classmethod
    def validate_patterns(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or "\\" in value for value in values):
            raise ValueError("candidate path patterns must be non-empty POSIX patterns")
        return values


class RegularFileEntry(StrictModel):
    id: ComponentId
    path: str
    kind: Literal["regular_file"]
    max_bytes: Annotated[int, Field(gt=0)]

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _absolute_runtime_path(value, "file bundle entry path")


class DirectoryTreeEntry(StrictModel):
    id: ComponentId
    path: str
    kind: Literal["directory_tree"]
    max_files: Annotated[int, Field(gt=0)]
    max_total_bytes: Annotated[int, Field(gt=0)]
    allow_internal_symlinks: bool = False

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _absolute_runtime_path(value, "file bundle entry path")


FileBundleEntry = Annotated[
    RegularFileEntry | DirectoryTreeEntry,
    Field(discriminator="kind"),
]


class FileBundleCandidate(StrictModel):
    type: Literal["file_bundle"]
    max_total_files: Annotated[int, Field(gt=0)]
    max_total_bytes: Annotated[int, Field(gt=0)]
    files: Annotated[tuple[FileBundleEntry, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_entries(self) -> "FileBundleCandidate":
        _unique((entry.id for entry in self.files), "file bundle entry id")
        _non_overlapping_paths((entry.path for entry in self.files), "file bundle entry paths")
        maximum_files = sum(
            1 if isinstance(entry, RegularFileEntry) else entry.max_files for entry in self.files
        )
        maximum_bytes = sum(
            entry.max_bytes if isinstance(entry, RegularFileEntry) else entry.max_total_bytes
            for entry in self.files
        )
        if maximum_files > self.max_total_files:
            raise ValueError("file bundle entry file bounds exceed candidate.max_total_files")
        if maximum_bytes > self.max_total_bytes:
            raise ValueError("file bundle entry byte bounds exceed candidate.max_total_bytes")
        return self


class FilesystemOverlayCandidate(StrictModel):
    type: Literal["filesystem_overlay"]
    include_roots: Annotated[tuple[str, ...], Field(min_length=1)]
    max_files: Annotated[int, Field(gt=0)]
    max_total_bytes: Annotated[int, Field(gt=0)]

    @field_validator("include_roots")
    @classmethod
    def validate_roots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            _absolute_runtime_path(value, "filesystem overlay include root") for value in values
        )
        _non_overlapping_paths(normalized, "filesystem overlay include roots")
        return normalized


CandidateSpec = Annotated[
    GitPatchCandidate | FileBundleCandidate | FilesystemOverlayCandidate,
    Field(discriminator="type"),
]


class ArtifactSource(StrictModel):
    entry: ComponentId | None = None
    path: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or "\\" in value:
            raise ValueError("artifact source path must be a non-empty POSIX path")
        path = PurePosixPath(value)
        if ".." in path.parts or str(path) in ("", "."):
            raise ValueError("artifact source path may not contain '..' or resolve to '.'")
        return str(path)

    @model_validator(mode="after")
    def exactly_one_source(self) -> "ArtifactSource":
        if (self.entry is None) == (self.path is None):
            raise ValueError("artifact source requires exactly one of entry or path")
        return self


class ArtifactLimits(StrictModel):
    max_bytes: Annotated[int, Field(gt=0)] | None = None
    max_files: Annotated[int, Field(gt=0)] | None = None
    max_total_bytes: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def validate_limit_shape(self) -> "ArtifactLimits":
        byte_input = self.max_bytes is not None
        tree_input = self.max_files is not None or self.max_total_bytes is not None
        if byte_input == tree_input:
            raise ValueError(
                "artifact limits require either max_bytes or both max_files and max_total_bytes"
            )
        if tree_input and (self.max_files is None or self.max_total_bytes is None):
            raise ValueError("tree artifact limits require max_files and max_total_bytes")
        return self


class ArtifactSpec(StrictModel):
    id: ComponentId
    source: ArtifactSource
    parser: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    limits: ArtifactLimits


class ArtifactCheck(StrictModel):
    id: ComponentId
    type: Literal["artifact"]
    artifacts: Annotated[tuple[ArtifactSpec, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def artifact_ids_are_unique(self) -> "ArtifactCheck":
        _unique((artifact.id for artifact in self.artifacts), "artifact id")
        return self


class ChallengeSpec(StrictModel):
    source: ComponentReference
    max_cases: Annotated[int, Field(gt=0)]
    max_case_bytes: Annotated[int, Field(gt=0)]


class ServiceSpec(StrictModel):
    id: ComponentId
    component: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    configuration: ComponentReference | None = None
    limits: dict[str, Any]


class ProtocolArtifactSpec(StrictModel):
    id: ComponentId
    parser: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    limits: ArtifactLimits


class ProtocolLimits(StrictModel):
    seconds_per_case: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    observation_bytes_per_case: Annotated[int, Field(gt=0)]


class ProtocolCheck(StrictModel):
    id: ComponentId
    type: Literal["protocol"]
    adapter: ComponentReference
    protocol: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    challenge: ChallengeSpec
    services: tuple[ServiceSpec, ...] = ()
    artifacts: tuple[ProtocolArtifactSpec, ...] = ()
    limits: ProtocolLimits

    @model_validator(mode="after")
    def local_ids_are_unique(self) -> "ProtocolCheck":
        _unique((service.id for service in self.services), "service id")
        _unique((artifact.id for artifact in self.artifacts), "protocol artifact id")
        return self


CheckSpec = Annotated[ArtifactCheck | ProtocolCheck, Field(discriminator="type")]


class VerificationSpec(StrictModel):
    execution_profile: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    candidate: CandidateSpec
    resources: VerificationResources = Field(default_factory=VerificationResources)
    checks: Annotated[tuple[CheckSpec, ...], Field(min_length=1)]
    oracle: ComponentReference

    @model_validator(mode="after")
    def references_are_consistent(self) -> "VerificationSpec":
        _unique((check.id for check in self.checks), "check id")
        runtime_ids = set(self.resources.runtime)
        host_ids = set(self.resources.host)
        _require_reference(self.oracle, "host", host_ids, "verification.oracle")

        file_entries = (
            {entry.id: entry for entry in self.candidate.files}
            if isinstance(self.candidate, FileBundleCandidate)
            else {}
        )
        for check in self.checks:
            if isinstance(check, ArtifactCheck):
                for artifact in check.artifacts:
                    self._validate_artifact_source(artifact, file_entries)
                continue
            _require_reference(check.adapter, "runtime", runtime_ids, f"check {check.id}.adapter")
            _require_reference(
                check.challenge.source,
                "host",
                host_ids,
                f"check {check.id}.challenge.source",
            )
            for service in check.services:
                if service.configuration is not None:
                    _require_reference(
                        service.configuration,
                        "host",
                        host_ids,
                        f"check {check.id}.service {service.id}.configuration",
                    )
        return self

    def _validate_artifact_source(
        self,
        artifact: ArtifactSpec,
        file_entries: dict[str, FileBundleEntry],
    ) -> None:
        source = artifact.source
        if source.entry is not None:
            if not isinstance(self.candidate, FileBundleCandidate):
                raise ValueError(
                    f"artifact {artifact.id!r} uses source.entry but candidate is not a file_bundle"
                )
            entry = file_entries.get(source.entry)
            if entry is None:
                raise ValueError(
                    f"artifact {artifact.id!r} references unknown candidate entry {source.entry!r}"
                )
            if isinstance(entry, RegularFileEntry) and artifact.limits.max_bytes is None:
                raise ValueError(f"artifact {artifact.id!r} requires byte limits for a regular file")
            if isinstance(entry, DirectoryTreeEntry) and artifact.limits.max_files is None:
                raise ValueError(f"artifact {artifact.id!r} requires tree limits for a directory entry")
            return
        if isinstance(self.candidate, FileBundleCandidate):
            raise ValueError("file_bundle artifact sources must use source.entry")
        assert source.path is not None
        path = PurePosixPath(source.path)
        if isinstance(self.candidate, GitPatchCandidate) and path.is_absolute():
            raise ValueError("git_patch artifact source.path must be repository-relative")
        if isinstance(self.candidate, FilesystemOverlayCandidate):
            if not path.is_absolute():
                raise ValueError("filesystem_overlay artifact source.path must be absolute")
            if not any(path.is_relative_to(PurePosixPath(root)) for root in self.candidate.include_roots):
                raise ValueError("filesystem_overlay artifact source.path is outside candidate include_roots")


class BenchmarkRowDocumentV2(StrictModel):
    """One row before manifest defaults are applied."""

    id: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    family: FamilyName | None = None
    input: dict[str, Any]
    assets: tuple[PublicAsset, ...] = ()
    environment: EnvironmentDefaults = Field(default_factory=EnvironmentDefaults)
    verification: VerificationSpec
    metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkRowV2(StrictModel):
    """One fully defaulted and semantically validated SecureBench v2 row."""

    id: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    family: FamilyName
    input: dict[str, Any]
    assets: tuple[PublicAsset, ...] = ()
    environment: EnvironmentSpec
    verification: VerificationSpec
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_family_contract(self) -> "BenchmarkRowV2":
        if self.family == "repo_patch":
            _validate_input(
                self.input,
                required={"repo", "base_commit", "instructions"},
                optional={"hints"},
                context="repo_patch input",
            )
            if not isinstance(self.verification.candidate, GitPatchCandidate):
                raise ValueError("repo_patch rows require a git_patch candidate")
        elif self.family == "terminal_task":
            _validate_input(
                self.input,
                required={"instructions"},
                optional={"context"},
                context="terminal_task input",
            )
            if isinstance(self.verification.candidate, GitPatchCandidate):
                raise ValueError(
                    "terminal_task rows require a file_bundle or filesystem_overlay candidate"
                )
        _non_overlapping_paths((asset.mount for asset in self.assets), "public asset mounts")
        runtime_mounts = tuple(resource.mount for resource in self.verification.resources.runtime.values())
        _non_overlapping_paths(runtime_mounts, "runtime resource mounts")
        _cross_namespace_mounts_do_not_overlap(self.assets, self.verification.resources.runtime)
        return self


def normalize_benchmark_row(
    document: BenchmarkRowDocumentV2,
    manifest: BenchmarkPackManifestV2,
) -> BenchmarkRowV2:
    """Apply manifest defaults and return the executable row model."""
    family = document.family or manifest.defaults.family
    if family is None:
        raise ValueError("row.family is required when manifest.defaults.family is not set")

    defaults = manifest.defaults.environment.model_dump(exclude_none=True)
    override = document.environment.model_dump(exclude_none=True)
    environment = {**defaults, **override}
    missing = sorted(
        {"image", "workdir", "timeout_seconds", "agent_network"} - set(environment)
    )
    if missing:
        raise ValueError(
            "row environment is missing required defaulted field(s): " + ", ".join(missing)
        )
    assets = tuple(
        asset.model_copy(
            update={
                "read_only": (
                    asset.read_only
                    if "read_only" in asset.model_fields_set
                    else manifest.asset_defaults.read_only
                )
            }
        )
        for asset in document.assets
    )
    return BenchmarkRowV2.model_validate(
        {
            "id": document.id,
            "family": family,
            "input": document.input,
            "assets": [asset.model_dump() for asset in assets],
            "environment": environment,
            "verification": document.verification.model_dump(),
            "metadata": document.metadata,
        }
    )


def _relative_pack_path(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{field} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
        raise ValueError(f"{field} must be relative and may not contain '..'")
    return str(path)


def _absolute_runtime_path(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{field} must be a non-empty POSIX absolute path")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or str(path) == "/":
        raise ValueError(f"{field} must be absolute, non-root, and may not contain '..'")
    return str(path)


def _immutable_image_reference(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("environment.image must be a non-empty immutable image reference")
    value = value.strip()
    digest = re.search(r"(?:@sha256:|^sha256:)([0-9a-fA-F]{64})$", value)
    if digest is None:
        raise ValueError(
            "environment.image must be pinned by sha256 digest (name@sha256:... or sha256:...)"
        )
    start, end = digest.span(1)
    return value[:start] + value[start:end].lower() + value[end:]


def _unique(values: Any, field: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate {field}(s): {', '.join(sorted(duplicates))}")


def _non_overlapping_paths(values: Any, field: str) -> None:
    paths = tuple(PurePosixPath(value) for value in values)
    for index, left in enumerate(paths):
        for right in paths[index + 1 :]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError(f"{field} may not overlap: {left} and {right}")


def _require_reference(
    reference: str,
    namespace: Literal["runtime", "host"],
    known: set[str],
    field: str,
) -> None:
    prefix, identifier = reference.split(".", 1)
    if prefix != namespace:
        raise ValueError(f"{field} must reference {namespace}.<id>")
    if identifier not in known:
        raise ValueError(f"{field} references unknown {namespace} resource {identifier!r}")


def _validate_input(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str],
    context: str,
) -> None:
    unknown = sorted(set(value) - required - optional)
    missing = sorted(required - set(value))
    if unknown:
        raise ValueError(f"{context} has unknown field(s): {', '.join(unknown)}")
    if missing:
        raise ValueError(f"{context} is missing field(s): {', '.join(missing)}")
    for key in required:
        item = value[key]
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}.{key} must be a non-empty string")
    if "hints" in value and (not isinstance(value["hints"], str) or not value["hints"].strip()):
        raise ValueError(f"{context}.hints must be a non-empty string")
    if "context" in value and not isinstance(value["context"], (str, dict)):
        raise ValueError(f"{context}.context must be a string or object")


def _cross_namespace_mounts_do_not_overlap(
    assets: tuple[PublicAsset, ...],
    runtime: dict[str, RuntimeResource],
) -> None:
    for asset in assets:
        asset_path = PurePosixPath(asset.mount)
        for identifier, resource in runtime.items():
            runtime_path = PurePosixPath(resource.mount)
            if (
                asset_path == runtime_path
                or asset_path.is_relative_to(runtime_path)
                or runtime_path.is_relative_to(asset_path)
            ):
                raise ValueError(
                    f"public asset mount {asset.mount!r} overlaps runtime resource "
                    f"{identifier!r} at {resource.mount!r}"
                )
