"""数据库迁移运行器。

迁移脚本命名规范：
    V{数字}_{描述}.py — 例如 V1_init.py

迁移脚本必须实现：
    def upgrade(conn: sqlite3.Connection) -> None
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ....utils.logger import plugin_logger as _log

_MIGRATION_PATTERN = re.compile(r"^V(\d+)_.+\.py$")
_DEFAULT_PACKAGE: str = __name__.rsplit(".", 1)[0]


def _extract_version(filename: str) -> int:
    match = _MIGRATION_PATTERN.match(filename)
    if not match:
        raise ValueError(
            f"无效的迁移文件名: {filename}，期望格式: V{{数字}}_{{描述}}.py"
        )
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class MigrationScript:
    version: int
    name: str
    module_name: str
    upgrade: Callable[..., None] | None = None


class MigrationRunner:
    _scripts: list[MigrationScript] | None = None

    def __init__(self, package: str = _DEFAULT_PACKAGE) -> None:
        self._package = package

    def _discover_scripts(self) -> list[MigrationScript]:
        scripts: list[MigrationScript] = []
        try:
            package = importlib.import_module(self._package)
            pkg_file = getattr(package, "__file__", None)
            if pkg_file is None:
                _log.warning("迁移包 %s 无 __file__", self._package)
                return []
            package_path = Path(pkg_file).parent
        except (ImportError, AttributeError):
            _log.warning("迁移包 %s 不存在或未找到 __file__", self._package)
            return []

        for _, module_name, is_pkg in pkgutil.iter_modules([str(package_path)]):
            if is_pkg:
                continue
            try:
                version = _extract_version(module_name + ".py")
            except ValueError:
                continue

            full_module_name = f"{self._package}.{module_name}"
            try:
                module = importlib.import_module(full_module_name)
            except Exception as ex:
                _log.error("加载迁移脚本 %s 失败: %s", full_module_name, ex)
                continue

            upgrade = getattr(module, "upgrade", None)
            if upgrade is None:
                _log.warning("迁移脚本 %s 缺少 upgrade 函数，已跳过", full_module_name)
                continue

            scripts.append(
                MigrationScript(
                    version=version,
                    name=module_name,
                    module_name=full_module_name,
                    upgrade=upgrade,
                )
            )

        scripts.sort(key=lambda s: s.version)

        seen: set[int] = set()
        for s in scripts:
            if s.version in seen:
                raise ValueError(f"迁移版本号重复: V{s.version}")
            seen.add(s.version)

        return scripts

    @property
    def scripts(self) -> list[MigrationScript]:
        if self._scripts is None:
            self._scripts = self._discover_scripts()
        return self._scripts

    def _get_applied_versions(self, conn: sqlite3.Connection) -> set[int]:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sp_migration_record'"
        ).fetchone()
        if row is None:
            return set()

        rows = conn.execute("SELECT version FROM sp_migration_record").fetchall()
        applied: set[int] = set()
        for r in rows:
            try:
                applied.add(int(r[0]))
            except (ValueError, TypeError):
                pass
        return applied

    def _record_migration(
        self, conn: sqlite3.Connection, version: int, description: str = ""
    ) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO sp_migration_record (version, applied_at, description)
            VALUES (?, datetime('now'), ?)
            """,
            (str(version), description),
        )

    def run_all(self, conn: sqlite3.Connection) -> list[int]:
        applied = self._get_applied_versions(conn)
        pending = [s for s in self.scripts if s.version not in applied]

        if not pending:
            _log.debug("数据库已是最新版本，无需迁移")
            return []

        executed: list[int] = []
        for script in pending:
            _log.info("执行迁移 V%s: %s", script.version, script.name)
            try:
                assert script.upgrade is not None
                script.upgrade(conn)
                self._record_migration(conn, script.version, script.name)
                executed.append(script.version)
                _log.info("迁移 V%s 执行成功", script.version)
            except Exception:
                _log.error("迁移 V%s (%s) 执行失败", script.version, script.name)
                raise

        _log.info("数据库迁移完成，本次执行 %d 个", len(executed))
        return executed


def run_migrations(conn: sqlite3.Connection) -> list[int]:
    return MigrationRunner().run_all(conn)
