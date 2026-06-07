"""项目级、与 South Plus 站点无关的常量。

抓包得到的常量请放在 ``src/api/constants.py``，不要混到这里。
"""

from __future__ import annotations

PLUGIN_NAME = "astrbot_plugin_south_plus"
LOG_PREFIX = f"[{PLUGIN_NAME}]"

CHECKIN_TASK_KEY_PREFIX = "sp.checkin."
CHECKIN_TASK_KEY_ALL = "sp.checkin.all"
CHECKIN_TASK_KEY_SESSION = "sp.checkin.session"
CHECKIN_TASK_KEY_DAILY = "sp.checkin.daily"
CHECKIN_TASK_KEY_WEEKLY = "sp.checkin.weekly"
