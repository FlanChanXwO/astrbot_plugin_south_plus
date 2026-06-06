"""South Plus 站点逆向产物。

包内分两层：

* 实现层（``client.py`` / ``exceptions.py`` / ``checkin_service.py`` /
  ``models.py`` / ``api/`` 子包内的各模块）只在包内部互相引用，
  **不向 ``core`` / ``main`` 暴露**。改这些模块属于"实现细节调整"，
  不算 API 变更。
* 接口层（``api/`` 子包的 ``__init__.py``）是对外的稳定 API。
  ``src/core/`` 与 ``main.py`` 一律 ``from .southplus.api import ...``，
  不要绕过子包直接 ``from .southplus.api.login import ...``。
* ``tests/`` 例外：测试可以白盒访问实现层（例如
  ``from src.southplus.api.profile import parse_profile_html``），用于覆盖
  没必要进入公开 API 的内部辅助函数。

``api/`` 子包结构：

* ``constants.py`` ── 所有 API 抓包常量集中定义
* ``login.py`` ── ``SouthPlusLoginApi`` / ``SouthPlusLoginAttempt``
* ``profile.py`` ── ``SouthPlusProfileApi`` / ``parse_profile_html``
* ``daily_checkin.py`` ── ``SouthPlusDailyCheckinApi``
* ``weekly_checkin.py`` ── ``SouthPlusWeeklyCheckinApi``

包根结构：

* ``client.py`` ── ``SouthPlusSession``（共享持久 ``httpx.Client``）
* ``exceptions.py`` ── 所有异常定义
* ``checkin_service.py`` ── ``CheckinService`` 签到服务
* ``models.py`` ── 数据模型与端点工厂

抓包流程见 ``docs/dev/southplus-capture.md``（含 Capture 日期约束）。
"""
