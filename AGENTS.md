# Repository Guidelines & Coding Standards

## Python Environment & Tooling
- Always execute Python tools and linters through the project virtual environment on Windows:
  - Linter: `.\.venv\Scripts\python.exe -m ruff check <path>`
  - Tests: `.\.venv\Scripts\python.exe -m pytest`
- **Safeguard Verification**: Whenever applying automated linting or formatting fixes (`ruff check --fix`), immediately run the test suite to ensure that auto-fixes have not introduced regressions or removed necessary side-effect imports.

## Code & Typing Standards
- **Typing Syntax**: Use modern Python 3.10+ annotations:
  - PEP 585 built-in generics: `list[T]`, `dict[K, V]`, `set[T]`, `tuple[...]` instead of `typing.List`, `typing.Dict`, etc.
  - PEP 604 union types: `T | None` and `TypeA | TypeB` instead of `typing.Optional[T]` or `typing.Union`.
  - Import callables from `collections.abc import Callable`.
- **Exception Handling**: Avoid bare `except Exception: pass` where possible; log non-fatal warnings or narrow exceptions unless explicitly building fallback/resilience handlers.

## Git Commit Standards
- Structure all commit messages using **Conventional Commits**:
  - Format: `<type>(<optional-scope>): <concise-description>`
  - Types: `fix`, `feat`, `refactor`, `test`, `chore`, `docs`, `perf`, `style`.
  - Body: Use bullet points detailing key structural changes, modernized patterns, or newly added configurations.
