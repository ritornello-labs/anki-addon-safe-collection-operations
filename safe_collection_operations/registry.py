"""Transport-neutral registry for the add-on's curated public operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .grading import (
    fail_cards_now,
    get_grading_cursor,
    grade_cards_now,
    inspect_cards,
    make_cards_available,
)
from .models import EventRef, OperationError, Target


Handler = Callable[[Any, Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class OperationSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    writes: bool = False

    def mcp_tool(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class OperationRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, OperationSpec] = {}

    def register(self, spec: OperationSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate operation: {spec.name}")
        self._specs[spec.name] = spec

    def specs(self) -> tuple[OperationSpec, ...]:
        return tuple(self._specs.values())

    def execute(self, col: Any, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        try:
            spec = self._specs[name]
        except KeyError as exc:
            raise OperationError(f"unknown operation: {name}") from exc
        return spec.handler(col, arguments)


def _capabilities(_col: Any, _arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": "Safe Collection Operations for Anki Add-ons",
        "api_version": 1,
        "operations": [
            "capabilities",
            "inspect_cards",
            "get_grading_cursor",
            "fail_cards_now",
            "grade_cards_now",
            "make_cards_available",
        ],
        "minimum_anki": "25.07",
        "runtime_dependencies": [],
    }


def _grading_arguments(arguments: Mapping[str, Any]) -> tuple[list[Target], EventRef]:
    raw_targets = arguments.get("targets")
    if not isinstance(raw_targets, list):
        raise OperationError("targets must be an array")
    targets = [Target.from_value(target) for target in raw_targets]
    raw_event = arguments.get("event")
    if not isinstance(raw_event, Mapping):
        raise OperationError("event is required for transport-originated grading")
    return targets, EventRef.from_mapping(raw_event)


def _fail_cards_now(col: Any, arguments: Mapping[str, Any]) -> dict[str, Any]:
    targets, event = _grading_arguments(arguments)
    return fail_cards_now(col, targets, event=event).to_dict()


def _grade_cards_now(col: Any, arguments: Mapping[str, Any]) -> dict[str, Any]:
    targets, event = _grading_arguments(arguments)
    # Absent rather than defaulted: a grading call that does not say what it is
    # recording should be a rejected call, not an implicit Again.
    if "rating" not in arguments:
        raise OperationError("rating is required (again, hard, good, or easy)")
    return grade_cards_now(
        col, targets, rating=arguments["rating"], event=event
    ).to_dict()


def _inspect_cards(col: Any, arguments: Mapping[str, Any]) -> dict[str, Any]:
    raw_ids = arguments.get("card_ids")
    if not isinstance(raw_ids, list):
        raise OperationError("card_ids must be an array")
    return inspect_cards(col, raw_ids)


def _get_grading_cursor(col: Any, arguments: Mapping[str, Any]) -> dict[str, Any]:
    stream_id = arguments.get("stream_id")
    if not isinstance(stream_id, str):
        raise OperationError("stream_id must be a string")
    return get_grading_cursor(col, stream_id)


def _make_cards_available(col: Any, arguments: Mapping[str, Any]) -> dict[str, Any]:
    raw_ids = arguments.get("card_ids")
    if not isinstance(raw_ids, list):
        raise OperationError("card_ids must be an array")
    return make_cards_available(col, raw_ids).to_dict()


def build_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(
        OperationSpec(
            name="capabilities",
            description="Report the bridge version and curated operation surface.",
            input_schema={"type": "object", "properties": {}},
            handler=_capabilities,
        )
    )
    registry.register(
        OperationSpec(
            name="inspect_cards",
            description=(
                "Resolve exact card IDs to note GUIDs and scheduler context before a write."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "card_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "integer"},
                    }
                },
                "required": ["card_ids"],
            },
            handler=_inspect_cards,
        )
    )
    registry.register(
        OperationSpec(
            name="get_grading_cursor",
            description=(
                "Read the last committed sequence and event ID for a grading stream."
            ),
            input_schema={
                "type": "object",
                "properties": {"stream_id": {"type": "string"}},
                "required": ["stream_id"],
            },
            handler=_get_grading_cursor,
        )
    )
    registry.register(
        OperationSpec(
            name="fail_cards_now",
            description=(
                "Record native Again ratings on exact cards, including future and "
                "filtered-deck cards. Preserve existing suspension/burial and return "
                "that state so the caller can tell the user and offer to remove it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "card_id": {"type": "integer"},
                                "note_guid": {"type": "string"},
                            },
                            "required": ["card_id", "note_guid"],
                        },
                    },
                    "event": {
                        "type": "object",
                        "properties": {
                            "stream_id": {"type": "string"},
                            "sequence": {"type": "integer", "minimum": 1},
                            "event_id": {"type": "string"},
                        },
                        "required": ["stream_id", "sequence", "event_id"],
                    },
                },
                "required": ["targets", "event"],
            },
            handler=_fail_cards_now,
            writes=True,
        )
    )
    registry.register(
        OperationSpec(
            name="grade_cards_now",
            description=(
                "Record a native rating (again, hard, good, or easy) on exact "
                "cards, including future and filtered-deck cards. Identical to "
                "fail_cards_now in every guarantee it makes - only the recorded "
                "rating differs. Preserve existing suspension/burial and return "
                "that state so the caller can tell the user and offer to remove it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "targets": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "card_id": {"type": "integer"},
                                "note_guid": {"type": "string"},
                            },
                            "required": ["card_id", "note_guid"],
                        },
                    },
                    "rating": {
                        "description": (
                            "again, hard, good, or easy (or 0-3). Required: a "
                            "grading call that does not say what it records is "
                            "rejected rather than defaulted."
                        ),
                        "oneOf": [
                            {"type": "string", "enum": ["again", "hard", "good", "easy"]},
                            {"type": "integer", "minimum": 0, "maximum": 3},
                        ],
                    },
                    "event": {
                        "type": "object",
                        "properties": {
                            "stream_id": {"type": "string"},
                            "sequence": {"type": "integer", "minimum": 1},
                            "event_id": {"type": "string"},
                        },
                        "required": ["stream_id", "sequence", "event_id"],
                    },
                },
                "required": ["targets", "rating", "event"],
            },
            handler=_grade_cards_now,
            writes=True,
        )
    )
    registry.register(
        OperationSpec(
            name="make_cards_available",
            description=(
                "Remove suspension or burial from exact cards through Anki's native "
                "scheduler. Review history and the previously recorded failure remain."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "card_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "integer"},
                    }
                },
                "required": ["card_ids"],
            },
            handler=_make_cards_available,
            writes=True,
        )
    )
    return registry
