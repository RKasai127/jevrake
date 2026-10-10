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

_PY_TYPES: dict[ExtractionKind, type] = {
    "str": str,
    "int": int,
    "float": float,
    "decimal": Decimal,
}


def _split_optional_type(annotation: Any) -> tuple[Any, bool]:
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if len(args) == 1:
            return args[0], nullable
    return annotation, False


def _find_extraction_kind(annotation: Any) -> ExtractionKind | None:
    # bool is a subclass of int but is not supported.
    if not isinstance(annotation, type) or issubclass(annotation, bool):
        return None
    for kind, py_type in _PY_TYPES.items():
        if issubclass(annotation, py_type):
            return kind
    return None


def build_targets_from_model(model: type[BaseModel]) -> list[ExtractionTarget]:
    targets = []
    for name, info in model.model_fields.items():
        annotation, nullable = _split_optional_type(info.annotation)
        found = _find_extraction_kind(annotation)
        if found is None:
            raise SchemaError(f"{model.__name__}.{name}: unsupported type {info.annotation!r}")
        targets.append(
            ExtractionTarget(
                name=name,
                description=info.description or name,
                kind=found,
                nullable=nullable,
                required=info.is_required(),
            )
        )
    if not targets:
        raise SchemaError(f"{model.__name__}: no fields defined")
    return targets


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    names = [name for name, _ in pairs]
    for name in names:
        if names.count(name) > 1:
            raise SchemaError(f"--fields: duplicate field name {name!r}")
    return dict(pairs)


def build_model_from_fields_json(text: str) -> type[BaseModel]:
    """Build a Pydantic model from the CLI ``--fields`` JSON.

    Each entry is either a description string or ``{"description": ..., "type": ...}``.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as e:
        raise SchemaError(f"--fields is not valid JSON: {e}") from None
    if not isinstance(raw, dict) or not raw:
        raise SchemaError("--fields must be a non-empty JSON object")

    definitions: dict[str, Any] = {}
    for name, value in raw.items():
        if not name.isidentifier() or name.startswith("_"):
            raise SchemaError(
                f"--fields: invalid field name {name!r} (use an identifier starting with a letter)"
            )
        if isinstance(value, str):
            value = {"description": value}
        try:
            definition = TargetDefinition.model_validate(value)
        except ValidationError as e:
            error = e.errors()[0]
            location = ".".join(str(part) for part in (name, *error["loc"]))
            raise SchemaError(f"--fields.{location}: {error['msg']}") from None
        # CLI fields are optional: a value that is not found becomes null instead of an error.
        definitions[name] = (
            _PY_TYPES[definition.type] | None,
            Field(default=None, description=definition.description),
        )
    return create_model("Record", **definitions)
