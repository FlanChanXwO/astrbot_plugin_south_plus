# South Plus 插件文档索引

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [project/README.md](./project/README.md) | 项目能力、架构分层、Dashboard 与数据库语义 |
| [dev/README.md](./dev/README.md) | 开发维护文档子索引 |
| [dev/maintenance.md](./dev/maintenance.md) | 维护规则、包边界、迁移规则、测试要求 |
| [dev/security.md](./dev/security.md) | 安全边界与 Cookie 存储说明 |
| [dev/southplus-capture.md](./dev/southplus-capture.md) | South Plus 抓包流程与逆向结论 |

## 结构

```
astrbot_plugin_south_plus/
├── main.py                        # AstrBot 入口：命令注册与生命周期协调
├── _conf_schema.json              # 用户可配置项（Dashboard 渲染）
├── src/
│   ├── southplus/                 # ===== South Plus 站点逆向产物 =====
│   │   ├── api/                   #   ⭐ 唯一对外接口层，core/main 必经此处
│   │   │   ├── __init__.py        #     re-export 公开符号
│   │   │   ├── constants.py       #     抓包常量集中定义
│   │   │   ├── login.py           #     SouthPlusLoginApi / SouthPlusLoginAttempt
│   │   │   ├── profile.py         #     SouthPlusProfileApi / parse_profile_html
│   │   │   ├── daily_checkin.py   #     SouthPlusDailyCheckinApi
│   │   │   └── weekly_checkin.py  #     SouthPlusWeeklyCheckinApi
│   │   ├── models.py              #   数据模型：SouthPlusEndpoints / LoginRequest / LoginResult 等
│   │   ├── client.py              #   SouthPlusSession（共享持久 httpx.Client）
│   │   ├── checkin_service.py     #   CheckinService（日 + 周签到门面）
│   │   └── exceptions.py         #   所有异常定义
│   ├── core/                      # ===== 与站点解耦的插件框架代码 =====
│   │   ├── auth_server.py         #   遗留兼容层（已迁移到 src/web/）
│   │   ├── config_manager.py      #   读取 _conf_schema.json，喂给 api.build_endpoints
│   │   ├── datamodels.py          #   框架数据模型：UserRow / ScheduleRow 等
│   │   ├── checkin_scheduler.py   #   APScheduler 签到调度（CronTrigger + 订阅表）
│   │   ├── platform_adapter.py    #   AstrBot 平台层适配
│   │   ├── user_card_render.py    #   遗留兼容层（已迁移到 src/render/）
│   │   ├── db/                    #   SQLite 持久化
│   │   │   ├── __init__.py        #     setup_db(db_path)：迁移入口
│   │   │   ├── user_store.py      #     UserStore
│   │   │   ├── checkin_store.py   #     CheckinStore
│   │   │   ├── schedule_store.py  #     ScheduleStore
│   │   │   ├── group_store.py     #     GroupStore
│   │   │   ├── user_group_store.py#     UserGroupStore
│   │   │   └── migrations/        #     版本化迁移脚本
│   │   │       ├── migration_runner.py
│   │   │       ├── V1_init.py
│   │   │       └── V2_user_auto_checkin.py
│   │   └── tasks/                 #   可调度任务基类与实现
│   │       ├── base.py
│   │       └── checkin_tasks.py
│   ├── web/                       # ===== HTTP 层 =====
│   │   └── auth_server.py         #   一次性登录表单 HTTP server（Jinja2 模板渲染）
│   ├── render/                    # ===== 卡片渲染 =====
│   │   └── card_render.py         #   HTML+t2i 渲染（Playwright）
│   ├── shared/                    # ===== 项目级共享常量 =====
│   │   └── constants.py           #   PLUGIN_NAME / LOG_PREFIX 等
│   └── utils/                     # ===== 无状态工具集 =====
│       ├── crypto.py
│       ├── events.py
│       ├── logger.py
│       ├── messages.py
│       ├── season.py
│       ├── text.py
│       ├── timeutil.py
│       └── url.py
├── data/
│   └── t2i_templates/             # Jinja2 HTML 模板（用户资料卡片）
├── assets/                        # 静态资源（logo.png）
├── pages/dashboard/               # Dashboard 数据库管理 Plugin Page
├── pages/credentials/             # 旧入口，跳转到 dashboard
├── tests/                         # pytest 测试套件
└── docs/                          # 维护文档
    ├── README.md                  # 你正在看的索引
    ├── dev/maintenance.md         # 维护规则、包边界、测试要求
    ├── dev/security.md            # 安全边界
    ├── dev/southplus-capture.md   # South Plus 抓包流程与结论（含 Capture 日期约束）
    └── project/README.md          # 业务概览与能力说明
```

## 包边界速查

| 包 / 模块 | 是否含抓包知识 | 改动触发的同步项 |
| --- | --- | --- |
| `src/southplus/` | **是** | 必须同步 `docs/dev/southplus-capture.md`（含顶部 Capture 日期）与 `tests/conftest.py` 的 mock 行为 |
| `src/core/` | 否 | 仅本目录 + 相关测试 |
| `src/web/` | 否 | HTTP server + Jinja2 模板 |
| `src/pages/` | 否 | Plugin Pages Web API 后端 |
| `src/render/` | 否 | HTML+t2i 渲染；Playwright 依赖 |
| `src/shared/` | 否 | 仅本目录 |
| `src/utils/` | 否 | 仅本目录 + `tests/test_utils.py` |

**分层规则**：`src/core/` 与 `main.py` 只允许 `from src.southplus.api import ...`，禁止直接 import `src/southplus/` 实现模块（`client`、`models`、`checkin_service`、`exceptions`、`api/login` 等）。测试可以白盒访问实现层。

## 数据位置

运行数据保存在 AstrBot 数据目录：

```text
data/plugin_data/astrbot_plugin_south_plus/southplus.db
```

该数据库不得提交到 Git。

## 登录流程时序

```
用户         AstrBot                src/web/auth_server             South Plus
 |             |                            |                              |
 |  /splogin   |                            |                              |
 |------------>|                            |                              |
 |             | get_or_create_session      |                              |
 |             |--------------------------->|                              |
 |             | 新建或复用登录链接 URL       |                              |
 |             |<---------------------------|                              |
 |  访问 URL   |                            |                              |
 |-------------------------------------------->|                          |
 |             |                            | GET /login.php (cookie jar) |
 |             |                            |----------------------------->|
 |             |                            |<-----------------------------|
 |             |                            | GET /ck.php?nowtime=<ms>     |
 |             |                            |----------------------------->|
 |             |                            |<--- PNG bytes ---------------|
 |  填表+提交  |                            |                              |
 |-------------------------------------------->|                          |
 |             |                            | POST /login.php?            |
 |             |                            |----------------------------->|
 |             |                            |<--- Set-Cookie winduser ----|
 |             | on_login_success(cookie)   |                              |
 |             |<---------------------------|                              |
 |             | 通知"登录成功"             |                              |
 |<------------|                            |                              |
```

## 抓包结论速查

完整抓包流程、端点、表单字段、cookie 行为、反爬、判定等详见 [`docs/dev/southplus-capture.md`](./dev/southplus-capture.md)。
