# Agent Instructions

## Python Package and Command Policy

- Use `uv` for Python dependency and command execution in this repository.
- Do not use `pip` commands directly in docs, scripts, or CI-related local command examples.
- Preferred patterns:
  - `uv sync --group ...`
  - `uv run pytest ...`
  - `uv run ruff ...`
