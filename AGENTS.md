# Agent Instructions

## Python Package and Command Policy

- Use `uv` for Python dependency and command execution in this repository.
- Do not use `pip` commands directly in docs, scripts, or CI-related local command examples.
- Preferred patterns:
  - `uv sync --group ...`
  - `uv run pytest ...`
  - `uv run ruff ...`

## Release Version Policy

- Do not use helper scripts to bump release version numbers.
- During release preparation, manually update both files to the same `X.Y.Z` value:
  - `pyproject.toml` (`version = "X.Y.Z"`)
  - `custom_components/bayrol/manifest.json` (`"version": "X.Y.Z"`)
- The Git tag must be `vX.Y.Z` and must match those file versions.
