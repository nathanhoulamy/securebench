# Private Docker network deployment validation

SecureBench's three private-network owners (Agent egress, provider relay, and
Trusted Helper Evaluation) explicitly create `bridge`, `--internal` networks
with both `com.docker.network.bridge.gateway_mode_ipv4=isolated` and
`com.docker.network.bridge.gateway_mode_ipv6=isolated`. Setting the IPv6 mode
does **not** enable IPv6. Evaluations without HTTP helpers and Agents without
permitted egress keep `network=none`.

Each owner immediately inspects the new network before launching its services
or making the network available to untrusted containers. The shared check
requires the bridge driver, boolean Internal flag, both isolated modes, and
default IPAM with the expected IPv4/optional IPv6 subnets and **no effective
IPAM gateway**. Inspection selects configuration fields (not endpoints or
labels), has a 30-second deadline and a 16-KiB parsing ceiling. Errors abort
startup and invoke the existing owner's cleanup; there is no ordinary-internal
fallback. Failed helper network removal retains ownership for retry.

This is a configuration preflight, not proof that a backend enforces isolation.
An old daemon merely echoing options is insufficient: the effective IPAM
configuration must also satisfy the check, and the deployment must pass live
qualification. Docker documents isolated mode in its
[Engine 28 release notes](https://docs.docker.com/engine/release-notes/28/) and
[gateway mode reference](https://docs.docker.com/engine/network/port-publishing/#gateway-modes).

## Deployment procedure

Use a local Linux Docker worker with `ip`, this repository's development Python
environment, and the locally available `python:3.11-slim` image plus the digest
pinned by `HTTP_REQUEST_RECORDER_IMAGE`. Run serially; the suite deliberately
reserves `192.0.0.8/29` on its disposable upstream bridge. Ensure that this
special-purpose range is unused by the deployment. It gives the controlled
HTTP service the Python-public-unicast address `192.0.0.9`, so the unchanged
proxy's real DNS/address policy can run without contacting an Internet service.
A test-only hosts entry maps `allowed.test` to that address, avoiding an IPv6
ULA DNS answer that the proxy correctly rejects. No proxy policy is bypassed.

Record `docker version`, selected `docker info` fields, local daemon
configuration, and image IDs. Then run:

```sh
SECUREBENCH_DOCKER_INTEGRATION=1 .venv/bin/pytest -q -s \
  tests/test_docker_network_isolation_live.py
```

All six variants must pass: egress, provider relay, and helper Evaluation, each
with default IPv4 and explicitly enabled test-only dual stack. The suite uses
production network owners, relay/proxy implementations and authenticated HTTP
helpers. Test containers drop all capabilities, use read-only root filesystems,
and join exactly their declared network. Only the relay/proxy bridge the Agent
network and upstream network. Controlled peer services and probes join their
intentionally permitted test networks; no ports are published.

Each denied target has a positive control first: an upstream peer reaches the
external service and host listeners; a peer in the other case reaches that
case's service; the host reaches any scoped link-local listener. Successful
connections to relay/proxy and authenticated helper requests establish the
permitted paths. An actual HTTP response through the unchanged allowlisted
proxy establishes forwarded access. Socket probes have one-second deadlines,
HTTP requests three seconds, Docker operations thirty seconds, and readiness
retries are bounded. All resources are removed in `finally`, followed by
explicit container/network absence and host-listener thread checks.

Do not interpret a failed positive control as successful isolation, or skip a
failed IPv6 variant to qualify a dual-stack deployment. Re-run after changing
Docker, kernel, network configuration or container capabilities. No test
requires daemon changes, installed packages, manual firewall rules, production
credentials, or production endpoints.

## Worker result: 2026-09-08

- Docker client/server: Engine Community **29.7.2**, API 1.55; server commit
  `6a43e3d`, containerd 2.3.3, runc 1.4.3.
- Linux/amd64, Ubuntu 26.04 LTS, kernel `7.0.0-29-generic`; overlayfs storage,
  systemd cgroup v2, IPv4 forwarding enabled; AppArmor, builtin seccomp and
  private cgroup namespaces. No `/etc/docker/daemon.json` was present. No daemon
  settings, manual firewall rules or existing workloads were changed.
- Probe/proxy/relay image resolved once per variant to
  `sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7`.
  The real helper used the repository's independently pinned image digest.
- Regression tests: **229 passed, 6 opt-in tests skipped**. Three existing live
  protocol/helper/networkless Evaluation tests also passed.
- **Six live isolation variants passed.** Agent-to-proxy and Agent-to-relay TCP,
  authenticated Evaluation-to-helper HTTP (204), and allowlisted proxied HTTP
  with an exact controlled response body succeeded.
- Direct connections from both Agent policy variants and Evaluation to the
  controlled upstream service, another case's service, and wildcard-bound host
  listeners were blocked (`ENETUNREACH`). Host targets included the worker's
  LAN IPv4 address, `docker0`, and the disposable upstream gateway. Dual-stack
  probes also blocked the other case's IPv6 address, upstream service IPv6
  address, and upstream host IPv6 gateway. Each target's positive control passed.
- IPv4-only bridges acquired host IPv6 link-local addresses after endpoints
  attached, despite gateway-free IPAM. The host listener was reachable locally
  at those scoped addresses, but IPv4-only untrusted containers could not
  connect to them (`ENETUNREACH`). Dual-stack isolated bridges had no host IP
  addresses. This is why IPAM/echoed options alone are not an enforcement test.
- Every variant removed its containers (including relay/proxy/helpers), networks
  and listeners. No remaining route was demonstrated by these probes.

Scope: the external target is a controlled Docker upstream service, not a public
Internet endpoint. IPv6 testing uses Docker-assigned ULA addresses; this worker
has no global IPv6 uplink. Relay reachability uses synthetic credentials and
never calls a provider. These tests establish the connections and attacks
exercised on this worker, not universal isolation or benchmark conversion
admission. Container network administration/raw-packet capabilities, host
networking and published ports are outside this tested topology and must not
be granted to untrusted containers.
