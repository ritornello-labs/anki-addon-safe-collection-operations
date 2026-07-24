"""Anki add-on bootstrap."""

import sys
from pathlib import Path

from . import safe_collection_operations as _core
from .safe_collection_operations import *  # noqa: F403
from .safe_collection_operations.bootstrap import initialize


# AnkiWeb installs add-ons under numeric package names. The compatibility alias
# belongs to the desktop add-on host, not to the reusable library package:
# vendored/Git-installed copies must not claim a process-global add-on name.
sys.modules.setdefault("anki_safe_collection_operations", _core)

initialize(__name__, Path(__file__).resolve().parent)
