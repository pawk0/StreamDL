# Repository Guidelines

## Tooling (Windows, project venv)

- Lint: `.\.venv\Scripts\python.exe -m ruff check <path>`
- Types: `.\.venv\Scripts\python.exe -m pyrefly check`
- Tests: `.\.venv\Scripts\python.exe -m pytest`

## Code

- Every `# pyrefly: ignore` or `# noqa` needs a short reason, e.g. `# pyrefly: ignore [bad-assignment] - dynamic monkey-patch`.

## Testing

- **Live vs. Fast Test Execution**:
  - End-to-end integration tests that touch external networks are marked `@pytest.mark.live` and excluded by default via `pytest.ini` (`addopts = -m "not live"`).
  - Always run fast, local unit/mock tests during development (`.\.venv\sScripts\python.exe -m pytest`).
  - Never run live tests unconditionally; only run `.\.venv\Scripts\python.exe -m pytest -m live` when explicitly verifying external network connectivity.
- **Parametrization vs. Multiple Assertions**:
  - **Parametrize** pure transformation functions, validators, and option matrices (e.g. quality options, provider configs) using `@pytest.mark.parametrize`. Each boundary case must run as an independent, descriptive test node.
  - **Use multiple assertions** for action workflows and state machine transitions where a single execution produces a compound state outcome (e.g., verifying `status`, `progress`, `filepath`, and `completed_at` of a finished download).

- Never read or write the repo's root `settings.json`, and never use the production port `7921`. Tests run through the `isolated_env` fixture in `tests/conftest.py`; do not bypass it or reset state manually in teardown.

## Architecture

- Core engines (e.g. `server/engine.py`) are provider-agnostic: no provider domains, URL patterns, or provider-specific headers.
- Capture and download must propagate the original request headers (`Referer`, `Origin`, `User-Agent`, `Cookie`) unchanged.
- Put third-party monkey-patches in compatibility modules (e.g. `server/patches.py`), not in core engines.
- Never weaken yt-dlp's unsafe-extension allowlist. Output files must be validated media types, never executable or shortcut extensions.

## Git Commit Standards
- Structure all commit messages using **Conventional Commits**:
  - Format: `<type>(<optional-scope>): <concise-description>`
  - Types: `fix`, `feat`, `refactor`, `test`, `chore`, `docs`, `perf`, `style`.
  - Body: Use bullet points detailing key structural changes, modernized patterns, or newly added configurations.
