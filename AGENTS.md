# AGENTS.md

|语言:默认简中答复|术语可夹 English|code-id 保持英文|
|范围:本目录为 AstrBot 插件|运行目录在 `astrbot-plugin-dev/data/plugins/astrbot_plugin_south_plus`|
|安全:不得提交 Cookie、密码、SQLite 数据库、日志|密码只允许内存中一次性使用|
|架构: `main.py` 只接 AstrBot|业务逻辑放 `src/core/`|Dashboard 放 `pages/`|文档放 `docs/`|
|数据层: SQLite 与 CRUD 在 `src/core/data_source.py`|数据模型在 `src/core/datamodels.py`|
|临时链接:默认 300 秒有效|提交即失效|过期必须通知用户|
|错误处理:登录失败、验证码、网络异常、页面结构变化须显式返回|不得伪造成功|
|测试:改 Python 逻辑需补或改测试|至少运行 `python -m compileall .` 与相关 pytest|
|文档:命令、配置、数据结构、安全边界变化须同步 README 与 docs|
