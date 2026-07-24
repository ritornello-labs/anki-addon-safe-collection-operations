"""Stable public Python API for other Anki add-ons."""

from __future__ import annotations

from .grading import (
    CURSOR_CONFIG_KEY,
    fail_cards_now,
    get_grading_cursor,
    inspect_cards,
    make_cards_available,
)
from .models import (
    AvailabilityResult,
    EventRef,
    GradingResult,
    OperationError,
    Rating,
    Target,
)
from .registry import OperationRegistry, OperationSpec, build_registry


__all__ = [
    "AvailabilityResult",
    "CURSOR_CONFIG_KEY",
    "EventRef",
    "GradingResult",
    "OperationError",
    "OperationRegistry",
    "OperationSpec",
    "Rating",
    "Target",
    "build_registry",
    "fail_cards_now",
    "get_grading_cursor",
    "inspect_cards",
    "make_cards_available",
]

__version__ = "0.1.0"
