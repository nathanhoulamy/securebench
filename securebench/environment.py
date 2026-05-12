"""Execution environment and Docker image helpers."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from securebench.errors import ConfigError


SUPPORTED_DOCKER_NETWORKS = {"none", "bridge"}
DEFAULT_ENVIRONMENT_PYTHON = "3.11-slim"
ENVIRONMENT_IMAGE_REPOSITORY = "securebench-agent-runtime"
PYTHON_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:-[A-Za-z0-9._-]+)?$")
PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]*$")


@dataclass(frozen=True)
class SandboxPolicySection:
    network: str = "none"
    cap_drop: tuple[str, ...] = ("ALL",)
    read_only: bool = True
    tmpfs: tuple[str, ...] = ("/tmp",)
    mem_limit: str | None = "1g"
    pids_limit: int | None = 256
    security_opt: tuple[str, ...] = ("no-new-privileges:true",)

    def docker_kwargs(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "cap_drop": self.cap_drop,
            "read_only": self.read_only,
            "tmpfs": self.tmpfs,
            "mem_limit": self.mem_limit,
            "pids_limit": self.pids_limit,
            "security_opt": self.security_opt,
        }


@dataclass(frozen=True)
class EnvironmentRoleSection:
    setup: tuple[str, ...] = ()
    network: str | None = None
    writable: bool | None = None


@dataclass(frozen=True)
class EnvironmentSection:
    python: str = DEFAULT_ENVIRONMENT_PYTHON
    packages: tuple[str, ...] = ()
    network: str = "none"
    writable: bool = False
    setup: tuple[str, ...] = ()
    producer: EnvironmentRoleSection = field(default_factory=EnvironmentRoleSection)
    runner: EnvironmentRoleSection = field(default_factory=EnvironmentRoleSection)

    @property
    def image(self) -> str:
        return environment_image_tag(self.python, self.packages)

    def producer_setup_commands(self) -> tuple[str, ...]:
        return (*self.setup, *self.producer.setup)

    def runner_setup_commands(self) -> tuple[str, ...]:
        return (*self.setup, *self.runner.setup)

    def producer_sandbox_policy(self) -> SandboxPolicySection:
        return environment_sandbox_policy(self, self.producer)

    def runner_sandbox_policy(self) -> SandboxPolicySection:
        return environment_sandbox_policy(self, self.runner)


def environment_python(value: Any, field: str) -> str:
    if not isinstance(value, str) or not PYTHON_VERSION_PATTERN.fullmatch(value):
        raise ConfigError(f"{field} must be a Python image tag like '3.11-slim' or '3.9-slim-bullseye'")
    return value


def environment_packages(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list of package names")
    packages = []
    for item in value:
        if not isinstance(item, str) or not PACKAGE_NAME_PATTERN.fullmatch(item):
            raise ConfigError(f"{field} entries must be non-empty package names")
        packages.append(item)
    return tuple(sorted(dict.fromkeys(packages)))


def sandbox_network(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a string")
    if value not in SUPPORTED_DOCKER_NETWORKS:
        expected = ", ".join(sorted(SUPPORTED_DOCKER_NETWORKS))
        raise ConfigError(f"{field} must be one of: {expected}")
    return value


def environment_sandbox_policy(
    environment: EnvironmentSection,
    role: EnvironmentRoleSection,
) -> SandboxPolicySection:
    writable = environment.writable if role.writable is None else role.writable
    return SandboxPolicySection(
        network=environment.network if role.network is None else role.network,
        read_only=not writable,
    )


def environment_image_tag(python_version: str, packages: tuple[str, ...]) -> str:
    if not packages:
        return f"{ENVIRONMENT_IMAGE_REPOSITORY}:py{python_version}"
    digest = hashlib.sha256(
        "\n".join((python_version, *sorted(packages))).encode("utf-8")
    ).hexdigest()[:12]
    return f"{ENVIRONMENT_IMAGE_REPOSITORY}:py{python_version}-{digest}"


def ensure_environment_image(*, image: str, python_version: str, packages: tuple[str, ...]) -> None:
    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ConfigError(f"Failed to inspect environment image {image!r}: {exc}") from exc
    if inspect.returncode == 0:
        return

    root = Path(__file__).resolve().parents[1]
    dockerfile = root / "docker" / "agent.Dockerfile"
    try:
        build = subprocess.run(
            [
                "docker",
                "build",
                "-f",
                str(dockerfile),
                "--build-arg",
                f"PYTHON_VERSION={python_version}",
                "--build-arg",
                f"ENVIRONMENT_PACKAGES={' '.join(packages)}",
                "-t",
                image,
                str(root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ConfigError(f"Failed to build environment image {image!r}: {exc}") from exc
    if build.returncode != 0:
        details = build.stderr.strip() or build.stdout.strip() or f"exit code {build.returncode}"
        raise ConfigError(f"Failed to build environment image {image!r}: {details}")
