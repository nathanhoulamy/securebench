"""Trusted transport controls; benchmark candidate code only runs in Docker."""
import json
import os
from pathlib import Path
import sys

import pytest

from tests.qualification_support import load_module

MODULE = load_module(Path(__file__).resolve().parents[1] /
    "benchmarks/deep-swe/v2/evaluation_inputs/go-critic-doc-link-checker/adapter/adapter.py",
    "go_critic_adapter")


@pytest.mark.parametrize("program,seconds,message", [
    ("import os,time; os.close(1); os.close(2); time.sleep(10)", 0.2, b"timed out"),
    ("import sys; sys.stdout.write('x'*100000)", 5, b"bound exceeded"),
])
def test_transport_bounds_outputs_and_closed_stream_timeout(tmp_path, program, seconds, message):
    incoming = tmp_path / "input"
    incoming.write_bytes(b"")
    code, output, error = MODULE.run_bounded(
        [sys.executable, "-c", program], stdin_path=incoming,
        env=dict(os.environ), seconds=seconds, cwd=tmp_path)
    assert code is None and not output and message in error


def test_transport_rejects_ambiguous_json():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"status":"candidate_error","status":"observed"}',
                   object_pairs_hook=MODULE.unique_object)
