"""Turn what the user wants to extract into ``ExtractionTarget``s.

The input is either the user's Pydantic model (Python API) or the ``--fields`` JSON (CLI).
"""

from __future__ import annotations

import json
import types
from decimal import Decimal
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, Field, ValidationError, create_model

from .exceptions import SchemaError
from .models import ExtractionKind, ExtractionTarget, TargetDefinition

_PYTHON_TYPES: dict[ExtractionKind, type] = {
    "str": str,
    "int": int,
    "float": float,
    "decimal": Decimal,
}


def _split_optional_type(annotation: Any) -> tuple[Any, bool]:
    if get_origin(annotation) in (Union, types.UnionType):
        non_none_types = [arg for arg in get_args(annotation) if arg is not type(None)]
        is_nullable = len(non_none_types) != len(get_args(annotation))
        if len(non_none_types) == 1:
            return non_none_types[0], is_nullable
    return annotation, False


def _find_extraction_kind(annotation: Any) -> ExtractionKind | None:
    # bool is a subclass of int but is not supported.
    if not isinstance(annotation, type) or issubclass(annotation, bool):
        return None
    for kind, python_type in _PYTHON_TYPES.items():
        if issubclass(annotation, python_type):
            return kind
    return None


def build_targets_from_model(model: type[BaseModel]) -> list[ExtractionTarget]:
    targets = []
    for name, field_info in model.model_fields.items():
        annotation, is_nullable = _split_optional_type(field_info.annotation)
        kind = _find_extraction_kind(annotation)
        if kind is None:
            raise SchemaError(
                f"{model.__name__}.{name}: unsupported type {field_info.annotation!r}"
            )
        targets.append(
            ExtractionTarget(
                name=name,
                description=field_info.description or name,
                kind=kind,
                is_nullable=is_nullable,
                is_required=field_info.is_required(),
            )
        )
    if not targets:
        raise SchemaError(f"{model.__name__}: no fields defined")
    return targets


def _reject_duplicate_keys(key_value_pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Used for every JSON object, so it may be a field name or a key such as ``type``."""
    keys = [key for key, _ in key_value_pairs]
    for key in keys:
        if keys.count(key) > 1:
            raise SchemaError(f"--fields: duplicate key {key!r}")
    return dict(key_value_pairs)


def build_model_from_fields_json(text: str) -> type[BaseModel]:
    """Build a Pydantic model from the CLI ``--fields`` JSON.

    Each entry is either a description string or ``{"description": ..., "type": ...}``.
    """
    try:
        fields_json = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as e:
        raise SchemaError(f"--fields is not valid JSON: {e}") from None
    if not isinstance(fields_json, dict) or not fields_json:
        raise SchemaError("--fields must be a non-empty JSON object")

    field_definitions: dict[str, Any] = {}
    for name, field_json in fields_json.items():
        if not name.isidentifier() or name.startswith("_"):
            raise SchemaError(
                f"--fields: invalid field name {name!r} (use an identifier starting with a letter)"
            )
        if isinstance(field_json, str):
            field_json = {"description": field_json}
        try:
            definition = TargetDefinition.model_validate(field_json)
        except ValidationError as e:
            first_error = e.errors()[0]
            location = ".".join(str(part) for part in (name, *first_error["loc"]))
            raise SchemaError(f"--fields.{location}: {first_error['msg']}") from None
        field_definitions[name] = (
            _PYTHON_TYPES[definition.type] | None,
            Field(default=None, description=definition.description),
        )
    return create_model("Record", **field_definitions)
