import pytest
import subprocess

from securebench.sandboxes import TIMEOUT_EXIT_CODE, HostSandbox


def test_host_sandbox_run_reports_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="partial out", stderr="partial err")

    monkeypatch.setattr("subprocess.run", fake_run)
    sandbox = HostSandbox(root=tmp_path)

    result = sandbox.run(["sleep", "10"], timeout=2)

    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.timed_out is True
    assert result.timeout_seconds == 2
    assert result.stdout == "partial out"
    assert result.stderr == "partial err"


def test_host_sandbox_read_file_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("host secret")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "candidate.txt").symlink_to(outside)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.read_file("candidate.txt")


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
    (root / "candidate.txt").symlink_to(outside)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.write_file("candidate.txt", "modified")

    assert outside.read_text() == "original"


def test_host_sandbox_write_file_rejects_symlink_parent_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.write_file("linked/candidate.txt", "modified")

    assert not (outside / "candidate.txt").exists()


def test_host_sandbox_write_file_rejects_symlink_to_inside_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    real = root / "real.txt"
    real.write_text("original")
    (root / "candidate.txt").symlink_to(real)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="write through symlink"):
        sandbox.write_file("candidate.txt", "modified")

    assert real.read_text() == "original"


def test_host_sandbox_write_file_rejects_symlink_parent_inside_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target_dir = root / "target"
    target_dir.mkdir()
    (root / "linked").symlink_to(target_dir, target_is_directory=True)
    sandbox = HostSandbox(root=root)

    with pytest.raises(ValueError, match="write through symlink"):
        sandbox.write_file("linked/candidate.txt", "modified")

    assert not (target_dir / "candidate.txt").exists()
