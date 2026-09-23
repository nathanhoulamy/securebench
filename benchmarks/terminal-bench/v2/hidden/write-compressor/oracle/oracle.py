"""Host-only Oracle for the write-compressor artifact conversion.

The source verifier recompiles the public ``decomp.c`` and runs
``cat data.comp | ./decomp2``, comparing stdout with ``data.txt`` and requiring
``data.comp`` to be at most 2500 bytes.

This Oracle does not compile or execute anything. It reimplements the public
range-decoder format in memory-safe Python and compares the decoded bytes with
its own trusted copy of ``data.txt``. Every place where the C program would run
off the end of a buffer becomes an explicit rejection, so a hostile stream
fails as candidate evidence rather than as a crash.

Faithfulness notes, all mirroring ``decomp.c``:

* ``gc()`` casts ``getchar()`` to ``unsigned char``, so reads past end-of-input
  yield 255 (from EOF's -1). That is modelled exactly.
* ``split`` is computed with C truncating division on non-negative operands,
  which matches Python floor division here.
* ``-~x`` is ``x + 1``.
* ``printf("%s", buf)`` stops at the first NUL, so the decoded output is
  truncated there.
"""

from __future__ import annotations

import json
import sys
from typing import Any


RADIX = 255
BUFFER_BYTES = 10000
CONTEXT_SLOTS = 1000000
OFF1 = 5
OFF2 = 2
INTOFF = 9
LITSIZE = 4
MAX_COMPRESSED_BYTES = 2500

# Bounds with no counterpart in the C program. They exist only so a hostile
# stream terminates instead of looping; a stream that needs more than these is
# rejected rather than silently truncated.
MAX_UNARY_BITS = 64
MAX_INPUT_READS = 1 << 20


class DecodeError(Exception):
    """The candidate stream is not decodable under the public format."""


class RangeDecoder:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._position = 0
        self._reads = 0
        self.counts = [0] * (CONTEXT_SLOTS * 2)
        self.fraction = 0
        self.range = 1

    def _next_byte(self) -> int:
        self._reads += 1
        if self._reads > MAX_INPUT_READS:
            raise DecodeError("stream_read_bound_exceeded")
        if self._position >= len(self._data):
            # getchar() returns EOF (-1); (unsigned char)(-1) == 255.
            return 255
        value = self._data[self._position]
        self._position += 1
        return value

    def get_bit(self, context: int) -> int:
        if context < 0 or context * 2 + 1 >= len(self.counts):
            raise DecodeError("context_out_of_range")
        if self.range < RADIX:
            self.range *= RADIX
            self.fraction *= RADIX
            self.fraction += self._next_byte() - 1

        zeros = self.counts[context * 2]
        ones = self.counts[context * 2 + 1]
        split = (self.range * (zeros + 1)) // (zeros + ones + 2)
        bit = 1 if self.fraction >= split else 0
        if bit:
            self.fraction -= split
            self.range = self.range - split
        else:
            self.range = split
        if self.range <= 0:
            raise DecodeError("range_collapsed")
        self.counts[context * 2 + bit] += 1
        return bit

    def get_integer(self, width: int, context: int) -> int:
        subtract = 1 << width
        result = 1
        context *= 99
        length = 0
        while True:
            width += 1
            if self.get_bit(width + context):
                break
            length += 1
            if length > MAX_UNARY_BITS:
                raise DecodeError("unary_prefix_too_long")
        width -= 1
        for _ in range(width):
            result = result * 2 | self.get_bit(context)
        return result - subtract


def decompress(data: bytes) -> bytes:
    decoder = RangeDecoder(data)
    tokens = decoder.get_integer(INTOFF, 0)
    if tokens < 0 or tokens > BUFFER_BYTES:
        raise DecodeError("token_count_out_of_range")

    buffer = bytearray(BUFFER_BYTES)
    written = 0
    for _ in range(tokens):
        if decoder.get_bit(1):
            distance = decoder.get_integer(OFF1, 2) + 1
            length = decoder.get_integer(OFF2, 3) + 1
            source = written - distance
            if source < 0:
                raise DecodeError("match_before_buffer_start")
            if length < 1:
                raise DecodeError("match_length_out_of_range")
            if written + length > BUFFER_BYTES:
                raise DecodeError("buffer_overflow")
            # Byte-at-a-time copy: overlapping matches are intentional.
            for _ in range(length):
                buffer[written] = buffer[source]
                written += 1
                source += 1
        else:
            sign = 1 - 2 * decoder.get_bit(8)
            magnitude = decoder.get_integer(LITSIZE, 9)
            if written >= BUFFER_BYTES:
                raise DecodeError("buffer_overflow")
            buffer[written] = (sign * magnitude) & 0xFF
            written += 1

    decoded = bytes(buffer[:written])
    terminator = decoded.find(b"\x00")
    if terminator >= 0:
        decoded = decoded[:terminator]
    return decoded


class WriteCompressorOracle:
    def __init__(self, expected: bytes) -> None:
        self.expected = expected
        self.evaluated = False
        self.passed = False
        self.failure = "not_evaluated"

    def evaluate(self, evidence: dict[str, Any]) -> None:
        self.evaluated = True
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            self.failure = (
                str(error.get("code", "artifact_rejected"))
                if isinstance(error, dict)
                else "artifact_rejected"
            )
            return
        value = evidence.get("parsed_value")
        if not isinstance(value, dict):
            self.failure = "invalid_artifact"
            return
        encoded = value.get("bytes_base64")
        if not isinstance(encoded, str):
            self.failure = "invalid_artifact"
            return
        import base64

        try:
            data = base64.b64decode(encoded, validate=True)
        except Exception:
            self.failure = "invalid_artifact"
            return

        if len(data) > MAX_COMPRESSED_BYTES:
            self.failure = "compressed_too_large"
            return
        try:
            decoded = decompress(data)
        except DecodeError as exc:
            self.failure = str(exc)
            return
        if decoded != self.expected:
            self.failure = "decompressed_output_mismatch"
            return
        self.passed = True
        self.failure = ""

    def verdict(self) -> dict[str, Any]:
        passed = self.evaluated and self.passed
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {"compressed_artifact": passed},
                "public_diagnostics": {
                    "message": (
                        "data.comp decompresses to data.txt within the size cap"
                        if passed
                        else "data.comp is oversized, undecodable, or incorrect"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    from pathlib import Path

    expected = (Path(__file__).resolve().parent / "data.txt").read_bytes()
    oracle = WriteCompressorOracle(expected)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                response = {"type": "ack"}
            elif operation == "evaluate_artifact":
                evidence = request.get("evidence")
                if not isinstance(evidence, dict):
                    raise ValueError("artifact evidence required")
                oracle.evaluate(evidence)
                response = {"type": "ack"}
            elif operation == "finalize":
                response = oracle.verdict()
            else:
                raise ValueError("unsupported operation")
        except Exception:
            response = {"type": "error"}
        print(json.dumps(response, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
