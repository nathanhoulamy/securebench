"""Opt-in Linux deployment qualification; all endpoints are disposable controls."""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from securebench.harnesses import network
from securebench.schemas.benchmark import TrustedHelperSpec
from securebench.verification import trusted_helpers

pytestmark = pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 on a Linux Docker worker",
)


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr[:2048]
    return result.stdout.strip()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"securebench-isolation-control")

    def log_message(self, *_):
        pass


SERVER = '''
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write(b'securebench-isolation-control')
 def log_message(self, *args): pass
class S(ThreadingHTTPServer): address_family = socket.AF_INET6
S(('::',80),H).serve_forever()
'''
PROBE = '''
import json,socket,sys
try:
 s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=1)
 s.close(); print(json.dumps({'connected':True}))
except OSError as e:
 print(json.dumps({'connected':False,'error':str(e)}))
'''


@pytest.mark.parametrize("kind", ["egress", "relay", "helper"])
@pytest.mark.parametrize("ipv6", [False, True], ids=["ipv4", "dual-stack"])
def test_private_network_boundary(monkeypatch, kind, ipv6):
    prefix = "securebench-nettest-" + uuid.uuid4().hex[:12]
    containers, policies, evaluations, owned_networks = [], [], [], []
    image = docker("image", "inspect", "python:3.11-slim", "--format", "{{.Id}}")
    assert image.startswith("sha256:")
    upstream_target = None
    upstream = None

    def start(network_name, *, server=False, extra=()):
        name = f"{prefix}-{len(containers)}"
        containers.append(name)  # Retain ownership even if launch/response fails.
        docker("run", "-d", "--name", name, "--network", network_name,
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
               "--read-only", "--pids-limit", "64", "--memory", "128m",
               *extra, image, "python3", "-c", SERVER if server else "import time; time.sleep(600)")
        return name

    def addresses(container, net):
        endpoint = json.loads(docker("inspect", container))[0]["NetworkSettings"]["Networks"][net]
        return [endpoint["IPAddress"]] + ([endpoint["GlobalIPv6Address"]] if ipv6 else [])

    def probe(container, host, port, allowed):
        result = json.loads(docker("exec", container, "python3", "-c", PROBE, host, str(port)))
        print(f"{kind} IPv6={ipv6}: {container.removeprefix(prefix)} -> {host}:{port}: {result}")
        assert result["connected"] is allowed

    def ready(container, host, port):
        for _ in range(20):
            result = json.loads(docker("exec", container, "python3", "-c", PROBE, host, str(port)))
            if result["connected"]:
                return
            time.sleep(0.1)
        pytest.fail(f"positive control unavailable: {host}:{port}")

    original_harness_run = network._run_docker
    original_helper_run = trusted_helpers._run_docker

    def create_options(command):
        if command[:3] == ["docker", "network", "create"]:
            owned_networks.append(command[-1])
            if ipv6:
                command = [*command[:-1], "--ipv6", command[-1]]
        return command

    def harness_run(command, action):
        nonlocal upstream_target, upstream
        command = create_options(command)
        is_upstream = command[:3] == ["docker", "network", "create"] and "--internal" not in command
        if is_upstream:
            # Special-purpose anycast addresses .9/.10 are classified as global
            # by Python. Keep the controlled target on this disposable bridge;
            # exercise the real proxy's public-address check without weakening it
            # or contacting an Internet endpoint. Abort if this range is in use.
            command = [*command[:-1], "--subnet", "192.0.0.8/29", "--gateway", "192.0.0.14", command[-1]]
        if command[:2] == ["docker", "run"]:
            # Keep allowed.test IPv4-only: a ULA AAAA answer would correctly
            # fail the proxy's existing public-unicast DNS policy.
            command = [*command[:2], "--add-host", "allowed.test:192.0.0.9", *command[2:]]
        result = original_harness_run(command, action)
        if is_upstream:
            upstream = command[-1]
            upstream_target = start(upstream, server=True,
                extra=("--ip", "192.0.0.9", "--network-alias", "allowed.test"))
        return result

    def helper_run(command, code, message):
        return original_helper_run(create_options(command), code, message)

    monkeypatch.setattr(network, "_run_docker", harness_run)
    monkeypatch.setattr(trusted_helpers, "_run_docker", helper_run)
    # All authentication is synthetic and confined to disposable test resources.
    monkeypatch.setenv("SECUREBENCH_ISOLATION_TEST_KEY", "disposable-test-key")
    host_server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=host_server.serve_forever, daemon=True)
    thread.start()
    host6 = None
    thread6 = None
    try:
        if socket.has_ipv6:
            class Server6(ThreadingHTTPServer):
                address_family = socket.AF_INET6
            host6 = Server6(("::", 0), Handler)
            thread6 = threading.Thread(target=host6.serve_forever, daemon=True)
            thread6.start()
        if kind == "relay":
            spec = network.ProviderRelaySpec("openai", "allowed.test", "SECUREBENCH_ISOLATION_TEST_KEY",
                "bearer", "http://securebench-provider-relay:8090")
            policy = network.DockerProviderRelayPolicy(spec, ("allowed.test",), relay_image=image, proxy_image=image)
        else:
            policy = network.DockerEgressPolicy(("allowed.test",), proxy_image=image)
        policies.append(policy)
        egress = policy.__enter__()
        agent = start(egress.network)
        ready(agent, network.EGRESS_PROXY_ALIAS, network.EGRESS_PROXY_PORT)
        probe(agent, network.EGRESS_PROXY_ALIAS, network.EGRESS_PROXY_PORT, True)
        if kind == "relay":
            ready(agent, network.PROVIDER_RELAY_ALIAS, network.PROVIDER_RELAY_PORT)
            probe(agent, network.PROVIDER_RELAY_ALIAS, network.PROVIDER_RELAY_PORT, True)
        control = start(upstream)
        ready(control, "192.0.0.9", 80)
        probe(control, "192.0.0.9", 80, True)
        response = docker("exec", agent, "python3", "-c",
            "import urllib.request; o=urllib.request.build_opener(urllib.request.ProxyHandler({'http':"
            "'http://securebench-egress-proxy:8080'})); print(o.open('http://allowed.test/',timeout=3).read(100).decode())")
        assert response == "securebench-isolation-control"
        print("allowed access through unchanged egress proxy: PASS")

        case_clients = []
        helper = TrustedHelperSpec.model_validate({"name": "recorder",
            "type": trusted_helpers.HTTP_REQUEST_RECORDER_TYPE,
            "limits": {"max_requests": 16, "max_body_bytes": 128}})
        for _ in range(2):
            evaluation = trusted_helpers.TrustedHelperEvaluation(task=SimpleNamespace(),
                check=SimpleNamespace(trusted_helpers=(helper,)),
                catalog=trusted_helpers.default_trusted_helper_catalog(), challenge_id=prefix, evaluation_id=uuid.uuid4().hex)
            evaluations.append(evaluation)
            access = evaluation.start()["recorder"]
            client = start(evaluation.network)
            case_clients.append(client)
            response = docker("exec", client, "python3", "-c",
                "import sys,urllib.request; r=urllib.request.Request(sys.argv[1],headers={'Authorization':sys.argv[2]}); "
                "print(urllib.request.urlopen(r,timeout=3).status)", access["url"], access["authorization"])
            assert response == "204"
            print("Evaluation -> declared authenticated helper: PASS")
        subject = case_clients[0] if kind == "helper" else agent
        subject_net = evaluations[0].network if kind == "helper" else egress.network
        assert set(json.loads(docker("inspect", subject))[0]["NetworkSettings"]["Networks"]) == {subject_net}
        for container in (policy.proxy_container, getattr(policy, "relay_container", None)):
            if container:
                assert set(json.loads(docker("inspect", container))[0]["NetworkSettings"]["Networks"]) == {egress.network, upstream}

        # Target on another case: prove reachability from its own permitted peer.
        other_target = start(evaluations[1].network, server=True)
        for address in addresses(other_target, evaluations[1].network):
            ready(case_clients[1], address, 80)
            probe(case_clients[1], address, 80, True)
            probe(subject, address, 80, False)
        # An external target is controlled and directly reachable upstream.
        for address in addresses(upstream_target, upstream):
            probe(control, address, 80, True)
            probe(subject, address, 80, False)
        info = json.loads(docker("network", "inspect", upstream))[0]
        host_targets = [(c["Gateway"], host6.server_port if ":" in c["Gateway"] else host_server.server_port)
                        for c in info["IPAM"]["Config"]]
        links = json.loads(subprocess.run(["ip", "-j", "addr"], check=True, capture_output=True, text=True, timeout=5).stdout)
        host_targets += [(a["local"], host_server.server_port) for link in links for a in link["addr_info"]
                         if a["family"] == "inet" and not ipaddress.ip_address(a["local"]).is_loopback]
        for address, port in dict.fromkeys(host_targets):
            probe(control, address, port, True)
            probe(subject, address, port, False)
        for net in [egress.network, *(e.network for e in evaluations)]:
            info = json.loads(docker("network", "inspect", net))[0]
            bridge = "br-" + info["Id"][:12]
            bridge_addresses = next(link for link in links if link["ifname"] == bridge)["addr_info"]
            assert all(a["scope"] == "link" and a["family"] == "inet6" for a in bridge_addresses)
            if net == subject_net and host6:
                for address in bridge_addresses:
                    # A peer on this exact bridge is the positive control for
                    # scoped host addresses; host-namespace access proves the
                    # listener exists even when guest IPv6 itself is disabled.
                    scoped = address["local"] + "%" + bridge
                    with socket.create_connection((scoped, host6.server_port), timeout=1):
                        pass
                    probe(subject, address["local"] + "%eth0", host6.server_port, False)
            assert info["EnableIPv6"] is ipv6
            print(f"{bridge}: no host global address: PASS")
    finally:
        # Continue all cleanup attempts even if one fails, and verify by name.
        failures = []
        policy_containers = [name for policy in policies
            for name in (policy.proxy_container, getattr(policy, "relay_container", None)) if name]
        helper_containers = [runtime.container_name for evaluation in evaluations
            for runtime in evaluation._runtimes if hasattr(runtime, "container_name")]
        for container in reversed(containers):
            try:
                docker("rm", "-f", container)
            except AssertionError as exc:
                failures.append(str(exc))
        for evaluation in reversed(evaluations):
            try:
                evaluation.close()
            except Exception as exc:
                failures.append(str(exc))
        for policy in reversed(policies):
            try:
                policy.__exit__(None, None, None)
            except Exception as exc:
                failures.append(str(exc))
        host_server.shutdown()
        host_server.server_close()
        thread.join(5)
        assert not thread.is_alive()
        if host6:
            host6.shutdown()
            host6.server_close()
            thread6.join(5)
            assert not thread6.is_alive()
        remaining_containers = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        remaining_networks = docker("network", "ls", "--format", "{{.Name}}").splitlines()
        assert not set(containers + policy_containers + helper_containers) & set(remaining_containers)
        assert not set(owned_networks) & set(remaining_networks)
        assert not failures, failures
        print(f"{prefix}: containers, networks and host listeners cleaned up: PASS")
