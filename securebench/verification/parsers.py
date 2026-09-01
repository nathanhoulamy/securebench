"""Registry of bounded parsers for hostile candidate artifacts."""

from __future__ import annotations

import ast
import csv
import io
import math
import re
import struct
import sys
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from securebench.data_formats import strict_json_loads
from securebench.verification.models import ParserRejected


ParserInputKind = Literal["bytes", "tree", "stored_tree"]
BytesParser = Callable[[bytes], Any]
TreeParser = Callable[[dict[str, Any]], Any]


class BlobReader(Protocol):
    def __call__(self, digest: str, *, expected_size: int | None = None) -> bytes: ...


StoredTreeParser = Callable[[dict[str, Any], BlobReader], Any]


MAX_CSV_BYTES = 16 * 1024 * 1024
MAX_CSV_COLUMNS = 256
MAX_CSV_ROWS = 100_000
MAX_CSV_CELLS = 1_000_000
MAX_CSV_CELL_CHARACTERS = 64 * 1024
MAX_NPY_BYTES = 16 * 1024 * 1024
MAX_NPY_HEADER_BYTES = 10_000
MAX_NPY_ELEMENTS = 1_000_000
MAX_NPY_DIMENSIONS = 8
MAX_NPY_HEADER_AST_NODES = 256
NPY_MAGIC = b"\x93NUMPY"
NPY_FLOAT_DESCR = re.compile(r"^(?P<byteorder>[<>=])?f(?P<size>2|4|8|16)$")


@dataclass(frozen=True)
class ParserProfile:
    id: str
    input_kind: ParserInputKind
    implementation: BytesParser | TreeParser | StoredTreeParser


class ParserRegistry:
    """Closed registry of reviewed parser profiles."""

    def __init__(self) -> None:
        self._profiles: dict[str, ParserProfile] = {}

    def register(self, profile: ParserProfile) -> None:
        if not profile.id:
            raise ValueError("parser profile id is required")
        if profile.id in self._profiles:
            raise ValueError(f"duplicate parser profile: {profile.id}")
        self._profiles[profile.id] = profile

    def profile(self, identifier: str) -> ParserProfile:
        try:
            return self._profiles[identifier]
        except KeyError as exc:
            raise KeyError(f"unknown parser profile: {identifier}") from exc

    def parse_bytes(self, identifier: str, content: bytes) -> Any:
        profile = self.profile(identifier)
        if profile.input_kind != "bytes":
            raise TypeError(f"parser {identifier!r} does not accept byte artifacts")
        return profile.implementation(content)

    def parse_tree(self, identifier: str, tree: dict[str, Any]) -> Any:
        profile = self.profile(identifier)
        if profile.input_kind != "tree":
            raise TypeError(f"parser {identifier!r} does not accept tree artifacts")
        return profile.implementation(tree)

    def parse_stored_tree(
        self,
        identifier: str,
        tree: dict[str, Any],
        read_blob: BlobReader,
    ) -> Any:
        profile = self.profile(identifier)
        if profile.input_kind != "stored_tree":
            raise TypeError(f"parser {identifier!r} does not accept stored tree artifacts")
        return profile.implementation(tree, read_blob)


def default_parser_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(ParserProfile("securebench.strict-json/v1", "bytes", _strict_json))
    registry.register(ParserProfile("securebench.utf8-text/v1", "bytes", _utf8_text))
    registry.register(ParserProfile("securebench.ics/v1", "bytes", _ics))
    registry.register(ParserProfile("securebench.strict-csv/v1", "bytes", _strict_csv))
    registry.register(
        ParserProfile("securebench.strict-npy-float-summary/v1", "bytes", _strict_npy_float_summary)
    )
    registry.register(ParserProfile("securebench.tree-manifest/v1", "tree", _tree_manifest))
    from securebench.verification.git_repository import git_repository_observation

    registry.register(
        ParserProfile(
            "securebench.git-repository/v1",
            "stored_tree",
            git_repository_observation,
        )
    )
    return registry


def _strict_json(content: bytes) -> Any:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParserRejected("invalid_utf8", "artifact is not valid UTF-8") from exc
    try:
        return strict_json_loads(text)
    except ValueError as exc:
        raise ParserRejected("invalid_json", "artifact is not valid JSON") from exc


def _utf8_text(content: bytes) -> str:
    try:
        return content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParserRejected("invalid_utf8", "artifact is not valid UTF-8") from exc


def _strict_npy_float_summary(content: bytes) -> dict[str, Any]:
    """Parse one bounded scalar-float NPY array into generic numeric statistics."""
    if len(content) > MAX_NPY_BYTES:
        raise ParserRejected("npy_too_large", "NPY artifact exceeds the parser byte bound")
    try:
        version, header, payload = _npy_parts(content)
        descr = header["descr"]
        fortran_order = header["fortran_order"]
        shape = header["shape"]
        byte_order, item_size = _npy_float_dtype(descr)
        count = _bounded_shape_size(shape)
        expected_bytes = count * item_size
        if len(payload) != expected_bytes:
            raise ValueError("NPY payload size does not match its shape and dtype")

        finite = True
        positive = True
        representable = True
        minimum: float | None = None
        maximum: float | None = None
        total = _CompensatedSum()
        for observed in _iter_npy_floats(payload, byte_order, item_size):
            if not observed.finite:
                finite = False
                positive = False
                continue
            if not observed.positive:
                positive = False
            if not math.isfinite(observed.value):
                representable = False
                continue
            minimum = (
                observed.value if minimum is None else min(minimum, observed.value)
            )
            maximum = (
                observed.value if maximum is None else max(maximum, observed.value)
            )
            total.add(observed.value)

        sum_value = (
            total.value
            if finite and representable and math.isfinite(total.value)
            else None
        )
        sum_log: float | None = None
        sum_x_log_x: float | None = None
        if finite and positive:
            logs = _CompensatedSum()
            weighted_logs = _CompensatedSum()
            for observed in _iter_npy_floats(payload, byte_order, item_size):
                assert observed.logarithm is not None
                logs.add(observed.logarithm)
                weighted_logs.add(observed.value * observed.logarithm)
            if math.isfinite(logs.value) and math.isfinite(weighted_logs.value):
                sum_log = logs.value
                sum_x_log_x = weighted_logs.value
    except ParserRejected:
        raise
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        SyntaxError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise ParserRejected("invalid_npy", "artifact is not a supported NPY float array") from exc

    return {
        "format": "npy",
        "version": list(version),
        "dtype": descr,
        "shape": list(shape),
        "fortran_order": fortran_order,
        "count": count,
        "statistics": {
            "all_finite": finite,
            "all_positive": positive,
            "minimum": minimum if finite else None,
            "maximum": maximum if finite else None,
            "sum": sum_value,
            "sum_log": sum_log,
            "sum_x_log_x": sum_x_log_x,
        },
    }


def _npy_parts(content: bytes) -> tuple[tuple[int, int], dict[str, Any], bytes]:
    if len(content) < 10 or not content.startswith(NPY_MAGIC):
        raise ValueError("NPY magic is missing")
    version = (content[6], content[7])
    if version == (1, 0):
        length_size = 2
        header_length = int.from_bytes(content[8:10], "little")
    elif version in {(2, 0), (3, 0)}:
        if len(content) < 12:
            raise ValueError("NPY preamble is truncated")
        length_size = 4
        header_length = int.from_bytes(content[8:12], "little")
    else:
        raise ValueError("NPY version is unsupported")
    if header_length <= 0 or header_length > MAX_NPY_HEADER_BYTES:
        raise ValueError("NPY header exceeds its bound")
    header_start = 8 + length_size
    header_end = header_start + header_length
    if header_end > len(content) or header_end % 64:
        raise ValueError("NPY header is truncated or misaligned")
    encoding = "utf-8" if version == (3, 0) else "latin-1"
    header_text = content[header_start:header_end].decode(encoding, errors="strict")
    if not header_text.endswith("\n"):
        raise ValueError("NPY header is not newline terminated")
    header = _strict_npy_header(header_text[:-1].rstrip(" "))
    return version, header, content[header_end:]


def _strict_npy_header(source: str) -> dict[str, Any]:
    expression = ast.parse(source, mode="eval")
    nodes = tuple(ast.walk(expression))
    if len(nodes) > MAX_NPY_HEADER_AST_NODES or not isinstance(expression.body, ast.Dict):
        raise ValueError("NPY header shape is invalid")
    keys: list[str] = []
    for node in expression.body.keys:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            raise ValueError("NPY header key is invalid")
        keys.append(node.value)
    if len(keys) != len(set(keys)) or set(keys) != {"descr", "fortran_order", "shape"}:
        raise ValueError("NPY header fields are invalid or ambiguous")
    value = ast.literal_eval(expression)
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("NPY header is invalid")
    descr = value.get("descr")
    fortran_order = value.get("fortran_order")
    shape = value.get("shape")
    if not isinstance(descr, str) or not isinstance(fortran_order, bool):
        raise ValueError("NPY dtype or storage order is invalid")
    if not isinstance(shape, tuple) or len(shape) > MAX_NPY_DIMENSIONS:
        raise ValueError("NPY shape is invalid")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in shape):
        raise ValueError("NPY dimensions are invalid")
    return {"descr": descr, "fortran_order": fortran_order, "shape": shape}


def _npy_float_dtype(descr: str) -> tuple[str, int]:
    matched = NPY_FLOAT_DESCR.fullmatch(descr)
    if matched is None:
        raise ParserRejected("unsupported_npy_dtype", "NPY artifact must contain scalar floats")
    item_size = int(matched.group("size"))
    byte_order = matched.group("byteorder") or "="
    if byte_order == "=":
        byte_order = "<" if sys.byteorder == "little" else ">"
    return byte_order, item_size


def _bounded_shape_size(shape: tuple[int, ...]) -> int:
    count = 1
    for dimension in shape:
        count *= dimension
        if count > MAX_NPY_ELEMENTS:
            raise ParserRejected(
                "npy_too_many_elements",
                "NPY artifact exceeds the parser element bound",
            )
    return count


def _iter_npy_floats(payload: bytes, byte_order: str, item_size: int):
    if item_size in {2, 4, 8}:
        code = {2: "e", 4: "f", 8: "d"}[item_size]
        for item in struct.iter_unpack(byte_order + code, payload):
            value = item[0]
            finite = math.isfinite(value)
            positive = finite and value > 0.0
            yield _NpyFloatObservation(
                value=value,
                finite=finite,
                positive=positive,
                logarithm=math.log(value) if positive else None,
            )
        return
    for offset in range(0, len(payload), 16):
        yield _decode_x87_extended(payload[offset : offset + 16], byte_order)


@dataclass(frozen=True)
class _NpyFloatObservation:
    value: float
    finite: bool
    positive: bool
    logarithm: float | None


def _decode_x87_extended(raw: bytes, byte_order: str) -> _NpyFloatObservation:
    if len(raw) != 16:
        raise ValueError("extended float payload is truncated")
    if byte_order == "<":
        significand = int.from_bytes(raw[:8], "little")
        sign_and_exponent = int.from_bytes(raw[8:10], "little")
    else:
        sign_and_exponent = int.from_bytes(raw[:2], "big")
        significand = int.from_bytes(raw[2:10], "big")
    sign = -1.0 if sign_and_exponent & 0x8000 else 1.0
    exponent = sign_and_exponent & 0x7FFF
    if exponent == 0x7FFF:
        value = sign * math.inf if significand == 1 << 63 else math.nan
        return _NpyFloatObservation(value, False, False, None)
    if exponent == 0:
        power = 1 - 16383 - 63
    elif significand < 1 << 63:
        raise ValueError("extended float has an invalid explicit integer bit")
    else:
        power = exponent - 16383 - 63
    try:
        value = sign * math.ldexp(float(significand), power)
    except OverflowError:
        value = sign * math.inf
    positive = sign > 0.0 and significand != 0
    logarithm = (
        math.log(significand) + power * math.log(2.0)
        if positive
        else None
    )
    return _NpyFloatObservation(value, True, positive, logarithm)


class _CompensatedSum:
    def __init__(self) -> None:
        self.total = 0.0
        self.correction = 0.0

    def add(self, value: float) -> None:
        combined = self.total + value
        if abs(self.total) >= abs(value):
            self.correction += (self.total - combined) + value
        else:
            self.correction += (value - combined) + self.total
        self.total = combined

    @property
    def value(self) -> float:
        return self.total + self.correction


def _strict_csv(content: bytes) -> dict[str, Any]:
    if len(content) > MAX_CSV_BYTES:
        raise ParserRejected("csv_too_large", "CSV artifact exceeds the parser byte bound")
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParserRejected("invalid_utf8", "artifact is not valid UTF-8") from exc
    if "\x00" in text:
        raise ParserRejected("invalid_csv", "CSV artifact contains a NUL byte")

    try:
        parsed_rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header: list[str] | None = None
        rows: list[list[str]] = []
        cell_count = 0
        for parsed in parsed_rows:
            if not parsed:
                continue
            _validate_csv_cells(parsed)
            if header is None:
                header = parsed
                if len(header) > MAX_CSV_COLUMNS:
                    raise ParserRejected(
                        "csv_too_many_columns",
                        "CSV artifact exceeds the parser column bound",
                    )
                if any(not name for name in header) or len(set(header)) != len(header):
                    raise ParserRejected(
                        "invalid_csv_header",
                        "CSV header names must be non-empty and unique",
                    )
                cell_count = len(header)
                continue
            if len(parsed) != len(header):
                raise ParserRejected(
                    "invalid_csv_shape",
                    "CSV rows must contain exactly the header field count",
                )
            if len(rows) >= MAX_CSV_ROWS:
                raise ParserRejected(
                    "csv_too_many_rows",
                    "CSV artifact exceeds the parser row bound",
                )
            cell_count += len(parsed)
            if cell_count > MAX_CSV_CELLS:
                raise ParserRejected(
                    "csv_too_many_cells",
                    "CSV artifact exceeds the parser cell bound",
                )
            rows.append(parsed)
    except ParserRejected:
        raise
    except (csv.Error, UnicodeError) as exc:
        raise ParserRejected("invalid_csv", "artifact is not valid CSV") from exc

    if header is None:
        raise ParserRejected("invalid_csv", "CSV artifact has no header row")
    return {"header": header, "rows": rows}


def _validate_csv_cells(row: list[str]) -> None:
    if any(len(value) > MAX_CSV_CELL_CHARACTERS for value in row):
        raise ParserRejected(
            "csv_cell_too_large",
            "CSV artifact contains a cell that exceeds the parser bound",
        )


def _ics(content: bytes) -> dict[str, Any]:
    text = _utf8_text(content)
    if "\x00" in text:
        raise ParserRejected("invalid_ics", "calendar contains a NUL byte")
    physical_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: list[str] = []
    for line in physical_lines:
        if len(line.encode("utf-8")) > 8192:
            raise ParserRejected("invalid_ics", "calendar line exceeds parser bound")
        if line.startswith((" ", "\t")):
            if not unfolded:
                raise ParserRejected("invalid_ics", "calendar starts with a folded continuation")
            unfolded[-1] += line[1:]
        elif line:
            unfolded.append(line)
    if not unfolded or unfolded[0].upper() != "BEGIN:VCALENDAR":
        raise ParserRejected("invalid_ics", "calendar must begin with VCALENDAR")
    if unfolded[-1].upper() != "END:VCALENDAR":
        raise ParserRejected("invalid_ics", "calendar must end with VCALENDAR")

    stack: list[str] = []
    components: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    calendar_properties: list[dict[str, Any]] = []
    for line in unfolded:
        name_and_parameters, separator, value = line.partition(":")
        if not separator:
            raise ParserRejected("invalid_ics", "calendar property is missing ':'")
        pieces = name_and_parameters.split(";")
        name = pieces[0].upper()
        parameters: dict[str, str] = {}
        for raw_parameter in pieces[1:]:
            key, equals, parameter_value = raw_parameter.partition("=")
            if not equals or not key:
                raise ParserRejected("invalid_ics", "calendar parameter is malformed")
            parameters[key.upper()] = parameter_value
        if name == "BEGIN":
            component_name = value.upper()
            stack.append(component_name)
            if component_name == "VEVENT":
                if current is not None:
                    raise ParserRejected("invalid_ics", "nested VEVENT is not supported")
                current = {"type": "VEVENT", "properties": []}
            continue
        if name == "END":
            component_name = value.upper()
            if not stack or stack.pop() != component_name:
                raise ParserRejected("invalid_ics", "calendar component nesting is invalid")
            if component_name == "VEVENT":
                assert current is not None
                components.append(current)
                current = None
            continue
        property_value = {"name": name, "parameters": parameters, "value": value}
        if current is not None:
            current["properties"].append(property_value)
        elif stack == ["VCALENDAR"]:
            calendar_properties.append(property_value)
    if stack:
        raise ParserRejected("invalid_ics", "calendar has unclosed components")
    return {"properties": calendar_properties, "events": components}


def _tree_manifest(tree: dict[str, Any]) -> dict[str, Any]:
    nodes = tree.get("nodes")
    if not isinstance(nodes, list):
        raise ParserRejected("invalid_tree", "candidate tree manifest is malformed")
    return {
        "nodes": [
            {
                key: node[key]
                for key in ("path", "kind", "mode", "size", "blob", "target")
                if key in node
            }
            for node in nodes
            if isinstance(node, dict)
        ]
    }
