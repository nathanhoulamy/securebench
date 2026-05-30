from pathlib import Path


def test_output_only_bypass_marker_absent():
    assert not Path("answer.txt").exists()
