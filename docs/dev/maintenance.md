# 维护规则 — astrbot_plugin_south_plus

本文面向维护者和协作 agent，记录仓库级开发约束。业务细节放 `docs/project/`。

## 文档同步

文档不是可选收尾。以下变化必须同步更新对应 `docs/`：

- 命令行为或参数变化
- 配置项、默认值、兼容规则变化
- 登录/签到/资料抓取流程变化（含 South Plus 接口变化）
- 数据库 schema 变化（含迁移脚本新增或修改）
- 包边界或安全边界变化

修改 repo-wide 约束或 agent 入口约定时，同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## 包边界

- `src/southplus/api/` 是 South Plus 逆向层的**唯一对外接口**；`src/core/` 和 `main.py` 只能通过它引用，不得直接 import 实现模块（`client.py` / `models.py` / `constants.py` / `profile_client.py`）。
- 逆向产物（URL、表单字段、cookie 名、成功/失败判定）只能放 `src/southplus/`。
- 框架代码（auth server、SQLite、datamodels、config、logger）放 `src/core/`。
- `src/web/`：HTTP 层（auth server + 静态模板）。
- `src/render/`：HTML+t2i 卡片渲染。
- `src/shared/`：项目级共享常量（`PLUGIN_NAME` 等）。
- `src/utils/`：无状态工具（事件平台识别、消息文案、季节名、时间、URL、文本、加密），统一通过 `from src.utils import ...` 引用。

## South Plus 逆向约束

- 触碰 `src/southplus/` 任何文件**必须**更新 `docs/dev/southplus-capture.md` 的 Capture 日期。
- 抓包结论变化时走"重新抓包 → 更新 Capture 日期 → 改 `src/southplus/`"流程，不得反向。

## 安全边界

- 账号密码只在单次请求内存中驻留，不写入 SQLite，不写入日志。
- Cookie 根据配置加密或明文写入 SQLite；`cookie_encryption_key` 留空时仅推荐本机调试。
- 不得提交 Cookie、密码、SQLite 数据库、日志文件或 Dashboard 密钥。
- 详细说明见 `docs/dev/security.md`。

## 数据库迁移

- 新 schema 变化通过 `src/core/db/migrations/V{N+1}_{描述}.py` 追加，不修改已有迁移脚本。
- 每个脚本实现 `def upgrade(conn: sqlite3.Connection) -> None`，逻辑须幂等。
- `setup_db(db_path)` 在 `main.py.__init__` 中、所有 Store 实例化前调用。

## 测试与检查

改动 Python 逻辑必须补测试或更新现有测试。常用命令：

```bash
python -m compileall .
python -m pytest
ruff check .
```

## 仓库体积

不要将字体、模型、媒体样例或大体积二进制资源纳入仓库。`assets/` 只存放轻量 logo PNG。
