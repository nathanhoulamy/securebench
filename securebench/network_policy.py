"""Shared network policy parsing and resolution."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Literal

from securebench.errors import ConfigError


MAX_ALLOWED_DOMAINS = 1024
_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
NetworkPolicyMode = Literal["benchmark", "replace", "extend"]
AgentNetworkMode = Literal["none", "restricted", "internet"]


def normalize_domain(value: Any, field: str) -> str:
    """Validate a DNS domain name and return its lowercase form."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty DNS domain name")
    domain = value.strip().lower().rstrip(".")
    if not domain:
        raise ConfigError(f"{field} must be a non-empty DNS domain name")
    if "://" in domain or "/" in domain or ":" in domain or "*" in domain:
        raise ConfigError(
            f"{field} must be a DNS domain name without scheme, port, path, or wildcard"
        )
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


def allowed_domains_config(
    value: Any,
    field: str = "harness.config.allowed_domains",
) -> tuple[str, ...]:
    """Parse and normalize a bounded allowed-domain list."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list of DNS domain names")
    if len(value) > MAX_ALLOWED_DOMAINS:
        raise ConfigError(f"{field} may contain at most {MAX_ALLOWED_DOMAINS} items")
    domains = []
    seen = set()
    for index, item in enumerate(value):
        domain = normalize_domain(item, f"{field}[{index}]")
        if domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return tuple(domains)


@dataclass(frozen=True)
class NetworkPolicy:
    """Tester-level network policy applied to a benchmark row."""

    mode: NetworkPolicyMode = "benchmark"
    allowed_domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in ("benchmark", "replace", "extend"):
            raise ConfigError(
                "network_policy.mode must be one of: benchmark, replace, extend"
            )
        if not isinstance(self.allowed_domains, (list, tuple)):
            raise ConfigError("network_policy.allowed_domains must be a list of DNS domain names")
        domains = allowed_domains_config(list(self.allowed_domains), "network_policy.allowed_domains")
        if self.mode == "benchmark" and domains:
            raise ConfigError(
                "network_policy.allowed_domains must be empty when mode is benchmark"
            )
        object.__setattr__(self, "allowed_domains", domains)


def _row_domains(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ConfigError(
            "environment.agent_network.allowed_domains must be a list of DNS domain names"
        )
    return allowed_domains_config(
        list(value), "environment.agent_network.allowed_domains"
    )


def resolve_allowed_domains(
    row_mode: AgentNetworkMode | str,
    row_domains: Any,
    policy: NetworkPolicy,
) -> tuple[str, ...]:
    """Resolve the effective generic egress domains for one benchmark row."""
    if row_mode not in ("none", "restricted", "internet"):
        raise ConfigError(
            "environment.agent_network.mode must be one of: none, restricted, internet"
        )
    domains = _row_domains(row_domains)
    if row_mode == "none" and domains:
        raise ConfigError(
            "environment.agent_network.allowed_domains must be empty when mode is none"
        )
    if policy.mode == "replace":
        return policy.allowed_domains
    if row_mode == "none":
        return ()
    if policy.mode == "extend":
        return tuple(dict.fromkeys((*domains, *policy.allowed_domains)))
    return domains
