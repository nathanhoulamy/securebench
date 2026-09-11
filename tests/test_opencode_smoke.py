"""Opt-in runtime compatibility check, not benchmark conversion qualification.

SECUREBENCH_OPENCODE_SMOKE=1 python -m pytest tests/test_opencode_smoke.py -q
"""
import os
import shutil
import subprocess
import uuid

import pytest

from securebench.candidates.capture import HostWorkspaceFilesystem, capture_file_bundle
from securebench.candidates.replay import replay_file_bundle
from securebench.candidates.store import CandidateStore
from securebench.docker_network import ISOLATED_BRIDGE_ARGUMENTS, validate_private_network
from securebench.harnesses.opencode import (
    OPENCODE_DEFAULT_VERSION, OPENCODE_OVERLAY_TARGET, opencode_agent_env,
    opencode_overlay_for_image, opencode_preflight_command, opencode_run_command,
    opencode_shell_command,
)
from securebench.sandboxes import DockerSandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.schemas.benchmark import FileBundleCandidate
from securebench.workspaces.cleanup import remove_untrusted_tree, restore_untrusted_tree_permissions


# Runs only inside the fixture service container, on an isolated internal bridge.
SERVER = r'''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        size = int(self.headers.get('Content-Length', '0'))
        if self.path != '/v1/chat/completions' or not 0 < size <= 4 * 1024 * 1024:
            self.send_error(400); return
        if self.headers.get('Authorization') != 'Bearer securebench-dummy-api-key':
            self.send_error(401); return
        request = json.loads(self.rfile.read(size))
        names = [t.get('function', {}).get('name') for t in request.get('tools', [])]
        done = any(m.get('role') == 'tool' for m in request.get('messages', []))
        if 'write' in names and not done:
            delta = {'tool_calls': [{'index': 0, 'id': 'call_fixture', 'type': 'function',
                     'function': {'name': 'write', 'arguments': json.dumps({'filePath': '/app/answer.txt', 'content': 'opencode-smoke\n'})}}]}
            finish = 'tool_calls'
        else:
            delta = {'content': 'Done.'}
            finish = 'stop'
        if request.get('stream'):
            chunks = [{'role': 'assistant'}, delta, {}]
            payload = b''
            for i, part in enumerate(chunks):
                chunk = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1,
                         'model': 'abliterated-model', 'choices': [{'index': 0, 'delta': part,
                         'finish_reason': finish if i == 2 else None}]}
                payload += ('data: ' + json.dumps(chunk) + '\n\n').encode()
            payload += b'data: [DONE]\n\n'
            kind = 'text/event-stream'
        else:
            payload = json.dumps({'id':'fixture', 'object':'chat.completion', 'created':1,
                       'model':'abliterated-model', 'choices':[{'index':0, 'message':{'role':'assistant','content':'Done.'},'finish_reason':'stop'}]}).encode()
            kind = 'application/json'
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
HTTPServer(('0.0.0.0', 8090), Handler).serve_forever()
'''


def test_pinned_opencode_edits_and_replays(tmp_path):
    if os.environ.get("SECUREBENCH_OPENCODE_SMOKE") != "1":
        pytest.skip("set SECUREBENCH_OPENCODE_SMOKE=1 to run Docker runtime smoke")
    if not shutil.which("docker"):
        pytest.skip("Docker is unavailable")
    info = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    if info.returncode:
        pytest.skip("Docker daemon is unavailable")

    def docker(args):
        return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=120).stdout.strip()

    image = "python:3.11-slim-bookworm"
    docker(["pull", image])
    image = docker(["image", "inspect", "--format", "{{.Id}}", image])
    overlay = opencode_overlay_for_image(image, OPENCODE_DEFAULT_VERSION)
    name = "securebench-opencode-smoke-" + uuid.uuid4().hex
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    docker(["network", "create", *ISOLATED_BRIDGE_ARGUMENTS, name])
    sandbox = None
    try:
        validate_private_network(name, lambda command: docker(command[1:]))
        docker(["run", "-d", "--name", name, "--network", name, "--network-alias", "fixture",
                "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                image, "python", "-c", SERVER])
        docker(["exec", name, "python", "-c", """
import socket, time
for attempt in range(100):
    try:
        socket.create_connection(('127.0.0.1', 8090), timeout=1).close()
        break
    except OSError:
        time.sleep(0.1)
else:
    raise RuntimeError('fixture did not start')
"""])
        sandbox = DockerSandbox(
            image=image, root=workspace, workspace_mount_target="/app", network=name, read_only=False,
            env=opencode_agent_env({}, "http://fixture:8090/v1", provider="abliteration", model="abliterated-model"),
            mounts=(DockerBindMount(overlay.path, OPENCODE_OVERLAY_TARGET, read_only=True),
                    DockerBindMount(home, "/opt/securebench/opencode-home", read_only=False)),
        )
        preflight = sandbox.run(opencode_shell_command(opencode_preflight_command(OPENCODE_DEFAULT_VERSION)), timeout=30)
        assert preflight.exit_code == 0, preflight.stderr
        result = sandbox.run(opencode_shell_command(opencode_run_command(
            "abliteration", "abliterated-model", "Write opencode-smoke followed by a newline to /app/answer.txt using the write tool.")),
            workdir="/app", timeout=90)
        assert result.exit_code == 0 and not result.timed_out, result.stderr
        sandbox.close()
        sandbox = None
        restore_untrusted_tree_permissions(workspace, image=image)
        spec = FileBundleCandidate(type="file_bundle", max_total_files=1, max_total_bytes=1024,
            files=[{"id":"answer", "path":"/app/answer.txt", "kind":"regular_file", "max_bytes":1024}])
        store = CandidateStore(tmp_path / "store")
        baseline = "sha256:" + "0" * 64
        candidate = capture_file_bundle(HostWorkspaceFilesystem(workspace, guest_root="/app"), spec, store, baseline_digest=baseline)
        replay = tmp_path / "replay"
        replay.mkdir()
        replay_file_bundle(candidate, store, replay, guest_root="/app", expected_baseline_digest=baseline)
        assert (replay / "answer.txt").read_bytes() == b"opencode-smoke\n"
        assert list(replay.iterdir()) == [replay / "answer.txt"]
    finally:
        if sandbox is not None:
            sandbox.close()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
        docker(["network", "rm", name])
        remove_untrusted_tree(home, image=image)
