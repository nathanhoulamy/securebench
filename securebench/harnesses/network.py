"""Harness network egress policy helpers."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from securebench.errors import ConfigError


EGRESS_PROXY_ALIAS = "securebench-egress-proxy"
EGRESS_PROXY_PORT = 8080
EGRESS_PROXY_IMAGE = "python:3.11-slim"
PROVIDER_RELAY_ALIAS = "securebench-provider-relay"
PROVIDER_RELAY_PORT = 8090
PROVIDER_RELAY_IMAGE = "python:3.11-slim"
PROVIDER_RELAY_CODEX_AUTH_TARGET = "/var/lib/securebench/codex-auth"
DOCKER_OPERATION_TIMEOUT_SECONDS = 30.0
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


@dataclass(frozen=True)
class HarnessEgress:
    """Docker network and proxy environment for one harness sandbox."""

    network: str
    env: dict[str, str]
    allowed_domains: tuple[str, ...]
    provider: str | None = None
    provider_base_url: str | None = None
    relay_log_dir: str | None = None
    provider_relay_enabled: bool = False
    allow_external_tools: bool = False


@dataclass(frozen=True)
class ProviderRelaySpec:
    """Provider-specific relay policy supplied by a harness."""

    provider: str
    upstream_host: str
    credential_env: str | None
    credential_kind: str
    base_url: str
    allowed_client_tool_types: tuple[str, ...] = ()
    allow_untyped_client_tools: bool = False
    allowed_path_prefixes: tuple[str, ...] = ()
    allowed_methods: tuple[str, ...] = ("POST",)


def allowed_domains_config(value: Any, field: str = "harness.config.allowed_domains") -> tuple[str, ...]:
    """Parse and normalize a harness allowed-domain list."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list of DNS domain names")
    domains = []
    seen = set()
    for index, item in enumerate(value):
        domain = normalize_domain(item, f"{field}[{index}]")
        if domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return tuple(domains)


def effective_allowed_domains(harness: str, configured: tuple[str, ...]) -> tuple[str, ...]:
    """Return tester-configured generic egress domains for a harness."""
    domains = []
    seen = set()
    for domain in configured:
        normalized = normalize_domain(domain, f"{harness}.allowed_domains")
        if normalized not in seen:
            seen.add(normalized)
            domains.append(normalized)
    return tuple(domains)


def normalize_domain(value: Any, field: str) -> str:
    """Validate a DNS domain name and return its lowercase form."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty DNS domain name")
    domain = value.strip().lower().rstrip(".")
    if not domain:
        raise ConfigError(f"{field} must be a non-empty DNS domain name")
    if "://" in domain or "/" in domain or ":" in domain or "*" in domain:
        raise ConfigError(f"{field} must be a DNS domain name without scheme, port, path, or wildcard")
    if domain == "localhost" or domain.endswith(".localhost"):
        raise ConfigError(f"{field} must not be localhost")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ConfigError(f"{field} must be a DNS domain name, not an IP address")
    if len(domain) > 253 or "." not in domain:
        raise ConfigError(f"{field} must be a DNS domain name with at least two labels")
    labels = domain.split(".")
    if any(not _LABEL_RE.fullmatch(label) for label in labels):
        raise ConfigError(f"{field} must be a valid DNS domain name")
    return domain


def domain_allowed(host: str, allowed_domains: tuple[str, ...]) -> bool:
    """Return whether host matches an allowed domain or one of its subdomains."""
    normalized = normalize_domain(host, "host")
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in allowed_domains)


class DockerEgressPolicy:
    """Create a strict Docker egress path for a harness container."""

    def __init__(
        self,
        allowed_domains: tuple[str, ...],
        *,
        proxy_image: str = EGRESS_PROXY_IMAGE,
    ) -> None:
        self.allowed_domains = tuple(allowed_domains)
        self.proxy_image = proxy_image
        self.network = "none"
        self.proxy_container: str | None = None
        self._network_name: str | None = None
        self._upstream_network_name: str | None = None

    def __enter__(self) -> HarnessEgress:
        if not self.allowed_domains:
            return HarnessEgress(network="none", env={}, allowed_domains=())

        suffix = uuid.uuid4().hex
        self._network_name = f"securebench-egress-{suffix}"
        self._upstream_network_name = f"securebench-upstream-{suffix}"
        self.proxy_container = f"securebench-egress-proxy-{suffix}"
        try:
            _run_docker(
                [
                    "docker",
                    "network",
                    "create",
                    "--internal",
                    self._network_name,
                ],
                "create egress network",
            )
            _run_docker(
                ["docker", "network", "create", self._upstream_network_name],
                "create upstream network",
            )
            _run_docker(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    self.proxy_container,
                    "--network",
                    self._upstream_network_name,
                    "--cap-drop",
                    "ALL",
                    "--read-only",
                    "--tmpfs",
                    "/tmp",
                    "--memory",
                    "128m",
                    "--pids-limit",
                    "64",
                    "--security-opt",
                    "no-new-privileges:true",
                    "-e",
                    f"SECUREBENCH_ALLOWED_DOMAINS={','.join(self.allowed_domains)}",
                    "--mount",
                    f"type=bind,source={egress_proxy_script()},target=/opt/securebench/egress_proxy.py,readonly",
                    self.proxy_image,
                    "python3",
                    "/opt/securebench/egress_proxy.py",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(EGRESS_PROXY_PORT),
                ],
                "start egress proxy",
            )
            _run_docker(
                [
                    "docker",
                    "network",
                    "connect",
                    "--alias",
                    EGRESS_PROXY_ALIAS,
                    self._network_name,
                    self.proxy_container,
                ],
                "connect egress proxy",
            )
        except Exception:
            self._cleanup()
            raise

        self.network = self._network_name
        proxy_url = f"http://{EGRESS_PROXY_ALIAS}:{EGRESS_PROXY_PORT}"
        return HarnessEgress(
            network=self.network,
            env={
                "HTTP_PROXY": proxy_url,
                "HTTPS_PROXY": proxy_url,
                "ALL_PROXY": proxy_url,
                "NO_PROXY": "localhost,127.0.0.1,::1",
                "http_proxy": proxy_url,
                "https_proxy": proxy_url,
                "all_proxy": proxy_url,
                "no_proxy": "localhost,127.0.0.1,::1",
            },
            allowed_domains=self.allowed_domains,
        )

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        failures: list[str] = []
        if self.proxy_container is not None:
            if _docker_cleanup_succeeded(
                ["docker", "rm", "-f", self.proxy_container],
                missing_marker="No such container",
            ):
                self.proxy_container = None
            else:
                failures.append("egress proxy container")
        if self._network_name is not None:
            if _docker_cleanup_succeeded(
                ["docker", "network", "rm", self._network_name],
                missing_marker="not found",
            ):
                self._network_name = None
            else:
                failures.append("egress network")
        if self._upstream_network_name is not None:
            if _docker_cleanup_succeeded(
                ["docker", "network", "rm", self._upstream_network_name],
                missing_marker="not found",
            ):
                self._upstream_network_name = None
            else:
                failures.append("upstream network")
        if failures:
            raise ConfigError("Docker egress cleanup failed for: " + ", ".join(failures))


def docker_egress_policy(allowed_domains: tuple[str, ...]) -> DockerEgressPolicy:
    return DockerEgressPolicy(allowed_domains)


class DockerProviderRelayPolicy:
    """Create Docker egress for a named provider relay plus optional web egress proxy."""

    def __init__(
        self,
        spec: ProviderRelaySpec,
        allowed_domains: tuple[str, ...],
        *,
        allow_external_tools: bool = False,
        credential_file: Path | None = None,
        relay_image: str = PROVIDER_RELAY_IMAGE,
        proxy_image: str = EGRESS_PROXY_IMAGE,
    ) -> None:
        self.spec = spec
        self.provider = spec.provider
        self.allowed_domains = tuple(allowed_domains)
        self.allow_external_tools = allow_external_tools
        self.credential_file = credential_file
        self.relay_image = relay_image
        self.proxy_image = proxy_image
        self.network = "none"
        self.relay_container: str | None = None
        self.proxy_container: str | None = None
        self._network_name: str | None = None
        self._upstream_network_name: str | None = None
        self._log_cleanup: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> HarnessEgress:
        require_provider_credential(self.spec, self.credential_file)
        suffix = uuid.uuid4().hex
        self._network_name = f"securebench-egress-{suffix}"
        self._upstream_network_name = f"securebench-upstream-{suffix}"
        self.relay_container = f"securebench-provider-relay-{suffix}"
        self._log_cleanup = tempfile.TemporaryDirectory(prefix="securebench-provider-relay-")
        relay_log_dir = Path(self._log_cleanup.name)
        try:
            _run_docker(
                [
                    "docker",
                    "network",
                    "create",
                    "--internal",
                    self._network_name,
                ],
                "create provider relay network",
            )
            _run_docker(
                ["docker", "network", "create", self._upstream_network_name],
                "create provider upstream network",
            )
            if self.allowed_domains:
                self.proxy_container = f"securebench-egress-proxy-{suffix}"
                self._start_egress_proxy()
            self._start_provider_relay(relay_log_dir)
        except Exception:
            self._cleanup()
            raise

        self.network = self._network_name
        env = _proxy_env() if self.allowed_domains else {}
        return HarnessEgress(
            network=self.network,
            env=env,
            allowed_domains=self.allowed_domains,
            provider=self.provider,
            provider_base_url=self.spec.base_url,
            relay_log_dir=str(relay_log_dir),
            provider_relay_enabled=True,
            allow_external_tools=self.allow_external_tools,
        )

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._cleanup()

    def _start_egress_proxy(self) -> None:
        _run_docker(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.proxy_container or "",
                "--network",
                self._upstream_network_name or "",
                "--cap-drop",
                "ALL",
                "--read-only",
                "--tmpfs",
                "/tmp",
                "--memory",
                "128m",
                "--pids-limit",
                "64",
                "--security-opt",
                "no-new-privileges:true",
                "-e",
                f"SECUREBENCH_ALLOWED_DOMAINS={','.join(self.allowed_domains)}",
                "--mount",
                f"type=bind,source={egress_proxy_script()},target=/opt/securebench/egress_proxy.py,readonly",
                self.proxy_image,
                "python3",
                "/opt/securebench/egress_proxy.py",
                "--host",
                "0.0.0.0",
                "--port",
                str(EGRESS_PROXY_PORT),
            ],
            "start egress proxy",
        )
        _run_docker(
            [
                "docker",
                "network",
                "connect",
                "--alias",
                EGRESS_PROXY_ALIAS,
                self._network_name or "",
                self.proxy_container or "",
            ],
            "connect egress proxy",
        )

    def _start_provider_relay(self, relay_log_dir: Path) -> None:
        user_arguments = []
        getuid = getattr(os, "getuid", None)
        getgid = getattr(os, "getgid", None)
        if getuid is not None and getgid is not None:
            # The relay writes only to a host-owned bounded log directory and,
            # for subscription auth, reads the host-owned credential file.
            # Matching the orchestrator UID avoids granting DAC capabilities.
            user_arguments = ["--user", f"{getuid()}:{getgid()}"]
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.relay_container or "",
            "--network",
            self._upstream_network_name or "",
            "--cap-drop",
            "ALL",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--memory",
            "256m",
            "--pids-limit",
            "64",
            "--security-opt",
            "no-new-privileges:true",
            *user_arguments,
        ]
        if self.spec.credential_kind == "codex-oauth":
            if self.credential_file is None:
                raise ConfigError("Codex subscription relay requires a credential file")
            command.extend(
                [
                    "-e",
                    (
                        "SECUREBENCH_CREDENTIAL_FILE="
                        f"{PROVIDER_RELAY_CODEX_AUTH_TARGET}/{self.credential_file.name}"
                    ),
                    "--mount",
                    (
                        f"type=bind,source={self.credential_file.parent},"
                        f"target={PROVIDER_RELAY_CODEX_AUTH_TARGET}"
                    ),
                    "--mount",
                    (
                        f"type=bind,source={codex_oauth_script()},"
                        "target=/opt/securebench/codex_oauth.py,readonly"
                    ),
                    "--mount",
                    (
                        f"type=bind,source={locking_script()},"
                        "target=/opt/securebench/locking.py,readonly"
                    ),
                ]
            )
        else:
            if self.spec.credential_env is None:
                raise ConfigError("provider relay requires a credential environment variable")
            command.extend(
                [
                    "-e",
                    self.spec.credential_env,
                    "-e",
                    f"SECUREBENCH_CREDENTIAL_ENV={self.spec.credential_env}",
                ]
            )
        command.extend(
            [
                "-e",
                f"SECUREBENCH_PROVIDER={self.provider}",
                "-e",
                f"SECUREBENCH_UPSTREAM_HOST={self.spec.upstream_host}",
                "-e",
                f"SECUREBENCH_CREDENTIAL_KIND={self.spec.credential_kind}",
                "-e",
                f"SECUREBENCH_ALLOWED_CLIENT_TOOL_TYPES={json.dumps(sorted(self.spec.allowed_client_tool_types))}",
                "-e",
                f"SECUREBENCH_ALLOW_UNTYPED_CLIENT_TOOLS={str(self.spec.allow_untyped_client_tools).lower()}",
                "-e",
                f"SECUREBENCH_ALLOWED_PATH_PREFIXES={json.dumps(sorted(self.spec.allowed_path_prefixes))}",
                "-e",
                f"SECUREBENCH_ALLOWED_METHODS={json.dumps(sorted(self.spec.allowed_methods))}",
                "-e",
                f"SECUREBENCH_ALLOW_EXTERNAL_TOOLS={str(self.allow_external_tools).lower()}",
                "-e",
                "SECUREBENCH_RELAY_LOG_DIR=/var/log/securebench-provider-relay",
                "--mount",
                f"type=bind,source={provider_relay_script()},target=/opt/securebench/provider_relay.py,readonly",
                "--mount",
                f"type=bind,source={relay_log_dir},target=/var/log/securebench-provider-relay",
                self.relay_image,
                "python3",
                "/opt/securebench/provider_relay.py",
                "--host",
                "0.0.0.0",
                "--port",
                str(PROVIDER_RELAY_PORT),
            ]
        )
        _run_docker(command, "start provider relay")
        _run_docker(
            [
                "docker",
                "network",
                "connect",
                "--alias",
                PROVIDER_RELAY_ALIAS,
                self._network_name or "",
                self.relay_container or "",
            ],
            "connect provider relay",
        )

    def _cleanup(self) -> None:
        failures: list[str] = []
        if self.relay_container is not None:
            if _docker_cleanup_succeeded(
                ["docker", "rm", "-f", self.relay_container],
                missing_marker="No such container",
            ):
                self.relay_container = None
            else:
                failures.append("provider relay container")
        if self.proxy_container is not None:
            if _docker_cleanup_succeeded(
                ["docker", "rm", "-f", self.proxy_container],
                missing_marker="No such container",
            ):
                self.proxy_container = None
            else:
                failures.append("egress proxy container")
        if self._network_name is not None:
            if _docker_cleanup_succeeded(
                ["docker", "network", "rm", self._network_name],
                missing_marker="not found",
            ):
                self._network_name = None
            else:
                failures.append("provider relay network")
        if self._upstream_network_name is not None:
            if _docker_cleanup_succeeded(
                ["docker", "network", "rm", self._upstream_network_name],
                missing_marker="not found",
            ):
                self._upstream_network_name = None
            else:
                failures.append("provider upstream network")
        if not failures and self._log_cleanup is not None:
            self._log_cleanup.cleanup()
            self._log_cleanup = None
        if failures:
            raise ConfigError("Docker provider cleanup failed for: " + ", ".join(failures))


def docker_provider_relay_policy(
    spec: ProviderRelaySpec,
    allowed_domains: tuple[str, ...],
    *,
    allow_external_tools: bool = False,
    credential_file: Path | None = None,
) -> DockerProviderRelayPolicy:
    return DockerProviderRelayPolicy(
        spec,
        allowed_domains,
        allow_external_tools=allow_external_tools,
        credential_file=credential_file,
    )


def require_provider_credential(
    spec: ProviderRelaySpec,
    credential_file: Path | None = None,
) -> None:
    if spec.credential_kind == "codex-oauth":
        if credential_file is None or not credential_file.is_file():
            raise ConfigError(
                "Codex subscription login is required; run `securebench auth codex login`"
            )
        return
    env_name = spec.credential_env
    if env_name is None:
        raise ConfigError(f"{spec.provider} provider relay has no credential source")
    if not os.environ.get(env_name):
        raise ConfigError(f"{spec.provider} provider relay requires environment variable: {env_name}")


def relay_decision_summary(log_dir: str | Path | None) -> dict[str, int]:
    """Summarize redacted provider relay decisions."""
    if log_dir is None:
        return {"provider_relay_requests": 0, "provider_relay_blocked": 0}
    path = Path(log_dir) / "decisions.jsonl"
    if not path.exists():
        return {"provider_relay_requests": 0, "provider_relay_blocked": 0}
    requests = 0
    blocked = 0
    try:
        with path.open("rb") as log_file:
            while True:
                line = log_file.readline(64 * 1024 + 1)
                if not line:
                    break
                oversized = len(line) > 64 * 1024
                while oversized and not line.endswith(b"\n"):
                    line = log_file.readline(64 * 1024 + 1)
                    if not line or line.endswith(b"\n"):
                        break
                if oversized:
                    continue
                try:
                    record = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                requests += 1
                if record.get("status") == "blocked":
                    blocked += 1
    except OSError:
        return {"provider_relay_requests": 0, "provider_relay_blocked": 0}
    return {
        "provider_relay_requests": requests,
        "provider_relay_blocked": blocked,
    }


def egress_proxy_script() -> Path:
    return Path(__file__).resolve().parent / "egress_proxy.py"


def provider_relay_script() -> Path:
    return Path(__file__).resolve().parent / "provider_relay.py"


def codex_oauth_script() -> Path:
    return Path(__file__).resolve().parent / "codex_oauth.py"


def locking_script() -> Path:
    return Path(__file__).resolve().parents[1] / "locking.py"


def _proxy_env() -> dict[str, str]:
    proxy_url = f"http://{EGRESS_PROXY_ALIAS}:{EGRESS_PROXY_PORT}"
    no_proxy = f"localhost,127.0.0.1,::1,{EGRESS_PROXY_ALIAS},{PROVIDER_RELAY_ALIAS}"
    return {
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "ALL_PROXY": proxy_url,
        "NO_PROXY": no_proxy,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
        "all_proxy": proxy_url,
        "no_proxy": no_proxy,
    }


def _run_docker(command: list[str], action: str) -> None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=DOCKER_OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"Failed to {action}: Docker operation did not complete") from exc
    if completed.returncode != 0:
        raise ConfigError(f"Failed to {action}: {completed.stderr.strip()}")


def _docker_cleanup_succeeded(command: list[str], *, missing_marker: str) -> bool:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=DOCKER_OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 or missing_marker.lower() in completed.stderr.lower()
