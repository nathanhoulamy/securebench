from pathlib import Path


def test_network_probe_marker_absent():
    assert not Path("network_success").exists()
