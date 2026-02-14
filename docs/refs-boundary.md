# refs.py boundary plan

Purpose:
- Move refs handling out of `app_ui.py` while preserving current UI behavior and function-name compatibility.

Scope split in `app/ui/refs.py`:

## 1) resolve layer (pure logic)
- Input: primitive values / dicts (preset, release, species, selected mode, user values).
- Output: resolved choices / normalized values / validation-ready descriptors.
- No filesystem access.
- No subprocess/network.
- Deterministic and unit-test friendly.

Examples:
- pick default preset by species
- derive available releases for a preset
- normalize user-provided ref path strings

## 2) fetch/cache layer (I/O)
- Handles file/network side effects only.
- Reads cache files, checks gzip integrity, updates cache, executes fetch commands.
- Returns explicit status objects (`ok`, `missing`, `invalid`, `error`) and diagnostics.
- Never touches Streamlit session state directly.

Examples:
- run fetch command and parse result
- inspect cache root and file status
- gzip validation for downloaded refs

## 3) provide layer (UI-facing API)
- Stable adapter used by `app_ui.py`.
- Keeps compatibility function names/signatures expected by current UI flow.
- Calls resolve/fetch-cache internally and translates results into UI-ready structures.
- This is the only layer that may map raw statuses into localized display fields.

Compatibility policy:
- Keep `app_ui.py` call sites and function names stable.
- Switch internals to delegation gradually.
- Avoid changing persisted file paths/keys and existing output contracts.

Migration steps:
1. Extract pure resolve helpers and add unit tests.
2. Move fetch/cache side effects behind dedicated functions with typed return payloads.
3. Convert `app_ui.py` refs helpers into thin wrappers over `app/ui/refs.py` provide API.
4. Remove duplicated logic in `app_ui.py` only after wrapper parity is verified.
