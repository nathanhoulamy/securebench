"""Shared fail-closed configuration check for private Docker bridges.

Inspect is configuration evidence, not a substitute for deployment connection
qualification. In particular, echoed driver options alone are insufficient.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable

from securebench.errors import ConfigError


ISOLATED_BRIDGE_ARGUMENTS = [
    "--internal", "--driver", "bridge",
    "--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated",
    "--opt", "com.docker.network.bridge.gateway_mode_ipv6=isolated",
]
# Select only bounded configuration fields, excluding endpoints and labels.
_INSPECT_FORMAT = (
    '[{{json .Driver}},{{json .Internal}},'
    '{{json (index .Options "com.docker.network.bridge.gateway_mode_ipv4")}},'
    '{{json (index .Options "com.docker.network.bridge.gateway_mode_ipv6")}},'
    '{{json .EnableIPv6}},{{json .IPAM}}]'
)


def validate_private_network(name: str, run: Callable[[list[str]], str]) -> None:
    """Require isolated modes and effective IPAM with no host gateways.

    The caller owns cleanup, including when creation or inspection fails.
    No IPv6 enablement is requested by this policy.
    """
    raw = run(["docker", "network", "inspect", "--format", _INSPECT_FORMAT, name])
    try:
        if len(raw) > 16384:
            raise ValueError("oversized configuration")
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != 6:
            raise ValueError("malformed configuration")
        driver, internal, ipv4, ipv6, enabled6, ipam = value
        if driver != "bridge" or internal is not True:
            raise ValueError("expected an internal bridge")
        if ipv4 != "isolated" or ipv6 != "isolated":
            raise ValueError("both gateway modes must be isolated")
        if type(enabled6) is not bool:
            raise ValueError("missing IPv6 configuration")
        configs = ipam["Config"]
        if ipam["Driver"] != "default" or not isinstance(configs, list) or not 1 <= len(configs) <= 2:
            raise ValueError("unexpected IPAM configuration")
        families = []
        for config in configs:
            if config.get("Gateway") not in (None, ""):
                raise ValueError("effective IPAM still assigns a gateway")
            families.append(ipaddress.ip_network(config["Subnet"]).version)
        if sorted(families) != ([4, 6] if enabled6 else [4]):
            raise ValueError("unexpected effective subnets")
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise ConfigError(f"Private Docker network {name} is not isolated: {str(exc)[:512]}") from exc
