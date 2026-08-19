import pytest

from securebench.locking import FileLockError, exclusive_file_lock


def test_exclusive_file_lock_rejects_second_nonblocking_owner(tmp_path):
    path = tmp_path / "run.lock"

    with exclusive_file_lock(path):
        with pytest.raises(FileLockError, match="could not acquire"):
            with exclusive_file_lock(path, blocking=False):
                pass


def test_exclusive_file_lock_does_not_relabel_body_errors(tmp_path):
    with pytest.raises(PermissionError, match="body failure"):
        with exclusive_file_lock(tmp_path / "run.lock"):
            raise PermissionError("body failure")
