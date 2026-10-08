# Repository Instructions

## Scope

This repository contains a public Anki utility add-on. Keep every committed
file safe for a public GitHub repository: no credentials, private hostnames,
personal collection data, absolute home-directory paths, or machine-specific
configuration.

## Architecture

- Keep native collection behavior in `safe_collection_operations/`.
- Keep transports thin: direct Python, AnkiConnect, and MCP must call the same
  operation registry and return the same result shapes.
- Use Anki-supported collection and scheduler operations. Never update Anki's
  scheduling tables directly.
- Treat the public operation list as a curated compatibility surface, not an
  unrestricted wrapper around `_backend` or SQLite.
- Preserve suspension and burial when grading hidden cards. Report preserved
  state so clients can tell users and offer to make cards available.

## Quality

- Run `make check` before committing.
- Validate behavior against a disposable real Anki client for scheduler or
  transport changes.
- Keep runtime dependencies at zero unless a strong public-use case justifies
  one.
- Sign commits with GPG.


## Publication safety

Follow `docs/PUBLICATION_PROCESS.md`. Install the shared local hooks before
public pushes, keep live artifacts outside Git, and check exact release bytes.
The required hosted publication check emits no private diagnostics.
