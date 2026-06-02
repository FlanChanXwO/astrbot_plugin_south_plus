"""South Plus 站点逆向产物。

包内分两层：

* 实现层（``constants.py`` / ``models.py`` / ``client.py`` /
  ``profile_client.py`` 等）只在包内部互相引用，**不向 ``core`` /
  ``main`` 暴露**。改这些模块属于"实现细节调整"，不算 API 变更。
* 接口层（``api/`` 子包）是对外的稳定 API。``src/core/`` 与 ``main.py``
  一律 ``from .southplus.api import ...``，不要绕过子包直接
  ``from .southplus.client import ...``。
* ``tests/`` 例外：测试可以白盒访问实现层（例如 ``from
  src.southplus.profile_client import parse_profile_html``），用于覆盖
  没必要进入公开 API 的内部辅助函数。

抓包流程见 ``docs/southplus-capture.md``（含 Capture 日期约束）。
"""
