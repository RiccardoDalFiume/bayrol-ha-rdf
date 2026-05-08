# Contributing

Thanks for contributing to this Bayrol Home Assistant integration.

## Development setup

This repository uses `uv` for dependency management and command execution.

```bash
uv venv
uv sync --group test --group lint
```

## Local checks

Run these checks before opening a pull request:

```bash
uv run pytest tests/ -v --tb=short
uv run ruff check custom_components/ tests/
uv run ruff format --check custom_components/ tests/
```

## Live integration tests (optional)

Live tests require valid Bayrol credentials and external connectivity.

1. Copy `.env.example` to `.env`.
2. Set `BAYROL_RUN_LIVE_TESTS=true`.
3. Fill required `BAYROL_*` values.

## Pull requests

- Target the `main` branch.
- Keep changes focused and include tests when behavior changes.
- Ensure GitHub Actions checks pass (`lint`, `tests`, `validate`, `hassfest`).
- Update documentation when user-facing behavior changes.
