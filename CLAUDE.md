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
- `src/southplus/` — **South Plus reverse-engineering artifacts** (constants, models, HTTP clients, profile parser).
  - `src/southplus/api/` is the **only** layer `src/core/` and `main.py` may import from. The package root `__init__.py` is intentionally empty of re-exports.
  - Touching any file under `src/southplus/` requires updating `docs/southplus-capture.md` and its Capture date.
- `src/core/` — framework-only code with no knowledge of South Plus (auth server, SQLite store, datamodels, config, logger, **user_card_render** for the Pillow profile card).
- `src/shared/` — non-reverse-engineering shared constants (`PLUGIN_NAME`, log prefix).
- `src/utils/` — stateless utility subpackage (`crypto / text / timeutil / url`). Always import via `from src.utils import ...`.
- `templates/` — HTML templates rendered by `auth_server.py` (`login.html` / `expired.html` / `message.html` / `404.html`). Use `string.Template` syntax; no Jinja.
- `assets/` — static binary assets served by the auth server at `/assets/<filename>` (currently `logo.png`).

## Boundaries

- Never commit cookies, passwords, SQLite databases, or logs.
- Do not store South Plus passwords permanently.
- Keep AstrBot handlers in `main.py`; put framework-only logic in `src/core/`.
- Keep everything reverse-engineered from South Plus (URLs, form fields, cookie names, success/failure parsing, models, constants) in `src/api/`. Do not mix with `src/core/`, `src/shared/`, or `src/utils/`.
- Project-level non-reverse-engineering constants (e.g. `PLUGIN_NAME`) go in `src/shared/constants.py`. Reverse-engineering constants go in `src/api/constants.py`.
- Keep SQLite persistence in `src/core/data_source.py`; keep framework-only data models in `src/core/datamodels.py`; keep South-Plus-specific data models in `src/api/models.py`.
- Update `README.md` and `docs/` whenever commands, config, storage, or security behavior changes.
- Any change to South Plus reverse engineering must update `docs/southplus-capture.md` AND its "Capture 日期" line. That date-stamp rule applies only to `docs/southplus-capture.md`.
