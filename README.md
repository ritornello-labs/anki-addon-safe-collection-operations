<p align="center">
  <img src="docs/assets/hero.svg" alt="Safe Collection Operations for Anki Add-ons" width="100%">
</p>

<p align="center">
  <a href="https://github.com/ritornello-labs/anki-addon-safe-collection-operations/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ritornello-labs/anki-addon-safe-collection-operations/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Anki 25.07+" src="https://img.shields.io/badge/Anki-25.07%2B-4a7bd0">
  <img alt="Runtime dependencies: zero" src="https://img.shields.io/badge/runtime_dependencies-zero-20a36a">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-8b5cf6"></a>
</p>

<p align="center">
  A small public utility add-on that gives other Anki add-ons and local agents
  a stable, guarded path to native collection operations that are absent from—or
  unsafe to compose through—AnkiConnect.
</p>

## Why this exists

Anki's native scheduler knows how to handle FSRS, learning steps, filtered
decks, leeches, sibling burying, undo, and revision history. Recreating that
behavior with direct database edits is brittle. Composing multiple remote calls
can be just as risky when one succeeds and the next one fails.

This add-on packages narrow, high-value operations as one audited layer:

- one implementation per operation;
- native Anki APIs only—never direct scheduling-row writes;
- preflight guards and postcondition checks;
- stable result shapes that surface surprising state;
- thin adapters for other add-ons, AnkiConnect, and optional MCP clients.

## First capability: grade any card safely

`grade_cards_now` records an honest native review — **again**, **hard**,
**good**, or **easy** — even when the card is not due today. `fail_cards_now`
is the same operation pinned to `again`, kept as the original entry point.

| Starting state | Native behavior |
|---|---|
| Normal or future card | Browser-grade `Grade Now → <rating>` |
| Rescheduling filtered deck | One native rating in place |
| Preview filtered deck | Native `Easy` exits only the target preview, then the requested rating at home |
| Suspended | Record the review, then restore suspension |
| Manually buried | Record the review, then restore manual burial |
| Sibling-buried | Record the review, then restore scheduler burial |

The rating is the only thing that varies: every guarantee is about what must
*not* change around the write, so the revlog-count, `reps + 1`, and
hidden-queue postconditions are identical whichever rating is requested. The
preliminary `Easy` on a preview card is a mechanism for sending it home, not a
grade anyone chose. An unparseable or out-of-range rating is rejected before
the backend is touched, and a transport call that omits `rating` entirely is
refused rather than defaulted to `again` — a grading call that does not say
what it records should not run.

The result explicitly lists the rating written plus preserved suspension and
burial. Clients should tell the user and offer `make_cards_available`, which
removes the hidden state without erasing the recorded review.

## Library first, optional desktop bridge

The repository has two deliberately separate roles:

1. `safe_collection_operations/` is the transport-free Python library. It is
   source-vendored by add-ons such as Chat With Your Cards and installed from a
   pinned Git commit by headless Anki services.
2. The add-on root is an optional desktop bridge. It packages the same library
   for ordinary Anki installation and exposes the curated operations to local
   agents through AnkiConnect and, optionally, MCP.

CWYC users do not need the bridge for CWYC itself. Install the bridge when an
agent outside CWYC should be able to apply these operations to the open desktop
collection.

## One core, three adapters

<p align="center">
  <img src="docs/assets/architecture.svg" alt="Core operation registry with Python, AnkiConnect, and MCP adapters" width="92%">
</p>

### Other add-ons

Import the stable API after add-ons have loaded:

```python
from anki_safe_collection_operations import EventRef, Target, fail_cards_now

result = fail_cards_now(
    mw.col,
    [Target(card_id=123, note_guid="stable-note-guid")],
    event=EventRef(stream_id="my-addon", sequence=1, event_id="review-123"),
)
```

An add-on that vendors the library should use its own private package path
instead. The global `anki_safe_collection_operations` alias is registered only
by the installed desktop bridge, so a vendored copy cannot impersonate it.

### AnkiConnect

When AnkiConnect is installed, the add-on registers namespaced actions:

- `safeCollectionOperationsCapabilities`
- `safeCollectionOperationsInspectCards`
- `safeCollectionOperationsGetGradingCursor`
- `safeCollectionOperationsFailCardsNow`
- `safeCollectionOperationsMakeCardsAvailable`

These are additions to AnkiConnect, not claims about its stock API.

### MCP

The optional MCP adapter is disabled by default. When enabled, it exposes the
same curated operation registry over authenticated localhost HTTP. The MCP
transport is an adapter, not the source of truth, and never exposes arbitrary
Python, `_backend`, or SQL execution.

## Safety contract

- Run collection access on Anki's main thread.
- Address exact card IDs; never combine a broad search and mutation invisibly.
- Include note GUIDs for agent-originated writes so stale mappings fail closed.
- Reuse the same event stream position when retrying an uncertain request.
- Never switch from the desktop writer to another synced writer after an
  ambiguous timeout.
- Report preserved hidden state and offer to make affected cards available.

See [API.md](docs/API.md) and [SECURITY.md](SECURITY.md) for the complete public
contract.

## Development

```bash
make check
```

The build produces `dist/anki-addon-safe-collection-operations.ankiaddon` and
checks that only the manifest, configuration, bootstrap, and runtime package
are included.

## Status

Early public alpha. The operation surface is intentionally small while the
transaction, filtered-deck, undo, and transport behavior receives real-Anki
coverage. New operations are added for concrete consumers, not to mirror all of
Anki or AnkiConnect.
