"""Registry of bounded parsers for hostile candidate artifacts."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any, Callable, Literal

from securebench.data_formats import strict_json_loads
from securebench.verification.models import ParserRejected


ParserInputKind = Literal["bytes", "tree"]
BytesParser = Callable[[bytes], Any]
TreeParser = Callable[[dict[str, Any]], Any]


MAX_CSV_BYTES = 16 * 1024 * 1024
MAX_CSV_COLUMNS = 256
MAX_CSV_ROWS = 100_000
MAX_CSV_CELLS = 1_000_000
MAX_CSV_CELL_CHARACTERS = 64 * 1024


@dataclass(frozen=True)
class ParserProfile:
    id: str
    input_kind: ParserInputKind
    implementation: BytesParser | TreeParser


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


def default_parser_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(ParserProfile("securebench.strict-json/v1", "bytes", _strict_json))
    registry.register(ParserProfile("securebench.utf8-text/v1", "bytes", _utf8_text))
    registry.register(ParserProfile("securebench.ics/v1", "bytes", _ics))
    registry.register(ParserProfile("securebench.strict-csv/v1", "bytes", _strict_csv))
    registry.register(ParserProfile("securebench.tree-manifest/v1", "tree", _tree_manifest))
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
