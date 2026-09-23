from __future__ import annotations

import base64
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ProtocolCheck
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    assert_file_bundle_capture_rejected,
    load_module,
    load_terminal_task,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/headless-terminal"
IMAGE = (
    "alexgshaw/headless-terminal@"
    "sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa"
)
ADAPTER = PACK / "v2" / "evaluation_inputs" / "headless-terminal" / "adapter"
ORACLE = PACK / "v2" / "hidden" / "headless-terminal" / "oracle" / "oracle.py"
REFERENCE = (
    PACK
    / "v2"
    / "hidden"
    / "headless-terminal"
    / "qualification"
    / "reference.py"
)


def compiled_task():
    return load_terminal_task(TASK_ID)


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _correct_observation(context: dict) -> dict:
    expected_file = context["expected_file"]
    expected_http = context["expected_http"]
    return {
        "driver_exit": 0,
        "driver_stdout_base64": "",
        "driver_stderr_base64": "",
        "file_exists": expected_file is not None,
        "file_too_large": False,
        "file_base64": _encoded((expected_file or "").encode()),
        "http_attempted": expected_http is not None,
        "http_status": 200 if expected_http is not None else 0,
        "http_too_large": False,
        "http_body_base64": _encoded((expected_http or "").encode()),
        "http_error": "",
    }


def test_headless_terminal_row_is_bounded_split_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    candidate = task.verification.candidate
    assert candidate.max_total_files == 257
    assert candidate.max_total_bytes == 8_454_144
    assert [(entry.id, entry.path) for entry in candidate.files] == [
        ("implementation", "/app/headless_terminal.py"),
        ("dependencies", "/app/headless_terminal_dependencies"),
    ]
    assert [type(check) for check in task.verification.checks] == [ProtocolCheck]
    protocol = task.verification.checks[0]
    assert protocol.challenge.max_cases == 6
    assert protocol.protocol == "securebench.headless-terminal/v1"
    assert not protocol.trusted_helpers
    assert not protocol.output_artifacts
    assert "headless_terminal_dependencies" in task.input["instructions"]

    adapter_files = {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert adapter_files == {"adapter.py", "adapter.yaml", "driver.py"}


def test_public_adapter_and_driver_contain_no_oracle_expectations():
    public_text = "\n".join(
        (ADAPTER / name).read_text() for name in ("adapter.py", "driver.py")
    )

    assert "securebench_" not in public_text
    assert "expected" not in public_text
    assert "verdict" not in public_text
    assert "passed" not in public_text


def test_oracle_builds_seeded_cases_for_every_public_behavior():
    oracle_module = load_module(ORACLE, "headless_terminal_oracle_cases")
    first = oracle_module.build_cases("first-seed")
    second = oracle_module.build_cases("second-seed")

    assert len(first) == 6
    assert first != second
    assert len({item["challenge"]["file_path"] for item in first}) == 6
    assert sum(item["context"]["expected_file"] is not None for item in first) == 4
    assert sum(item["context"]["expected_http"] is not None for item in first) == 1
    decoded_steps = [
        base64.b64decode(step["keys_base64"])
        for item in first
        for step in item["challenge"]["steps"]
    ]
    assert b"\x03" in decoded_steps
    assert b"vim " in b"".join(decoded_steps)
    assert b"\x1b" in decoded_steps
    assert b":wq" in decoded_steps


def test_case_waits_now_match_upstreams_own_waits_exactly():
    """Regression test for the audit finding that several non-vim cases'
    waits were tighter than upstream's own waits
    (`docs/benchmark-conversions/workaround-audit.md`, "headless-terminal":
    "Waits are tighter than upstream: 5 s -> 1.2 s, 1 s -> 0.7 s and
    2 s -> 0.5 s"). The 2 s -> 0.5 s (vim) case was already restored in an
    earlier correction (see the dossier's "Review correction" section); this
    covers the remaining five non-vim cases against upstream's own
    `tests/test_outputs.py` wait_sec values.

    A too-tight wait can reject a correct implementation whose real
    command-completion time is between the old (too tight) wait and
    upstream's actual wait -- exactly the input upstream accepts that the old
    v2 check rejected.
    """
    oracle_module = load_module(ORACLE, "headless_terminal_oracle_waits")
    cases = oracle_module.build_cases("wait-regression-seed")

    def wait_ms_values(index: int) -> list[int]:
        return [step["wait_ms"] for step in cases[index]["challenge"]["steps"]]

    # test_send_non_interactive_command: send_keystrokes("\n", wait_sec=1)
    assert wait_ms_values(0) == [0, 1_000]
    # test_shell_state_persists_between_commands: both waits are wait_sec=0.5
    assert wait_ms_values(1) == [0, 500, 0, 500]
    # test_send_interactive_command (vim), already matching upstream exactly
    assert wait_ms_values(2) == [0, 2_000, 500, 500, 500, 500, 0, 500]
    # test_cancel_command: both real waits are wait_sec=0.5. The trailing
    # 1.7 s step and the shorter `sleep 2` command are an unrelated,
    # previously reviewed and documented fidelity improvement (observing
    # cancellation after the original delayed command would have completed),
    # not a "wait" with an upstream counterpart, so they are untouched.
    assert wait_ms_values(3) == [0, 500, 500, 1_700]
    # test_startup_files: wait_sec=0.5
    assert wait_ms_values(4) == [0, 500]
    # test_background_commands: wait_sec=5
    assert wait_ms_values(5) == [0, 5_000]

    # A concrete, plausible correct implementation: its real command
    # completion time for the non-interactive case is 850 ms (independent of
    # what the driver asks it to wait). The previous, too-tight 700 ms v2
    # wait would have rejected it (its file write had not yet been observed
    # by the time the Adapter read the file); upstream's own 1000 ms wait --
    # now restored here -- accepts it.
    old_too_tight_wait_ms = 700
    plausible_real_completion_ms = 850
    new_wait_ms = wait_ms_values(0)[-1]
    assert old_too_tight_wait_ms < plausible_real_completion_ms <= new_wait_ms


def test_oracle_accepts_independent_correct_evidence():
    oracle_module = load_module(ORACLE, "headless_terminal_oracle_pass")
    oracle = oracle_module.HeadlessTerminalOracle()
    oracle.initialize("qualification")

    index = 0
    while (case := oracle.next_case())["type"] == "case":
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": f"evaluation_{index}",
                "observation": _correct_observation(case["case_context"]),
            },
        )
        index += 1

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is True
    assert verdict["check_outcomes"] == {"terminal_behavior": True}


@pytest.mark.parametrize(
    "attack",
    [
        "driver_failure",
        "wrong_file",
        "created_cancel_file",
        "wrong_http",
        "forged_claim",
        "malformed_observation",
        "reused_evaluation",
    ],
)
def test_oracle_rejects_semantic_mutants_and_claims(attack):
    oracle_module = load_module(ORACLE, f"headless_terminal_oracle_{attack}")
    oracle = oracle_module.HeadlessTerminalOracle()
    oracle.initialize("mutant")

    index = 0
    while (case := oracle.next_case())["type"] == "case":
        observation = _correct_observation(case["case_context"])
        if attack == "driver_failure" and index == 0:
            observation["driver_exit"] = 1
        elif attack == "wrong_file" and index == 0:
            observation["file_base64"] = _encoded(b'{"verdict":"passed"}')
        elif attack == "created_cancel_file" and index == 3:
            observation["file_exists"] = True
        elif attack == "wrong_http" and index == 5:
            observation["http_status"] = 404
        elif attack == "forged_claim" and index == 0:
            observation["driver_stdout_base64"] = _encoded(b'{"score":1}')
            observation["file_base64"] = _encoded(b"wrong")
        elif attack == "malformed_observation" and index == 0:
            observation["file_base64"] = "not-base64"
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": (
                    "evaluation_0"
                    if attack == "reused_evaluation"
                    else f"evaluation_{index}"
                ),
                "observation": observation,
            },
        )
        index += 1

    assert oracle.verdict()["verdict"]["passed"] is False


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_dependency_bundle_rejects_malicious_shapes(tmp_path, attack):
    assert_file_bundle_capture_rejected(
        compiled_task(),
        tmp_path,
        attack=attack,
        target_id="dependencies",
    )


def _workspace(tmp_path: Path, source: bytes) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "headless_terminal.py").write_bytes(source)
    (workspace / "headless_terminal_dependencies").mkdir()
    return workspace


@DOCKER_INTEGRATION
def test_reference_passes_six_fresh_pinned_evaluations(tmp_path):
    result, _, _ = verify_workspace(
        compiled_task(),
        _workspace(tmp_path, REFERENCE.read_bytes()),
        tmp_path / "store",
        run_seed="headless-terminal-reference",
    )

    assert result.status == "passed", result
    behavior = result.checks[0]
    assert behavior.cases == 6
    assert len(set(behavior.evidence_digests)) == 6


PTY_FORK_REFERENCE = b'''from base_terminal import BaseTerminal
import os
import pty
import time
from pathlib import Path


class HeadlessTerminal(BaseTerminal):
    """A non-daemonizing, pexpect/ptyprocess-style implementation.

    Unlike the tmux-backed qualification reference above, this owns its pty
    and child bash directly in this same process (`pty.fork()`, like
    `pexpect`/`ptyprocess` do), instead of handing off to an independently
    daemonized `tmux` server. Before the Adapter fix, killing this driver's
    process group -- or even letting it exit on its own -- before observing
    bounded evidence would tear down the pty and its foreground session,
    losing the background service the Candidate started
    (docs/benchmark-conversions/workaround-audit.md: "pexpect or
    ptyprocess-style implementations send SIGHUP to the background server and
    fail v2, even though they pass upstream"). It is a valid, upstream-passing
    implementation and must still pass here.
    """

    def __init__(self):
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp(
                "bash",
                ["bash", "--noprofile", "--rcfile", str(Path.home() / ".bashrc"), "-i"],
            )
        self._pid = pid
        self._fd = fd

    def send_keystrokes(self, keystrokes: str, wait_sec: float = 0.0) -> None:
        os.write(self._fd, keystrokes.encode())
        time.sleep(wait_sec)
'''


@DOCKER_INTEGRATION
def test_non_daemonizing_pty_reference_passes_six_fresh_pinned_evaluations(tmp_path):
    """A pexpect/ptyprocess-style positive control for the HTTP-ordering fix.

    Regression coverage for the audit finding that the Adapter used to probe
    the file/HTTP evidence only after the driver's terminal was already torn
    down, which rejected valid non-tmux implementations that upstream itself
    accepts.
    """
    result, _, _ = verify_workspace(
        compiled_task(),
        _workspace(tmp_path, PTY_FORK_REFERENCE),
        tmp_path / "store",
        run_seed="headless-terminal-pty-fork",
    )

    assert result.status == "passed", result
    behavior = result.checks[0]
    assert behavior.cases == 6
    assert len(set(behavior.evidence_digests)) == 6


@DOCKER_INTEGRATION
def test_semantic_and_malicious_mutants_fail_real_evaluations(tmp_path):
    ignored_interrupt = REFERENCE.read_text().replace(
        "    def send_keystrokes(self, keystrokes: str, wait_sec: float = 0.0) -> None:\n"
        "        subprocess.run(\n",
        "    def send_keystrokes(self, keystrokes: str, wait_sec: float = 0.0) -> None:\n"
        "        if keystrokes == \"\\x03\":\n"
        "            time.sleep(wait_sec)\n"
        "            return\n"
        "        subprocess.run(\n",
    )
    assert ignored_interrupt != REFERENCE.read_text()
    mutants = {
        "stateless": b'''from base_terminal import BaseTerminal\nimport subprocess,time\nclass HeadlessTerminal(BaseTerminal):\n def send_keystrokes(self,keystrokes,wait_sec=0):\n  subprocess.run(["bash","-c",keystrokes],check=False);time.sleep(wait_sec)\n''',
        "forged-output": b'''from base_terminal import BaseTerminal\nclass HeadlessTerminal(BaseTerminal):\n def __init__(self): print('{"verdict":"passed","score":1}')\n def send_keystrokes(self,keystrokes,wait_sec=0): pass\n''',
        "output-flood": b'''from base_terminal import BaseTerminal\nprint("x"*9000)\nclass HeadlessTerminal(BaseTerminal):\n def send_keystrokes(self,keystrokes,wait_sec=0): pass\n''',
        "ignored-interrupt": ignored_interrupt.encode(),
        # Plausible almost-correct bug: modifier keys are dispatched through a
        # fixed name table (matching the two documented ones, Control-C and
        # Control-D) and any other printable text or text containing a
        # newline is forwarded literally, but an unmapped control byte such
        # as Escape has no table entry and is silently dropped instead of
        # being forwarded. This still passes the non-interactive, persistent,
        # startup, cancel, and background-service cases (all rely only on
        # `\n` and the two named keys) but breaks the restored vim case: vim
        # never leaves insert mode, so `:wq` and the trailing `\n` are typed
        # into the buffer instead of executed, and the file is never saved.
        "vim-escape-dropped": '''from base_terminal import BaseTerminal
import subprocess
import time
import uuid
from pathlib import Path


class HeadlessTerminal(BaseTerminal):
    _NAMED_KEYS = {"\\x03": "C-c", "\\x04": "C-d"}

    def __init__(self):
        self._session_id = str(uuid.uuid4())
        subprocess.run(
            [
                "tmux", "new-session", "-d", "-s", self._session_id, "bash",
                "--noprofile", "--rcfile", str(Path.home() / ".bashrc"), "-i",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def send_keystrokes(self, keystrokes: str, wait_sec: float = 0.0) -> None:
        if keystrokes in self._NAMED_KEYS:
            subprocess.run(
                ["tmux", "send-keys", "-t", self._session_id, self._NAMED_KEYS[keystrokes]],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif keystrokes.isprintable() or "\\n" in keystrokes:
            subprocess.run(
                ["tmux", "send-keys", "-l", "-t", self._session_id, keystrokes],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        time.sleep(wait_sec)
'''.encode(),
    }
    for name, source in mutants.items():
        root = tmp_path / name
        root.mkdir()
        result, _, _ = verify_workspace(
            compiled_task(),
            _workspace(root, source),
            root / "store",
            run_seed=f"headless-terminal-{name}",
        )

        assert result.status == "failed", result
        assert result.infrastructure_error is None, result
