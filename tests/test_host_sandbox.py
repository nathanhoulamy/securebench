import pytest

from securebench.sandboxes import HostSandbox


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
