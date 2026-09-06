# Repository Guidelines & Coding Standards

## Python Environment & Tooling
- Always execute Python tools and linters through the project virtual environment on Windows:
  - Linter: `.\.venv\Scripts\python.exe -m ruff check <path>`
  - Type Checker: `.\.venv\Scripts\python.exe -m pyrefly check`
  - Tests: `.\.venv\Scripts\python.exe -m pytest`
- **Post-Change Verification**: Always run both `pyrefly` and `ruff` checks after making changes to ensure there are no type errors or linting violations:
  - `.\.venv\Scripts\python.exe -m pyrefly check`
  - `.\.venv\Scripts\python.exe -m ruff check <path>` (or `.\.venv\Scripts\python.exe -m ruff check .`)
- **Safeguard Verification**: Whenever applying automated linting or formatting fixes (`ruff check --fix`), immediately run the test suite to ensure that auto-fixes have not introduced regressions or removed necessary side-effect imports.

## Code & Typing Standards
- **Typing Syntax**: Use modern Python typing features:
  - PEP 585 (Python 3.9+) built-in generics: `list[T]`, `dict[K, V]`, `set[T]`, `tuple[...]` instead of `typing.List`, `typing.Dict`, etc.
  - PEP 604 (Python 3.10+) union types: `T | None` and `TypeA | TypeB` instead of `typing.Optional[T]` or `typing.Union`.
  - Import callables from `collections.abc import Callable`.
- **Suppression Explanations**: Any type checker or linter suppressions (`pyrefly: ignore` or ruff `noqa`) must include a short explanation justifying why the suppression is necessary (e.g. `# pyrefly: ignore [bad-assignment] - dynamic monkey-patch`).
- **String Prefix & Suffix Checking**: Pass tuples to `str.startswith(...)` and `str.endswith(...)` (e.g. `s.startswith(("index-f", "master-"))`) instead of chaining multiple `or` expressions.
- **Exception Handling**: Avoid bare `except Exception: pass` where possible; log non-fatal warnings or narrow exceptions unless explicitly building fallback/resilience handlers.

## Testing Standards & Patterns
- **Before-and-After Refactoring Verification**:
  - Prior to initiating any structural refactoring, module decomposition, or import reorganization, execute the complete test suite (`.\.venv\Scripts\python.exe -m pytest`) to establish an explicit passing baseline.
  - Re-run the full test suite immediately after applying the refactoring to confirm zero functional or test regressions.
- **Live vs. Fast Test Execution**:
  - End-to-end integration tests that touch external networks are marked `@pytest.mark.live` and excluded by default via `pytest.ini` (`addopts = -m "not live"`).
  - Always run fast, local unit/mock tests during development (`.\.venv\Scripts\python.exe -m pytest`).
  - Never run live tests unconditionally; only run `.\.venv\Scripts\python.exe -m pytest -m live` when explicitly verifying external network connectivity.
- **Parametrization vs. Multiple Assertions**:
  - **Parametrize** pure transformation functions, validators, and option matrices (e.g. quality options, provider configs) using `@pytest.mark.parametrize`. Each boundary case must run as an independent, descriptive test node.
  - **Use multiple assertions** for action workflows and state machine transitions where a single execution produces a compound state outcome (e.g., verifying `status`, `progress`, `filepath`, and `completed_at` of a finished download).
- **Filename Collision & Boundary Parametrization**:
  - Whenever implementing or testing file matching, cleanup, or regex extractors, parametrize against realistic naming collisions (e.g. delimiters `_`, `.`, `-`, spaces, numeric suffixes like `.1`, and words sharing pattern prefixes like `final` or `first` for `.f<fmt>.`).
  - Verify both deletion of target files AND non-deletion/handle preservation of similar non-target files across all cases.
- **Background Worker & Queue Isolation**:
  - When unit testing execution logic (`execute_download`), instantiate models directly (`DownloadTask(...)`) instead of registering them into the singleton `manager.add_task(...)`. This prevents background polling threads from racing with test execution.
- **Configuration & Port Isolation in Tests**:
  - Tests must **never** read from or write to the repository's root `settings.json`. All test runs must operate in a temporary isolated environment via `VIDEO_DL_SETTINGS_FILE` (pointing to a dedicated file in pytest's `tmp_path`), enforced automatically by the `isolated_env` fixture in `tests/conftest.py`.
  - Tests must never bind or default to the production server port (`7921`). The test environment must enforce an alternate port (`VIDEO_DL_PORT=17921` or ephemeral port `0`) to prevent socket collisions or interference with active server instances running in the background.
  - Avoid manual state resets in `tearDown()` that write hardcoded dictionaries back to disk; rely on pytest's `monkeypatch` and fixture teardown to guarantee complete environmental isolation even upon test failures.

## Architecture & Third-Party Compatibility
- **Direct Imports & Explicit Dependencies**:
  - Always import symbols directly from their source modules without backwards-compatibility re-export facades (`__all__`); keep dependency graphs explicit and eliminate dead facade layers.
- **Provider Decoupling & Engine Agnosticism**:
  - Keep core execution engines (e.g. `server/engine.py`) strictly generic and provider-agnostic.
  - Never embed provider domain lists, hardcoded URL pattern checks, or provider-specific fallback headers directly inside the download engine.
  - All provider identification, matching patterns, concurrency limits, and custom provider configurations must reside in configuration (`settings.json` / `server/config.py`).
  - Client surfaces (extension popup, background scripts, web UI) must never maintain hardcoded provider domain lists or fallback strings; they must consume configured providers dynamically from the server (`/api/settings`) and mirror the backend's pattern matching.
  - **Minimalist Scope & Configuration Reuse**: Before proposing multi-component changes (altering server endpoints, background message channels, or test suites) to support client features, verify if existing configuration APIs already provide the required data. Avoid modifying the backend when the client can directly consume existing contracts.
  - Network and protocol semantics (such as browser default headers, player CORS fetch headers, and automatic `Origin` derivation from `Referer`) must remain completely generic across all providers.
- **Dynamic Provider State Invariants**:
  - Settings changes to provider definitions, patterns, or concurrency limits must take effect immediately on in-flight and queued tasks without requiring restarts or dropping task state.
- **Request Header Fidelity**:
  - Browser extension capture and download engine must propagate full original request headers (`Referer`, `Origin`, `User-Agent`, `Cookie`) end-to-end; never fall back to synthetic or provider-hardcoded headers.
- **Patch Quarantining**:
  - Centralize third-party library monkey-patches and runtime shims in dedicated compatibility modules (e.g. `server/patches.py`) rather than embedding them directly in core execution engines.
- **Security Mitigation Invariants**:
  - When patching third-party extractors or parsers (such as `yt-dlp`), never bypass or disable security allowlists (e.g. `_UnsafeExtensionError.ALLOWED_EXTENSIONS` / GHSA-79w7-vh3h-8g4j, GHSA-c6mh-fpjc-4pr3). All output files written to disk must strictly resolve to validated media types (`.mp4`, `.mkv`, etc.), never executable, server script, or shortcut extensions (`.desktop`, `.url`, `.webloc`).
- **Shared Directory Resource Isolation & Handle Scoping**:
  - In multi-threaded operations sharing a common directory (e.g. `download_dir`), file stream handle releases (such as `gc.get_objects()` scanning) and file deletion sweeps must strictly scope to the specific task's tracked files and exact stem matches.
  - **Never** perform directory-wide handle closures (e.g. `abs_name.startswith(download_dir)`), as this closes active write streams of concurrent tasks and triggers `ValueError: write to closed file`.
  - When matching format-specific stream artifacts (e.g. yt-dlp `.f<fmt>.` intermediate files), always enforce strict format specifier boundaries (`.f(\d+|ba|bv|...)...`) instead of open-ended string prefixes to prevent false-positive collisions with legitimate user filenames.
- **Cancellation Safety**:
  - Cancellation cleanup must release all task-scoped file handles, break exception reference cycles, and delete all task artifacts (main file, `.part`, `.ytdl`, fragments, format streams) without affecting concurrent downloads.
  - File deletion on Windows must use bounded retries with backoff to tolerate NTFS handle release latency.
  - Task execution entrypoints must check cancellation state before transitioning to `downloading` to prevent startup race conditions.


## Git Commit Standards
- Structure all commit messages using **Conventional Commits**:
  - Format: `<type>(<optional-scope>): <concise-description>`
  - Types: `fix`, `feat`, `refactor`, `test`, `chore`, `docs`, `perf`, `style`.
  - Body: Use bullet points detailing key structural changes, modernized patterns, or newly added configurations.
