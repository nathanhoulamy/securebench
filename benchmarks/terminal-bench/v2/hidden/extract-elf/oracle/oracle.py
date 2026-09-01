"""Host-only Oracle for bounded ELF memory-extraction behavior."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import random
import struct
import sys
from typing import Any

from securebench.data_formats import strict_json_loads
from securebench.verification.json_data import json_digest


CHECK_ID = "extractor_behavior"
MAX_CASE_BYTES = 131_072
MAX_ELF_BYTES = 65_536
MAX_OUTPUT_FIELDS = 8_192
CASE_DIGESTS = {
    "arguments": "b43fdc21e9103d6e1d924a312f50d1c2edcb3a148896e35da46a8cac659aa80c",
    "functions": "2fee5485a493ca00cd067dc0da1c957fc3250af8cd1fd2883d4b9724b04c3c40",
    "hello": "90db2f0afd5b3ff4d719b829b322b2558c67e79523aeb4c057e811522ccc7c05",
    "sections": "84abf6e1d1da385bbd6b37e138d0794da18354ad1b874f9275247b0510b0b3a5",
}


def _unpack(data: bytes, offset: int, fmt: str) -> tuple[int, ...]:
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ValueError("ELF field is out of bounds")
    return struct.unpack_from(fmt, data, offset)


def _section_bytes(data: bytes, section: dict[str, int]) -> bytes:
    offset = section["offset"]
    size = section["size"]
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError("ELF section is out of bounds")
    return data[offset : offset + size]


def _section_name(table: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(table):
        return ""
    end = table.find(b"\0", offset)
    if end < 0:
        end = len(table)
    try:
        return table[offset:end].decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ""


def extract_reference_values(data: bytes) -> dict[str, int]:
    """Independently reproduce the row's documented ELF word semantics."""

    if len(data) > MAX_ELF_BYTES or len(data) < 52 or data[:4] != b"\x7fELF":
        raise ValueError("invalid bounded ELF")
    elf_class = data[4]
    elf_data = data[5]
    if elf_class not in {1, 2} or elf_data not in {1, 2}:
        raise ValueError("unsupported ELF identity")
    endian = "<" if elf_data == 1 else ">"
    if elf_class == 2:
        if len(data) < 64:
            raise ValueError("truncated ELF64 header")
        section_offset = _unpack(data, 40, endian + "Q")[0]
        section_entry_size = _unpack(data, 58, endian + "H")[0]
        section_count = _unpack(data, 60, endian + "H")[0]
        string_table_index = _unpack(data, 62, endian + "H")[0]
        minimum_entry_size = 64
    else:
        section_offset = _unpack(data, 32, endian + "I")[0]
        section_entry_size = _unpack(data, 46, endian + "H")[0]
        section_count = _unpack(data, 48, endian + "H")[0]
        string_table_index = _unpack(data, 50, endian + "H")[0]
        minimum_entry_size = 40
    if (
        section_entry_size < minimum_entry_size
        or not 1 <= section_count <= 256
        or string_table_index >= section_count
        or section_offset + section_entry_size * section_count > len(data)
    ):
        raise ValueError("invalid ELF section table")

    sections: list[dict[str, int]] = []
    for index in range(section_count):
        offset = section_offset + index * section_entry_size
        name = _unpack(data, offset, endian + "I")[0]
        if elf_class == 2:
            address = _unpack(data, offset + 16, endian + "Q")[0]
            file_offset = _unpack(data, offset + 24, endian + "Q")[0]
            size = _unpack(data, offset + 32, endian + "Q")[0]
        else:
            address = _unpack(data, offset + 12, endian + "I")[0]
            file_offset = _unpack(data, offset + 16, endian + "I")[0]
            size = _unpack(data, offset + 20, endian + "I")[0]
        if address > (1 << 53) - 1:
            raise ValueError("ELF address exceeds JavaScript integer precision")
        section = {
            "name": name,
            "address": address,
            "offset": file_offset,
            "size": size,
        }
        _section_bytes(data, section)
        sections.append(section)

    names = _section_bytes(data, sections[string_table_index])
    selected: dict[str, dict[str, int]] = {}
    for section in sections:
        name = _section_name(names, section["name"])
        if name in {".text", ".data", ".rodata"}:
            selected[name] = section

    expected: dict[str, int] = {}
    for name in (".text", ".data", ".rodata"):
        section = selected.get(name)
        if section is None:
            continue
        content = _section_bytes(data, section)
        for offset in range(0, len(content) - 3, 4):
            address = section["address"] + offset
            if address > (1 << 53) - 1:
                raise ValueError("ELF word address exceeds JavaScript integer precision")
            expected[str(address)] = int.from_bytes(
                content[offset : offset + 4], "little", signed=False
            )
    if not expected or len(expected) > MAX_OUTPUT_FIELDS:
        raise ValueError("ELF reference mapping is empty or too large")
    return expected


def _load_cases() -> list[dict[str, Any]]:
    directory = Path(__file__).resolve().parent / "cases"
    cases: list[dict[str, Any]] = []
    for case_id, expected_digest in CASE_DIGESTS.items():
        content = (directory / f"{case_id}.elf").read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_digest or len(content) > MAX_ELF_BYTES:
            raise ValueError("hidden ELF case integrity check failed")
        cases.append(
            {
                "id": case_id,
                "content": content,
                "expected": extract_reference_values(content),
            }
        )
    return cases


class ElfExtractionOracle:
    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []
        self.case_index = 0
        self.evaluated = 0
        self.passed = True
        self.terminal_failure = False
        self.evaluation_ids: set[str] = set()
        self.failures: list[str] = []

    def initialize(self, run_seed: str) -> None:
        self.cases = _load_cases()
        seed = hashlib.sha256(("extract-elf\0" + run_seed).encode("utf-8")).digest()
        random.Random(seed).shuffle(self.cases)
        self.case_index = 0
        self.evaluated = 0
        self.passed = True
        self.terminal_failure = False
        self.evaluation_ids.clear()
        self.failures.clear()

    def _fail(self, category: str) -> None:
        self.passed = False
        self.terminal_failure = True
        self.failures.append(category)

    def next_case(self) -> dict[str, Any]:
        if self.terminal_failure or self.case_index >= len(self.cases):
            return {"type": "exhausted"}
        case = self.cases[self.case_index]
        content = case["content"]
        challenge = {
            "elf_base64": base64.b64encode(content).decode("ascii"),
            "elf_sha256": f"sha256:{hashlib.sha256(content).hexdigest()}",
        }
        context = {
            "case_id": case["id"],
            "case_index": self.case_index,
            "challenge_digest": json_digest(challenge),
        }
        self.case_index += 1
        return {
            "type": "case",
            "challenge": challenge,
            "case_context": context,
        }

    def evaluate_case(
        self, context: dict[str, Any], evidence: dict[str, Any]
    ) -> None:
        self.evaluated += 1
        case_index = context.get("case_index")
        case_id = context.get("case_id")
        if evidence.get("check_id") != CHECK_ID:
            self._fail("check_correlation_failed")
            return
        if (
            type(case_index) is not int
            or not 0 <= case_index < len(self.cases)
            or self.cases[case_index]["id"] != case_id
        ):
            self._fail("case_context_invalid")
            return
        challenge = evidence.get("challenge")
        if (
            not isinstance(challenge, dict)
            or challenge.get("index") != case_index
            or challenge.get("digest") != context.get("challenge_digest")
        ):
            self._fail("challenge_correlation_failed")
            return
        if evidence.get("status") != "observed":
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self._fail(str(code or "candidate_execution_failed"))
            return
        evaluation_id = evidence.get("evaluation_id")
        if not isinstance(evaluation_id, str) or evaluation_id in self.evaluation_ids:
            self._fail("evaluation_not_fresh")
            return
        self.evaluation_ids.add(evaluation_id)
        observation = evidence.get("observation")
        if not isinstance(observation, dict) or type(observation.get("exit_code")) is not int:
            self._fail("candidate_observation_invalid")
            return
        if observation["exit_code"] != 0:
            self._fail("candidate_execution_failed")
            return
        stdout = observation.get("stdout")
        if not isinstance(stdout, str):
            self._fail("candidate_output_invalid")
            return
        try:
            output = strict_json_loads(stdout)
        except (UnicodeError, ValueError):
            self._fail("candidate_output_invalid")
            return
        if not isinstance(output, dict) or len(output) > MAX_OUTPUT_FIELDS:
            self._fail("candidate_output_invalid")
            return
        if any(type(value) is not int for value in output.values()):
            self._fail("candidate_value_not_integer")
            return

        expected = self.cases[case_index]["expected"]
        found = 0
        for address, value in output.items():
            if address in expected:
                found += 1
                if value != expected[address]:
                    self._fail("candidate_value_incorrect")
                    return
        if found * 4 < len(expected) * 3:
            self._fail("candidate_coverage_insufficient")

    def verdict(self) -> dict[str, Any]:
        behavior = (
            self.evaluated == len(self.cases)
            and len(self.evaluation_ids) == len(self.cases)
            and self.passed
        )
        return {
            "type": "verdict",
            "verdict": {
                "passed": behavior,
                "score": 1.0 if behavior else 0.0,
                "check_outcomes": {CHECK_ID: behavior},
                "public_diagnostics": {
                    "message": (
                        "Extractor matched the bounded ELF challenge suite"
                        if behavior
                        else "Extractor behavior did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = ElfExtractionOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                run_seed = request.get("run_seed")
                if not isinstance(run_seed, str):
                    raise ValueError("run seed is required")
                oracle.initialize(run_seed)
                response = {"type": "ack"}
            elif operation == "next_case":
                if (
                    request.get("check_id") != CHECK_ID
                    or request.get("challenge_source") != "host.task_oracle"
                    or request.get("bounds")
                    != {"max_cases": len(CASE_DIGESTS), "max_case_bytes": MAX_CASE_BYTES}
                ):
                    raise ValueError("unsupported check")
                response = oracle.next_case()
            elif operation == "evaluate_case":
                context = request.get("case_context")
                evidence = request.get("evidence")
                if (
                    request.get("check_id") != CHECK_ID
                    or not isinstance(context, dict)
                    or not isinstance(evidence, dict)
                ):
                    raise ValueError("case evidence is required")
                oracle.evaluate_case(context, evidence)
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
