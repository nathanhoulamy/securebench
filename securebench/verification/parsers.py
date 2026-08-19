"""Registry of bounded parsers for hostile candidate artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from securebench.verification.models import ParserRejected


ParserInputKind = Literal["bytes", "tree"]
BytesParser = Callable[[bytes], Any]
TreeParser = Callable[[dict[str, Any]], Any]


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
    registry.register(ParserProfile("securebench.tree-manifest/v1", "tree", _tree_manifest))
    return registry


def _strict_json(content: bytes) -> Any:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParserRejected("invalid_utf8", "artifact is not valid UTF-8") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParserRejected("invalid_json", "artifact is not valid JSON") from exc
    _reject_non_finite(value)
    return value


def _utf8_text(content: bytes) -> str:
    try:
        return content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParserRejected("invalid_utf8", "artifact is not valid UTF-8") from exc


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


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        raise ParserRejected("non_finite_json", "JSON numbers must be finite")
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
