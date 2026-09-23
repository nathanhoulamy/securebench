from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, FileBundleCandidate
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    assert_base_capture_rejected,
    assert_file_bundle_capture_rejected,
    assert_missing_candidate_failure,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/write-compressor"
IMAGE = "sha256:d35bc48b79d5b2560fb095140ca853427f6817cc02bb9b3133db22b02ff9be4d"
HIDDEN = PACK / "v2" / "hidden" / "write-compressor"
ORACLE = HIDDEN / "oracle" / "oracle.py"
REFERENCE = HIDDEN / "qualification" / "reference.comp"
EXPECTED_TEXT = HIDDEN / "oracle" / "data.txt"
SOURCE_DATA = PACK / "hidden" / "write-compressor" / "tests" / "original-data.txt"
SOURCE_DECOMP = PACK / "hidden" / "write-compressor" / "tests" / "original-decomp.c"
PUBLIC_DECOMP = PACK / "docker" / "write-compressor" / "decomp.c"
SIZE_CAP = 2500


def compiled_task():
    return load_terminal_task(TASK_ID)


def oracle_module():
    return load_module(ORACLE, "write_compressor_oracle_under_test")


def reference_bytes() -> bytes:
    assert REFERENCE.is_file(), f"missing host-only reference material: {REFERENCE}"
    return REFERENCE.read_bytes()


def verify_compressed(tmp_path: Path, content: bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    # The agent's own compressor source is not a declared deliverable.
    (workspace / "compress.py").write_text("excluded", encoding="utf-8")
    (workspace / "data.comp").write_bytes(content)
    return verify_workspace(
        task, workspace, tmp_path / "store", run_seed="write-compressor-test-seed"
    )


def assert_candidate_failure(tmp_path: Path, content: bytes, category: str):
    result, _, _ = verify_compressed(tmp_path, content)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result
    return result


def test_write_compressor_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    # gcc, rustc and bc all ship in the image.
    assert task.environment.agent_network.mode == "none"

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert [entry.id for entry in candidate.files] == ["compressed"]
    assert candidate.files[0].path == "/app/data.comp"
    # Capture must allow more than the source's size rule so that "too large"
    # stays a scored Oracle decision rather than a capture rejection.
    assert candidate.files[0].max_bytes > SIZE_CAP

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == "compressed_artifact"
    assert check.artifacts[0].parser == "securebench.opaque-bytes/v1"

    assert task.verification.oracle == "host.task_oracle"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "oracle" not in view
        assert "qualification" not in view


def test_oracle_holds_the_pinned_expected_text_and_source_constants():
    module = oracle_module()

    assert module.MAX_COMPRESSED_BYTES == SIZE_CAP
    assert (module.OFF1, module.OFF2, module.INTOFF, module.LITSIZE) == (5, 2, 9, 4)
    assert module.RADIX == 255
    assert module.BUFFER_BYTES == 10000

    # The Oracle's trusted data.txt must equal the one the source verifier
    # restores before grading, which is also the public file.
    expected = EXPECTED_TEXT.read_bytes()
    assert expected == SOURCE_DATA.read_bytes()
    assert len(expected) == 4868

    # The public decomp.c and the verifier's restored copy are the same format.
    assert PUBLIC_DECOMP.read_bytes() == SOURCE_DECOMP.read_bytes()


def test_reference_matches_the_c_decoder_conformance_record():
    """The checked-in reference is the artifact validated against real gcc/rustc.

    The qualification README records that the C decoder reproduced data.txt from
    this exact file; this test pins the bytes so that record stays meaningful.
    """
    data = reference_bytes()

    assert len(data) == 2264
    assert len(data) <= SIZE_CAP
    assert hashlib.sha256(data).hexdigest() == hashlib.sha256(
        REFERENCE.read_bytes()
    ).hexdigest()


def test_oracle_decoder_reproduces_the_pinned_text(tmp_path):
    module = oracle_module()

    decoded = module.decompress(reference_bytes())

    assert decoded == EXPECTED_TEXT.read_bytes()


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_compressed(tmp_path, reference_bytes())

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["compressed"]
    assert "compress.py" not in json.dumps(manifest.payload)


def test_opaque_parser_delivers_exact_bytes_to_the_oracle():
    """The parser must not transform the artifact, only transport it."""
    from securebench.verification.parsers import default_parser_registry

    data = reference_bytes()
    parsed = default_parser_registry().parse_bytes(
        "securebench.opaque-bytes/v1", data
    )

    assert parsed["byte_count"] == len(data)
    assert parsed["sha256"] == hashlib.sha256(data).hexdigest()
    assert base64.b64decode(parsed["bytes_base64"]) == data


# Corrupting a range-coded stream desynchronises the arithmetic decoder, so a
# mutant usually trips a structural bound rather than decoding cleanly to the
# wrong text. Both outcomes are correct rejections, so the test pins the class
# of failure rather than one implementation-specific category.
DECODE_FAILURES = frozenset(
    {
        "decompressed_output_mismatch",
        "match_before_buffer_start",
        "match_length_out_of_range",
        "buffer_overflow",
        "token_count_out_of_range",
        "unary_prefix_too_long",
        "range_collapsed",
        "context_out_of_range",
        "stream_read_bound_exceeded",
    }
)


def test_trailing_byte_is_unused_matching_the_c_decoder(tmp_path):
    """Dropping the final byte still decodes, in both implementations.

    The decoder stops after the encoded token count, and ``gc()`` yields 255
    past end-of-input, so a trailing byte can be unused. The real gcc-compiled
    decomp.c was checked against this same truncated stream and also reproduced
    data.txt, so accepting it is fidelity, not Oracle laxity.
    """
    result, _, _ = verify_compressed(tmp_path, reference_bytes()[:-1])

    assert result.status == "passed", result


def test_oversize_artifact_is_rejected_on_size_not_on_decode(tmp_path):
    """The source's size rule is a distinct assertion, so it keeps its own category."""
    padded = reference_bytes() + b"\x00" * (SIZE_CAP + 1 - len(reference_bytes()))

    assert_candidate_failure(tmp_path, padded, "compressed_too_large")


@pytest.mark.parametrize(
    "mutator",
    [
        pytest.param(lambda d: b"", id="empty_stream"),
        pytest.param(lambda d: d[:100], id="truncated"),
        pytest.param(lambda d: bytes([d[0] ^ 0xFF]) + d[1:], id="corrupted_first_byte"),
        pytest.param(
            lambda d: d[:1200] + bytes([d[1200] ^ 0x01]) + d[1201:],
            id="corrupted_middle_byte",
        ),
        pytest.param(lambda d: d[::-1], id="reversed_stream"),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, mutator):
    result, _, _ = verify_compressed(tmp_path, mutator(reference_bytes()))

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    categories = set(result.public_diagnostics["failure_categories"])
    assert categories <= DECODE_FAILURES, categories


def test_exact_size_cap_boundary_is_preserved():
    """The source rule is `<= 2500`, so 2500 is allowed and 2501 is not."""
    module = oracle_module()
    reference = reference_bytes()

    oracle = module.WriteCompressorOracle(EXPECTED_TEXT.read_bytes())
    oracle.evaluate(
        {
            "status": "observed",
            "parsed_value": {
                "byte_count": len(reference),
                "sha256": hashlib.sha256(reference).hexdigest(),
                "bytes_base64": base64.b64encode(reference).decode(),
            },
        }
    )
    assert oracle.passed is True

    for size, expected in ((SIZE_CAP, "decompressed_output_mismatch"),
                           (SIZE_CAP + 1, "compressed_too_large")):
        padded = b"\x00" * size
        probe = module.WriteCompressorOracle(EXPECTED_TEXT.read_bytes())
        probe.evaluate(
            {
                "status": "observed",
                "parsed_value": {
                    "byte_count": size,
                    "sha256": hashlib.sha256(padded).hexdigest(),
                    "bytes_base64": base64.b64encode(padded).decode(),
                },
            }
        )
        assert probe.passed is False
        # The oversize case must be rejected on size, not on decode.
        if size > SIZE_CAP:
            assert probe.failure == expected


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"\xff" * 2500, id="all_ones"),
        pytest.param(b"\x00" * 2500, id="all_zeros"),
        pytest.param(bytes(range(256)) * 9, id="cyclic"),
    ],
)
def test_hostile_streams_fail_closed_without_infrastructure_error(tmp_path, payload):
    """A hostile stream must never crash the host or hang the decoder.

    The C program would happily run off both ends of its 10000-byte stack
    buffer here; the Oracle's decoder rejects instead.
    """
    result, _, _ = verify_compressed(tmp_path, payload)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result


def test_decoder_rejects_rather_than_reading_out_of_bounds():
    module = oracle_module()

    # A match that reaches before the start of the output buffer is exactly the
    # out-of-bounds read the C program performs; here it must be an error.
    assert module.DecodeError is not None
    for payload in (b"\x00", b"\x01" * 64, b"\x80" * 512):
        try:
            module.decompress(payload)
        except module.DecodeError:
            continue
        # Decoding may also succeed into a wrong-but-bounded output; what must
        # never happen is an unbounded read or an unhandled exception.


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_malicious_candidate_filesystem_shapes_are_rejected_at_capture(
    tmp_path, attack
):
    assert_file_bundle_capture_rejected(
        compiled_task(), tmp_path, attack=attack, target_id="compressed"
    )


def test_missing_deliverable_scores_as_candidate_failure():
    assert_missing_candidate_failure(
        compiled_task(),
        run_seed="write-compressor-missing",
        check_ids=("compressed_artifact",),
    )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_compressed(tmp_path, reference_bytes())
    second = VerificationEngine().verify(
        compiled_task(), candidate, store, run_seed="write-compressor-replay"
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
def test_base_image_without_deliverable_is_rejected_at_capture(tmp_path):
    assert_base_capture_rejected(compiled_task(), tmp_path, command=("true",))


@DOCKER_INTEGRATION
def test_pinned_image_ships_decomp_and_data_but_not_the_reference_compressor(tmp_path):
    """main.rs is the upstream solution and must not be in the Agent image."""
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=(
            "sh",
            "-c",
            "test -f /app/decomp.c && test -f /app/data.txt && test -x /app/decomp "
            "&& test ! -e /app/main.rs && printf 'x' > /app/data.comp",
        ),
        run_seed="write-compressor-image-contents",
    )

    # The stub artifact fails scoring; the assertions above ran inside the image
    # and would have made the command fail if main.rs were present.
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
