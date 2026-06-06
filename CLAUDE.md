# CLAUDE.md — astrbot_plugin_south_plus

本文件只保留 Claude 协作入口规则。业务细节按需阅读 `docs/project/`，维护规则优先阅读 `docs/dev/maintenance.md`。

## 沟通语言

必须使用中文与用户交流。

## 项目形态

- **语言**: Python 3.10+
- **框架**: AstrBot plugin system
- **架构**: 简单分层（非 DDD）
- **许可证**: MIT

主要目录：

```text
main.py                    AstrBot 命令注册与生命周期协调
src/southplus/api/         South Plus 逆向层唯一对外接口
src/core/                  框架代码（config、datamodels、db、checkin_scheduler）
src/core/db/migrations/    V{N}_{描述}.py 版本化迁移脚本
src/web/                   HTTP 层（auth server + 静态模板）
src/pages/                 Plugin Pages Web API 后端
src/render/                HTML+t2i 卡片渲染
src/shared/                项目级共享常量
src/utils/                 无状态工具（events/messages/season/crypto/text/timeutil/url）
pages/                     Dashboard Plugin Pages
tests/                     pytest 测试套件
docs/                      维护与开发文档
assets/                    静态资源（logo 等）
```

## 阅读入口

- 任何改动前先看：`docs/dev/maintenance.md`
- 业务背景：`docs/project/README.md`
- 数据库表与 Dashboard 语义：`docs/project/README.md`
- South Plus 逆向边界：`docs/southplus-capture.md`
- 安全边界：`docs/security.md`

## 技能

修改本插件时可参考 `astrbot-dev-skill`（AstrBot 命令装饰器、Plugin Pages bridge、统一会话 ID 边界）。

## 硬约束

- `src/southplus/api/` 是唯一对外层；实现模块禁止被 `src/core/` 或 `main.py` 直接 import
- 逆向常量只能放 `src/southplus/`；触碰任何文件必须更新 `docs/southplus-capture.md` Capture 日期
- `main.py` 只接 AstrBot 命令注册，不放业务逻辑
- 账号密码只在单次请求内存中一次性使用，不落库、不打日志
- 新 db schema 变化通过新增 `V{N+1}` 脚本追加，不修改已有迁移脚本

## 文档纪律

文档是改动的一部分。命令行为、配置语义、登录/签到流程、db schema、包边界或安全边界变化时，必须在同一 patch 中更新相关 `docs/`。repo-wide 约束变化时同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## 测试与检查命令

从插件目录运行：

```bash
python -m compileall .
python -m pytest
ruff check .
```

从 AstrBot runtime 根目录重载：

```bash
scripts/astrbot/reload-plugins.sh 6196 astrbot_plugin_south_plus
```

## 维护

架构、命令面、db schema、配置路径或测试/lint 流程变化时，同步更新 `AGENTS.md` 和 `CLAUDE.md`。

## 篇幅约束

`AGENTS.md` 和 `CLAUDE.md` 均不得超过 100 行；内容过长时拆入 `docs/dev/` 或 `docs/project/`。
