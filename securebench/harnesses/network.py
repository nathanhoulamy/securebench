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
    api_key_env: str
    base_url: str
    blocked_tool_types: tuple[str, ...] = ()
    blocked_tool_prefixes: tuple[str, ...] = ()
    allowed_client_tool_types: tuple[str, ...] = ()


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

    def __enter__(self) -> HarnessEgress:
        if not self.allowed_domains:
            return HarnessEgress(network="none", env={}, allowed_domains=())

        suffix = uuid.uuid4().hex
        self._network_name = f"securebench-egress-{suffix}"
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
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    self.proxy_container,
                    "--network",
                    "bridge",
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
        if self.proxy_container is not None:
            subprocess.run(
                ["docker", "rm", "-f", self.proxy_container],
                check=False,
                capture_output=True,
                text=True,
            )
            self.proxy_container = None
        if self._network_name is not None:
            subprocess.run(
                ["docker", "network", "rm", self._network_name],
                check=False,
                capture_output=True,
                text=True,
            )
            self._network_name = None


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
        relay_image: str = PROVIDER_RELAY_IMAGE,
        proxy_image: str = EGRESS_PROXY_IMAGE,
    ) -> None:
        self.spec = spec
        self.provider = spec.provider
        self.allowed_domains = tuple(allowed_domains)
        self.allow_external_tools = allow_external_tools
        self.relay_image = relay_image
        self.proxy_image = proxy_image
        self.network = "none"
        self.relay_container: str | None = None
        self.proxy_container: str | None = None
        self._network_name: str | None = None
        self._log_cleanup: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> HarnessEgress:
        require_provider_key(self.spec)
        suffix = uuid.uuid4().hex
        self._network_name = f"securebench-egress-{suffix}"
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
                "bridge",
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
        _run_docker(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self.relay_container or "",
                "--network",
                "bridge",
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
                "-e",
                self.spec.api_key_env,
                "-e",
                f"SECUREBENCH_PROVIDER={self.provider}",
                "-e",
                f"SECUREBENCH_UPSTREAM_HOST={self.spec.upstream_host}",
                "-e",
                f"SECUREBENCH_API_KEY_ENV={self.spec.api_key_env}",
                "-e",
                f"SECUREBENCH_BLOCKED_TOOL_TYPES={json.dumps(sorted(self.spec.blocked_tool_types))}",
                "-e",
                f"SECUREBENCH_BLOCKED_TOOL_PREFIXES={json.dumps(sorted(self.spec.blocked_tool_prefixes))}",
                "-e",
                f"SECUREBENCH_ALLOWED_CLIENT_TOOL_TYPES={json.dumps(sorted(self.spec.allowed_client_tool_types))}",
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
            ],
            "start provider relay",
        )
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
        for container in (self.relay_container, self.proxy_container):
            if container is not None:
                subprocess.run(
                    ["docker", "rm", "-f", container],
                    check=False,
                    capture_output=True,
                    text=True,
                )
        self.relay_container = None
        self.proxy_container = None
        if self._network_name is not None:
            subprocess.run(
                ["docker", "network", "rm", self._network_name],
                check=False,
                capture_output=True,
                text=True,
            )
            self._network_name = None
        if self._log_cleanup is not None:
            self._log_cleanup.cleanup()
            self._log_cleanup = None


def docker_provider_relay_policy(
    spec: ProviderRelaySpec,
    allowed_domains: tuple[str, ...],
    *,
    allow_external_tools: bool = False,
) -> DockerProviderRelayPolicy:
    return DockerProviderRelayPolicy(
        spec,
        allowed_domains,
        allow_external_tools=allow_external_tools,
    )


def require_provider_key(spec: ProviderRelaySpec) -> None:
    env_name = spec.api_key_env
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
    for line in path.read_text(errors="ignore").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        requests += 1
        if record.get("status") == "blocked":
            blocked += 1
    return {
        "provider_relay_requests": requests,
        "provider_relay_blocked": blocked,
    }


def egress_proxy_script() -> Path:
    return Path(__file__).resolve().parent / "egress_proxy.py"


def provider_relay_script() -> Path:
    return Path(__file__).resolve().parent / "provider_relay.py"


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
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ConfigError(f"Failed to {action}: {completed.stderr.strip()}")
