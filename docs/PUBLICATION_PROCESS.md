# Publication process

Publication uses the shared anki-addon-release 0.2.5 guard, pinned in CI to
`0a0fd06d19227279dca923c8a053d44d7d86a3a4`. Follow the [shared process](https://github.com/ritornello-labs/anki-addon-release/blob/0a0fd06d19227279dca923c8a053d44d7d86a3a4/docs/PUBLICATION_PROCESS.md).

Install `anki-publication-hooks` on each publishing machine before the first
public push. Keep snapshots, AnkiConnect responses, scheduling, recovery archives
and detailed audit reports outside every Git checkout. Local staged-object and
outgoing-history checks are required, including intermediate commits and tags.
Never bypass an unavailable remote, a failed check or an unsupported format.
Public Actions output is generic pass/fail; do not add details or report artifacts.

Before each release check the exact package bytes with `anki-publication-check
--artifact FILE` and produce a fixed-schema hash receipt using
`anki-publication-receipt FILE --receipt RECEIPT`. A rebuild or export invalidates
the previous receipt. Match uploaded bytes to the checked digest. Use synthetic
fixtures and disposable profiles for tests and public media; review prose and
screenshots separately. Listing images still require the user's visual approval.

A passing known-signature scan does not prove arbitrary personal content is safe.
Existing history and historical release assets require a separate private audit;
CI scans the current tree and incoming commits. Stop publication on a real finding,
preserve evidence privately, and prepare a scoped cleanup plan before history
rewrites or public deletions.
