from pathlib import Path


def test_candidate_cannot_replace_trusted_test_runner():
    assert not Path("bin/pytest").exists()
