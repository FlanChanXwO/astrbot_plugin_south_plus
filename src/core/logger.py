from __future__ import annotations

import logging
from typing import Any

from ..shared.constants import LOG_PREFIX, PLUGIN_NAME
from ..utils import mask_secret


class PluginLogger:
    def __init__(self, base_logger: Any) -> None:
        self._base_logger = base_logger

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._base_logger.debug(self._format(message), *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._base_logger.info(self._format(message), *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._base_logger.warning(self._format(message), *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._base_logger.error(self._format(message), *args, **kwargs)

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._base_logger.exception(self._format(message), *args, **kwargs)

    def mask_secret(self, value: str, *, keep: int = 6) -> str:
        return mask_secret(value, keep=keep)

    @staticmethod
    def _format(message: str) -> str:
        return f"{LOG_PREFIX} {message}"


def get_plugin_logger(base_logger: Any | None = None) -> PluginLogger:
    if base_logger is None:
        try:
            from astrbot.api import logger as astrbot_logger
        except ImportError:
            base_logger = logging.getLogger(PLUGIN_NAME)
        else:
            base_logger = astrbot_logger
    return PluginLogger(base_logger)


plugin_logger = get_plugin_logger()
