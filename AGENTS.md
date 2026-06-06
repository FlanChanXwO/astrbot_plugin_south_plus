# AGENTS.md — astrbot_plugin_south_plus

本文件只保留协作 agent 的入口规则。业务细节按需阅读 `docs/project/`，维护规则优先阅读 `docs/dev/maintenance.md`。

## 沟通语言

与用户沟通必须使用中文。

## 项目形态

AstrBot 插件，非 DDD。主要目录：

- `main.py` — AstrBot 命令注册与生命周期协调
- `src/southplus/api/` — South Plus 逆向层**唯一对外接口**
- `src/core/` — 框架代码（config、datamodels、db、checkin_scheduler）
- `src/core/db/migrations/` — `V{N}_{描述}.py` 版本化迁移脚本
- `src/web/` — HTTP 层（auth server + 静态模板）
- `src/pages/` — Plugin Pages Web API 后端
- `src/render/` — HTML+t2i 卡片渲染
- `src/shared/` — 项目级共享常量
- `src/utils/` — 无状态工具
- `pages/`、`tests/`、`docs/`、`assets/`

## 阅读入口

- 任何改动前先看：`docs/dev/maintenance.md`
- 业务背景：`docs/project/README.md`
- 数据库表与 Dashboard 语义：`docs/project/README.md`
- South Plus 逆向边界：`docs/dev/southplus-capture.md`
- 安全边界：`docs/dev/security.md`

## 硬约束

- `src/southplus/api/` 是唯一对外层；实现模块禁止被 `src/core/` 或 `main.py` 直接 import
- 逆向常量（URL、表单字段、cookie 名、成功/失败判定）只能放 `src/southplus/`
- `main.py` 只接 AstrBot 命令注册，不放业务逻辑
- 账号密码只在单次请求内存中一次性使用，不落库、不打日志
- 触碰 `src/southplus/` 任何文件必须更新 `docs/dev/southplus-capture.md` 的 Capture 日期
- 新 db schema 变化通过新增 `V{N+1}` 脚本追加，不修改已有迁移脚本

## 文档纪律

文档不是可选收尾。以下变化必须同步更新对应 `docs/`：

- 命令行为或参数变化
- 配置项、默认值、兼容规则变化
- 登录/签到/资料抓取流程变化
- 数据库 schema 变化（含迁移脚本）
- 包边界或安全边界变化

修改 repo-wide 约束或 agent 入口约定时，同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## 测试与检查命令

从插件目录运行：

```bash
python -m compileall .
python -m pytest
ruff check .
```

## 更新策略

架构、命令面、db schema、配置路径或测试/lint 流程变化时，同步更新 `CLAUDE.md` 和 `AGENTS.md`。

## 篇幅约束

`AGENTS.md` 和 `CLAUDE.md` 均不得超过 100 行；内容过长时拆入 `docs/dev/` 或 `docs/project/`。
