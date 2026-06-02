# CLAUDE.md

This is an AstrBot plugin for South Plus credential and task automation.

## Commands

- Run syntax checks: `python -m compileall .`
- Run tests: `python -m pytest`
- Lint: `ruff check .`
- Start AstrBot from runtime root: `cd /Users/flanchan/Development/SourceCode/GithubProjects/astrbot-plugin-dev && astrbot run -r -p 6196`
- Reload this plugin from runtime root: `scripts/astrbot/reload-plugins.sh 6196 astrbot_plugin_south_plus`

## Package layout

- `main.py` — AstrBot entry point only.
- `src/api/` — **South Plus reverse-engineering artifacts** (constants, models, HTTP client). Touch this and you must touch `docs/southplus-capture.md` + its Capture date.
- `src/core/` — framework-only code with no knowledge of South Plus (auth server, SQLite store, datamodels, config, logger).
- `src/shared/` — non-reverse-engineering shared constants (`PLUGIN_NAME`, log prefix).
- `src/utils/` — stateless utility subpackage (`crypto / text / timeutil / url`). Always import via `from src.utils import ...`.

## Boundaries

- Never commit cookies, passwords, SQLite databases, or logs.
- Do not store South Plus passwords permanently.
- Keep AstrBot handlers in `main.py`; put framework-only logic in `src/core/`.
- Keep everything reverse-engineered from South Plus (URLs, form fields, cookie names, success/failure parsing, models, constants) in `src/api/`. Do not mix with `src/core/`, `src/shared/`, or `src/utils/`.
- Project-level non-reverse-engineering constants (e.g. `PLUGIN_NAME`) go in `src/shared/constants.py`. Reverse-engineering constants go in `src/api/constants.py`.
- Keep SQLite persistence in `src/core/data_source.py`; keep framework-only data models in `src/core/datamodels.py`; keep South-Plus-specific data models in `src/api/models.py`.
- Update `README.md` and `docs/` whenever commands, config, storage, or security behavior changes.
- Any change to South Plus reverse engineering must update `docs/southplus-capture.md` AND its "Capture 日期" line. That date-stamp rule applies only to `docs/southplus-capture.md`.
