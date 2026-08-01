"""Public value objects for safe collection operations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping


QUEUE_SUSPENDED = -1
QUEUE_SCHED_BURIED = -2
QUEUE_USER_BURIED = -3
HIDDEN_QUEUES = frozenset({QUEUE_SUSPENDED, QUEUE_SCHED_BURIED, QUEUE_USER_BURIED})


class OperationError(RuntimeError):
    """An operation could not be applied without violating its safety contract."""


class Rating(IntEnum):
    """Values used by Anki's scheduler CardAnswer rating enum."""

    AGAIN = 0
    HARD = 1
    GOOD = 2
    EASY = 3

    @classmethod
    def from_value(cls, value: Any) -> "Rating":
        """Accept the enum, its integer, or its name.

        Transports carry JSON, so a rating arrives as `2` or `"good"`. Parsing
        it here keeps every transport agreeing on the same vocabulary, and
        makes an out-of-range integer a clean OperationError instead of
        whatever the backend does with an unknown rating.
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):  # bool is an int; never a rating
            raise OperationError(f"invalid rating: {value!r}")
        if isinstance(value, int):
            try:
                return cls(value)
            except ValueError:
                raise OperationError(
                    f"rating {value} is out of range; valid: "
                    f"{[member.value for member in cls]}"
                ) from None
        if isinstance(value, str):
            try:
                return cls[value.strip().upper()]
            except KeyError:
                raise OperationError(
                    f"unknown rating {value!r}; valid: "
                    f"{[member.name.lower() for member in cls]}"
                ) from None
        raise OperationError(f"invalid rating: {value!r}")


@dataclass(frozen=True)
class EventRef:
    """An immutable position in a caller-owned, contiguous event stream."""

    stream_id: str
    sequence: int
    event_id: str

    def validate(self) -> None:
        if not self.stream_id.strip() or len(self.stream_id) > 128:
            raise OperationError("stream_id must be 1-128 characters")
        if self.sequence < 1:
            raise OperationError("event sequence must be positive")
        if not self.event_id.strip() or len(self.event_id) > 128:
            raise OperationError("event_id must be 1-128 characters")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EventRef:
        try:
            event = cls(
                stream_id=str(value["stream_id"]),
                sequence=int(value["sequence"]),
                event_id=str(value["event_id"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OperationError("event must contain stream_id, sequence, and event_id") from exc
        event.validate()
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "event_id": self.event_id,
        }


@dataclass(frozen=True)
class Target:
    """An exact card plus the stable GUID of the note expected to own it."""

    card_id: int
    note_guid: str | None = None

    @classmethod
    def from_value(cls, value: Target | Mapping[str, Any] | int) -> Target:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            try:
                raw_guid = value.get("note_guid")
                return cls(
                    card_id=int(value["card_id"]),
                    note_guid=str(raw_guid) if raw_guid is not None else None,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise OperationError("target must contain a valid card_id") from exc
        try:
            return cls(card_id=int(value))
        except (TypeError, ValueError) as exc:
            raise OperationError("target must be a card ID or target object") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"card_id": self.card_id, "note_guid": self.note_guid}


@dataclass(frozen=True)
class GradingResult:
    card_ids: tuple[int, ...]
    # Which rating was actually recorded. Callers surface this to users, and a
    # result that does not say what it wrote cannot be audited.
    rating: Rating = Rating.AGAIN
    already_applied: bool = False
    preview_exits: tuple[int, ...] = ()
    rescheduling_filtered: tuple[int, ...] = ()
    preserved_suspended: tuple[int, ...] = ()
    preserved_user_buried: tuple[int, ...] = ()
    preserved_sched_buried: tuple[int, ...] = ()
    newly_suspended: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_ids": list(self.card_ids),
            "rating": self.rating.name.lower(),
            "already_applied": self.already_applied,
            "preview_exits": list(self.preview_exits),
            "rescheduling_filtered": list(self.rescheduling_filtered),
            "preserved_hidden_state": {
                "suspended": list(self.preserved_suspended),
                "user_buried": list(self.preserved_user_buried),
                "scheduler_buried": list(self.preserved_sched_buried),
            },
            "newly_suspended": list(self.newly_suspended),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AvailabilityResult:
    card_ids: tuple[int, ...]
    restored_suspended: tuple[int, ...] = ()
    restored_user_buried: tuple[int, ...] = ()
    restored_sched_buried: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_ids": list(self.card_ids),
            "restored": {
                "suspended": list(self.restored_suspended),
                "user_buried": list(self.restored_user_buried),
                "scheduler_buried": list(self.restored_sched_buried),
            },
            "note": "Review history is unchanged; only suspension/burial was removed.",
        }

