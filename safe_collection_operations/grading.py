"""Native arbitrary-card grading with filtered-deck and hidden-state guards."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Sequence

from .models import (
    HIDDEN_QUEUES,
    QUEUE_SCHED_BURIED,
    QUEUE_SUSPENDED,
    QUEUE_USER_BURIED,
    AvailabilityResult,
    EventRef,
    GradingResult,
    OperationError,
    Rating,
    Target,
)


CURSOR_CONFIG_KEY = "safeCollectionOperationsGradingCursorsV1"
MAX_EVENT_STREAMS = 64


@dataclass(frozen=True)
class _CardBefore:
    card_id: int
    note_id: int
    reps: int
    queue: int
    current_deck_id: int
    home_deck_id: int
    preview_filtered: bool
    rescheduling_filtered: bool


def _unique_targets(targets: Sequence[Target | dict[str, Any] | int]) -> list[Target]:
    unique: list[Target] = []
    positions: dict[int, int] = {}
    for raw in targets:
        target = Target.from_value(raw)
        card_id = int(target.card_id)
        if card_id <= 0:
            raise OperationError(f"invalid card id {card_id}")
        if card_id in positions:
            index = positions[card_id]
            existing = unique[index]
            if existing.note_guid and target.note_guid and existing.note_guid != target.note_guid:
                raise OperationError(f"card {card_id} was supplied with conflicting note GUIDs")
            if existing.note_guid is None and target.note_guid:
                unique[index] = target
            continue
        positions[card_id] = len(unique)
        unique.append(target)
    if not unique:
        raise OperationError("at least one card is required")
    return unique


def _unique_card_ids(card_ids: Iterable[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    result: list[int] = []
    for raw in card_ids:
        try:
            card_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise OperationError("card IDs must be integers") from exc
        if card_id <= 0:
            raise OperationError(f"invalid card id {card_id}")
        if card_id not in seen:
            seen.add(card_id)
            result.append(card_id)
    if not result:
        raise OperationError("at least one card is required")
    return tuple(result)


def _get_deck(col: Any, deck_id: int) -> Any:
    try:
        deck = col.decks.get(int(deck_id), default=False)
    except TypeError:
        deck = col.decks.get(int(deck_id))
    if not deck:
        raise OperationError(f"card points at missing deck {int(deck_id)}")
    return deck


def _preflight_cards(
    col: Any,
    targets: Sequence[Target],
    *,
    require_note_guids: bool,
) -> list[_CardBefore]:
    snapshots: list[_CardBefore] = []
    for target in targets:
        try:
            card = col.get_card(int(target.card_id))
        except Exception as exc:
            raise OperationError(f"card {target.card_id} no longer exists") from exc

        note_id = int(card.nid)
        if require_note_guids and not target.note_guid:
            raise OperationError(f"event target {target.card_id} is missing its note GUID")
        if target.note_guid:
            note = col.get_note(note_id)
            actual_guid = str(getattr(note, "guid", "") or "")
            if actual_guid != target.note_guid:
                raise OperationError(
                    f"card {target.card_id} no longer belongs to the expected note "
                    f"(GUID {target.note_guid!r} != {actual_guid!r})"
                )

        current_deck_id = int(card.did)
        original_deck_id = int(getattr(card, "odid", 0) or 0)
        current_deck = _get_deck(col, current_deck_id)
        current_is_filtered = bool(current_deck.get("dyn"))
        if current_is_filtered and not original_deck_id:
            raise OperationError(
                f"card {target.card_id} is homeless in filtered deck {current_deck_id} "
                "(odid=0)"
            )
        if original_deck_id and not current_is_filtered:
            raise OperationError(
                f"card {target.card_id} has odid={original_deck_id}, but current deck "
                f"{current_deck_id} is not filtered"
            )

        home_deck_id = original_deck_id or current_deck_id
        if bool(_get_deck(col, home_deck_id).get("dyn")):
            raise OperationError(
                f"card {target.card_id}'s home deck {home_deck_id} is filtered"
            )

        preview = current_is_filtered and not bool(current_deck.get("resched", True))
        snapshots.append(
            _CardBefore(
                card_id=int(target.card_id),
                note_id=note_id,
                reps=int(card.reps),
                queue=int(card.queue),
                current_deck_id=current_deck_id,
                home_deck_id=home_deck_id,
                preview_filtered=preview,
                rescheduling_filtered=current_is_filtered and not preview,
            )
        )
    return snapshots


def _read_cursors(col: Any) -> dict[str, dict[str, Any]]:
    raw = col.get_config(CURSOR_CONFIG_KEY, {})
    if not isinstance(raw, dict):
        raise OperationError("the collection's grading cursor map is malformed")
    parsed: dict[str, dict[str, Any]] = {}
    try:
        for stream_id, cursor in raw.items():
            if not isinstance(stream_id, str) or not isinstance(cursor, dict):
                raise TypeError
            parsed[stream_id] = {
                "sequence": int(cursor["sequence"]),
                "event_id": str(cursor["event_id"]),
            }
    except (KeyError, TypeError, ValueError) as exc:
        raise OperationError("the collection's grading cursor map is malformed") from exc
    return parsed


def _event_is_already_applied(col: Any, event: EventRef) -> bool:
    cursors = _read_cursors(col)
    cursor = cursors.get(event.stream_id)
    if cursor is None:
        if event.sequence != 1:
            raise OperationError(
                f"event stream starts with a gap: got {event.sequence}, expected 1"
            )
        if len(cursors) >= MAX_EVENT_STREAMS:
            raise OperationError(
                f"collection already tracks {MAX_EVENT_STREAMS} grading streams; "
                "retire one explicitly before adding another"
            )
        return False

    current = int(cursor["sequence"])
    if event.sequence < current:
        return True
    if event.sequence == current:
        if cursor["event_id"] != event.event_id:
            raise OperationError(
                f"grading sequence {event.sequence} was reused with a different event id"
            )
        return True
    if event.sequence != current + 1:
        raise OperationError(
            f"event stream has a gap: got {event.sequence}, expected {current + 1}"
        )
    return False


def _write_cursor(col: Any, event: EventRef) -> None:
    cursors = _read_cursors(col)
    cursors[event.stream_id] = {
        "sequence": event.sequence,
        "event_id": event.event_id,
    }
    col.set_config(CURSOR_CONFIG_KEY, cursors, undoable=False)
    stored = _read_cursors(col).get(event.stream_id)
    if stored is None or int(stored["sequence"]) != event.sequence:
        raise OperationError("grading cursor did not persist")


def get_grading_cursor(col: Any, stream_id: str) -> dict[str, Any]:
    """Return the committed position for a caller-owned grading stream."""

    normalized = str(stream_id).strip()
    if not normalized or len(normalized) > 128:
        raise OperationError("stream_id must be 1-128 characters")
    cursor = _read_cursors(col).get(normalized)
    if cursor is None:
        return {"stream_id": normalized, "sequence": 0, "event_id": None}
    return {
        "stream_id": normalized,
        "sequence": int(cursor["sequence"]),
        "event_id": str(cursor["event_id"]),
    }


def inspect_cards(col: Any, card_ids: Iterable[int]) -> dict[str, Any]:
    """Resolve exact card IDs to stable identities and scheduler context."""

    normalized = _unique_card_ids(card_ids)
    snapshots = _preflight_cards(
        col,
        [Target(card_id) for card_id in normalized],
        require_note_guids=False,
    )
    cards: list[dict[str, Any]] = []
    for snapshot in snapshots:
        note = col.get_note(snapshot.note_id)
        cards.append(
            {
                "card_id": snapshot.card_id,
                "note_id": snapshot.note_id,
                "note_guid": str(note.guid),
                "current_deck_id": snapshot.current_deck_id,
                "home_deck_id": snapshot.home_deck_id,
                "queue": snapshot.queue,
                "reps": snapshot.reps,
                "preview_filtered": snapshot.preview_filtered,
                "rescheduling_filtered": snapshot.rescheduling_filtered,
            }
        )
    return {"cards": cards}


def _revlog_count(col: Any, card_ids: Iterable[int]) -> int:
    ids = tuple(int(card_id) for card_id in card_ids)
    id_sql = "(" + ",".join(str(card_id) for card_id in ids) + ")"
    return int(col.db.scalar(f"select count() from revlog where cid in {id_sql}"))


def _discard_undo_entries(col: Any, count: int) -> None:
    for _ in range(count):
        try:
            col.undo()
        except Exception:
            return


def _native_operation(call: Callable[[], Any], increment: Callable[[], None]) -> Any:
    result = call()
    increment()
    return result


def fail_cards_now(
    col: Any,
    targets: Sequence[Target | dict[str, Any] | int],
    *,
    event: EventRef | None = None,
) -> GradingResult:
    """Record native Again ratings on arbitrary cards in one guarded operation.

    Retained as the original entry point, and the name every existing transport
    advertises; identical to ``grade_cards_now(..., rating=Rating.AGAIN)``.
    """

    return grade_cards_now(col, targets, rating=Rating.AGAIN, event=event)


def grade_cards_now(
    col: Any,
    targets: Sequence[Target | dict[str, Any] | int],
    *,
    rating: Rating | int | str = Rating.AGAIN,
    event: EventRef | None = None,
) -> GradingResult:
    """Record a native rating on arbitrary cards in one guarded operation.

    Run on Anki's main thread. Event-driven callers must provide an EventRef and
    note GUIDs. An explicit local add-on action may omit the event, accepting
    that cross-process retry idempotency is then unavailable.

    The rating is the ONLY thing that varies. Every guarantee this operation
    makes is rating-independent, because each one is about what must *not*
    change around the write: preview-filtered cards still take a preliminary
    Easy to exit the preview deck (a mechanism for sending them home, not a
    grade anyone chose) before the requested rating is recorded; suspension and
    burial are still preserved and reported; and the revlog-count, reps+1, and
    hidden-queue postconditions still run unchanged.
    """

    grade = Rating.from_value(rating)
    normalized = _unique_targets(targets)
    if event is not None:
        event.validate()

    backend_grade = getattr(getattr(col, "_backend", None), "grade_now", None)
    if not callable(backend_grade):
        raise OperationError("this Anki version does not expose native Grade Now")
    db_transact = getattr(getattr(col, "db", None), "transact", None)
    if not callable(db_transact):
        raise OperationError("collection transaction support is unavailable")
    if not all(
        callable(getattr(col, name, None))
        for name in ("add_custom_undo_entry", "merge_undo_entries", "undo")
    ):
        raise OperationError("collection undo support is unavailable")

    card_ids = tuple(target.card_id for target in normalized)
    result_box: dict[str, GradingResult] = {}
    undo_steps = 0
    undo_target: int | None = None

    def increment_undo() -> None:
        nonlocal undo_steps
        undo_steps += 1

    def apply() -> None:
        nonlocal undo_steps, undo_target
        if event is not None and _event_is_already_applied(col, event):
            result_box["result"] = GradingResult(
                card_ids=card_ids, rating=grade, already_applied=True
            )
            return

        cards = _preflight_cards(col, normalized, require_note_guids=event is not None)
        preview_ids = tuple(card.card_id for card in cards if card.preview_filtered)
        rescheduling_ids = tuple(
            card.card_id for card in cards if card.rescheduling_filtered
        )
        suspended_ids = tuple(card.card_id for card in cards if card.queue == QUEUE_SUSPENDED)
        user_buried_ids = tuple(card.card_id for card in cards if card.queue == QUEUE_USER_BURIED)
        sched_buried_ids = tuple(
            card.card_id for card in cards if card.queue == QUEUE_SCHED_BURIED
        )
        revlogs_before = _revlog_count(col, card_ids)

        undo_target = int(col.add_custom_undo_entry("Apply safe card grading"))
        undo_steps = 1

        if preview_ids:
            _native_operation(
                lambda: backend_grade(card_ids=list(preview_ids), rating=Rating.EASY),
                increment_undo,
            )
        _native_operation(
            lambda: backend_grade(card_ids=list(card_ids), rating=grade),
            increment_undo,
        )

        needs_suspend = tuple(
            card_id
            for card_id in suspended_ids
            if int(col.get_card(card_id).queue) != QUEUE_SUSPENDED
        )
        if needs_suspend:
            _native_operation(
                lambda: col.sched.suspend_cards(list(needs_suspend)), increment_undo
            )

        newly_suspended = tuple(
            card.card_id
            for card in cards
            if card.queue != QUEUE_SUSPENDED
            and int(col.get_card(card.card_id).queue) == QUEUE_SUSPENDED
        )
        needs_user_bury = tuple(
            card_id
            for card_id in user_buried_ids
            if int(col.get_card(card_id).queue) != QUEUE_SUSPENDED
            and int(col.get_card(card_id).queue) != QUEUE_USER_BURIED
        )
        if needs_user_bury:
            _native_operation(
                lambda: col.sched.bury_cards(list(needs_user_bury), manual=True),
                increment_undo,
            )
        needs_sched_bury = tuple(
            card_id
            for card_id in sched_buried_ids
            if int(col.get_card(card_id).queue) != QUEUE_SUSPENDED
            and int(col.get_card(card_id).queue) != QUEUE_SCHED_BURIED
        )
        if needs_sched_bury:
            _native_operation(
                lambda: col.sched.bury_cards(list(needs_sched_bury), manual=False),
                increment_undo,
            )

        expected_revlogs = len(card_ids) + len(preview_ids)
        actual_revlogs = _revlog_count(col, card_ids) - revlogs_before
        if actual_revlogs != expected_revlogs:
            raise OperationError(
                f"native grading wrote {actual_revlogs} revlog entries; "
                f"expected {expected_revlogs}"
            )

        for snapshot in cards:
            card = col.get_card(snapshot.card_id)
            if int(card.reps) != snapshot.reps + 1:
                raise OperationError(
                    f"card {snapshot.card_id} reps changed by "
                    f"{int(card.reps) - snapshot.reps}, expected +1"
                )
            if snapshot.preview_filtered:
                if int(getattr(card, "odid", 0) or 0) != 0:
                    raise OperationError(f"preview card {snapshot.card_id} did not return home")
                if int(card.did) != snapshot.home_deck_id:
                    raise OperationError(
                        f"preview card {snapshot.card_id} returned to deck {int(card.did)}, "
                        f"expected {snapshot.home_deck_id}"
                    )
            expected_queue = {
                QUEUE_SUSPENDED: QUEUE_SUSPENDED,
                QUEUE_USER_BURIED: QUEUE_USER_BURIED,
                QUEUE_SCHED_BURIED: QUEUE_SCHED_BURIED,
            }.get(snapshot.queue)
            if expected_queue is not None and int(card.queue) != expected_queue:
                if not (
                    snapshot.queue in {QUEUE_USER_BURIED, QUEUE_SCHED_BURIED}
                    and int(card.queue) == QUEUE_SUSPENDED
                ):
                    raise OperationError(
                        f"card {snapshot.card_id} did not preserve hidden queue "
                        f"{expected_queue}; got {int(card.queue)}"
                    )

        if event is not None:
            _write_cursor(col, event)

        result_box["result"] = GradingResult(
            card_ids=card_ids,
            rating=grade,
            preview_exits=preview_ids,
            rescheduling_filtered=rescheduling_ids,
            preserved_suspended=suspended_ids,
            preserved_user_buried=tuple(
                card_id
                for card_id in user_buried_ids
                if int(col.get_card(card_id).queue) == QUEUE_USER_BURIED
            ),
            preserved_sched_buried=tuple(
                card_id
                for card_id in sched_buried_ids
                if int(col.get_card(card_id).queue) == QUEUE_SCHED_BURIED
            ),
            newly_suspended=newly_suspended,
        )

    try:
        db_transact(apply)
    except OperationError:
        _discard_undo_entries(col, undo_steps)
        raise
    except Exception as exc:
        _discard_undo_entries(col, undo_steps)
        raise OperationError(str(exc)) from None

    result = result_box["result"]
    if result.already_applied or undo_target is None:
        return result
    try:
        col.merge_undo_entries(undo_target)
    except Exception as exc:
        return replace(
            result,
            warnings=(f"grading applied, but Anki could not merge undo steps: {exc}",),
        )
    return result


def make_cards_available(col: Any, card_ids: Iterable[int]) -> AvailabilityResult:
    """Natively remove suspension/burial from exact cards without changing reviews."""

    normalized = _unique_card_ids(card_ids)
    before: dict[int, int] = {}
    for card_id in normalized:
        try:
            before[card_id] = int(col.get_card(card_id).queue)
        except Exception as exc:
            raise OperationError(f"card {card_id} no longer exists") from exc

    hidden = tuple(card_id for card_id in normalized if before[card_id] in HIDDEN_QUEUES)
    if hidden:
        restore = getattr(
            getattr(col, "_backend", None),
            "restore_buried_and_suspended_cards",
            None,
        )
        if not callable(restore):
            raise OperationError("native restore operation is unavailable")
        restore(list(hidden))
        for card_id in hidden:
            if int(col.get_card(card_id).queue) in HIDDEN_QUEUES:
                raise OperationError(f"card {card_id} remained hidden after native restore")

    return AvailabilityResult(
        card_ids=normalized,
        restored_suspended=tuple(
            card_id for card_id in normalized if before[card_id] == QUEUE_SUSPENDED
        ),
        restored_user_buried=tuple(
            card_id for card_id in normalized if before[card_id] == QUEUE_USER_BURIED
        ),
        restored_sched_buried=tuple(
            card_id for card_id in normalized if before[card_id] == QUEUE_SCHED_BURIED
        ),
    )
