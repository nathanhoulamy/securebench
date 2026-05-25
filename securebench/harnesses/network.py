"""Harness network egress policy helpers."""

from __future__ import annotations

import ipaddress
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from securebench.errors import ConfigError


CODEX_PROVIDER_DOMAINS = ("api.openai.com",)
CLAUDE_CODE_PROVIDER_DOMAINS = ("api.anthropic.com",)
EGRESS_PROXY_ALIAS = "securebench-egress-proxy"
EGRESS_PROXY_PORT = 8080
EGRESS_PROXY_IMAGE = "python:3.11-slim"
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


@dataclass(frozen=True)
class HarnessEgress:
    """Docker network and proxy environment for one harness sandbox."""

    network: str
    env: dict[str, str]
    allowed_domains: tuple[str, ...]


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
    """Return provider defaults plus tester-configured domains for a harness."""
    provider_domains: tuple[str, ...]
    if harness == "codex":
        provider_domains = CODEX_PROVIDER_DOMAINS
    elif harness == "claude_code":
        provider_domains = CLAUDE_CODE_PROVIDER_DOMAINS
    else:
        provider_domains = ()
    domains = []
    seen = set()
    for domain in (*provider_domains, *configured):
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


def egress_proxy_script() -> Path:
    return Path(__file__).resolve().parent / "egress_proxy.py"


def _run_docker(command: list[str], action: str) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ConfigError(f"Failed to {action}: {completed.stderr.strip()}")
