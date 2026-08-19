import subprocess
import sys

import pytest

from securebench.sandboxes import TIMEOUT_EXIT_CODE, HostSandbox
from securebench.sandboxes.base import MAX_COMMAND_OUTPUT_BYTES


def test_host_sandbox_run_reports_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="partial out", stderr="partial err")

    monkeypatch.setattr("securebench.sandboxes.host.run_bounded_subprocess", fake_run)
    sandbox = HostSandbox(root=tmp_path)

    result = sandbox.run(["sleep", "10"], timeout=2)

    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.timed_out is True
    assert result.timeout_seconds == 2
    assert result.stdout == "partial out"
    assert result.stderr == "partial err"


def test_host_sandbox_forwards_stdin(tmp_path):
    sandbox = HostSandbox(root=tmp_path)

    result = sandbox.run(["sh", "-c", "cat"], stdin="trusted patch")

    assert result.stdout == "trusted patch"


def test_host_sandbox_normalizes_output_when_stdin_is_bytes(tmp_path):
    sandbox = HostSandbox(root=tmp_path)

    result = sandbox.run(["sh", "-c", "cat"], stdin=b"binary patch")

    assert result.stdout == "binary patch"


def test_host_sandbox_bounds_stdout_and_stderr(tmp_path):
    sandbox = HostSandbox(root=tmp_path)
    size = MAX_COMMAND_OUTPUT_BYTES * 2

    result = sandbox.run(
        [
            sys.executable,
            "-c",
            f"import os; os.write(1, b'x' * {size}); os.write(2, b'y' * {size})",
        ]
    )

    assert len(result.stdout.encode()) <= MAX_COMMAND_OUTPUT_BYTES
    assert len(result.stderr.encode()) <= MAX_COMMAND_OUTPUT_BYTES
    assert result.stdout.endswith("[securebench: output truncated]\n")
    assert result.stderr.endswith("[securebench: output truncated]\n")
    assert result.stdout_bytes == size
    assert result.stderr_bytes == size
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert result.stdout_valid_utf8 is True
    assert result.stderr_valid_utf8 is True


def test_host_sandbox_preserves_invalid_utf8_metadata(tmp_path):
    sandbox = HostSandbox(root=tmp_path)

    result = sandbox.run(
        [sys.executable, "-c", "import os; os.write(1, b'\\xff')"]
    )

    assert result.stdout == "�"
    assert result.stdout_bytes == 1
    assert result.stdout_truncated is False
    assert result.stdout_valid_utf8 is False


@pytest.mark.parametrize("timeout", [float("inf"), 10**400])
def test_host_sandbox_rejects_unrepresentable_timeout_before_starting_process(
    tmp_path, timeout
):
    sandbox = HostSandbox(root=tmp_path)

    with pytest.raises(ValueError, match="finite positive number"):
        sandbox.run([sys.executable, "-c", "raise SystemExit(0)"], timeout=timeout)


def test_host_sandbox_read_file_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("host secret")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "workspace-output.txt").symlink_to(outside)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.read_file("workspace-output.txt")


def test_host_sandbox_extract_file_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"host secret")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "candidate.bin").symlink_to(outside)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.extract_file("candidate.bin")


def test_host_sandbox_write_file_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("original")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "workspace-output.txt").symlink_to(outside)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.write_file("workspace-output.txt", "modified")

    assert outside.read_text() == "original"


def test_host_sandbox_write_file_rejects_symlink_parent_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.write_file("linked/workspace-output.txt", "modified")

    assert not (outside / "workspace-output.txt").exists()


def test_host_sandbox_write_file_rejects_symlink_to_inside_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    real = root / "real.txt"
    real.write_text("original")
    (root / "workspace-output.txt").symlink_to(real)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="write through symlink"):
        sandbox.write_file("workspace-output.txt", "modified")

    assert real.read_text() == "original"


def test_host_sandbox_write_file_rejects_symlink_parent_inside_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target_dir = root / "target"
    target_dir.mkdir()
    (root / "linked").symlink_to(target_dir, target_is_directory=True)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="write through symlink"):
        sandbox.write_file("linked/workspace-output.txt", "modified")

    assert not (target_dir / "workspace-output.txt").exists()
