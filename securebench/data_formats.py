"""Strict decoders for configuration and protocol data."""

from __future__ import annotations

import json
from typing import Any

import yaml
from yaml.nodes import MappingNode


class DuplicateYamlKeyError(yaml.YAMLError):
    """Raised when YAML contains the same mapping key more than once."""


class DuplicateJsonKeyError(ValueError):
    """Raised when JSON contains the same object key more than once."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys at every depth."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise DuplicateYamlKeyError("duplicate YAML mapping key")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def strict_yaml_loads(value: str | bytes) -> Any:
    """Decode safe YAML while rejecting duplicate mapping keys."""
    return yaml.load(value, Loader=_UniqueKeySafeLoader)


def strict_json_loads(value: str | bytes) -> Any:
    """Decode one finite JSON value while rejecting duplicate object keys."""

    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON number: {constant}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise DuplicateJsonKeyError("duplicate JSON object key")
            result[key] = item
        return result

    try:
        return json.loads(
            value,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except RecursionError as exc:
        raise ValueError("JSON data exceeds the nesting limit") from exc
