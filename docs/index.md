# South Plus 插件维护文档

## 结构

```
astrbot_plugin_south_plus/
├── main.py                       # AstrBot 入口：命令、Web API、生命周期
├── _conf_schema.json             # 用户可配置项（Dashboard 渲染）
├── src/
│   ├── southplus/                # ===== South Plus 站点逆向产物 =====
│   │   ├── api/                  #   ⭐ 唯一对外接口层，core/main 必经此处
│   │   │   └── __init__.py       #     re-export 公开符号（SouthPlusClient/Profile* / 模型 / build_endpoints）
│   │   ├── constants.py          #   抓包得到的常量：URL 路径、UA、表单默认、cookie 后缀、失败关键字
│   │   ├── models.py             #   抓包数据模型：SouthPlusEndpoints / LoginRequest / LoginResult / CaptchaPayload / UserProfile
│   │   ├── client.py             #   登录 HTTP 调用：SouthPlusClient / SouthPlusLoginAttempt
│   │   └── profile_client.py     #   profile.php 抓取与解析：SouthPlusProfileClient / parse_profile_html
│   ├── core/                     # ===== 与站点解耦的插件框架代码 =====
│   │   ├── auth_server.py        #   一次性登录表单 HTTP server（验证码代理 / 状态机 / 模板渲染 / 静态资源）
│   │   ├── data_source.py        #   SQLite 凭证数据源（Cookie 透明加解密）
│   │   ├── datamodels.py         #   框架数据模型：CredentialSession / StoredCredential / AuthServerConfig / PluginConfigSnapshot
│   │   ├── config_manager.py     #   读取 _conf_schema.json，喂给 southplus.api.build_endpoints
│   │   ├── logger.py             #   带前缀的日志门面
│   │   └── user_card_render.py   #   Pillow 资料卡片渲染
│   ├── shared/                   # ===== 跨包共享的非抓包常量 =====
│   │   └── constants.py          #   PLUGIN_NAME / LOG_PREFIX 等项目级标识
│   └── utils/                    # ===== 无状态工具集 =====
│       ├── crypto.py             #   cookie 加解密原语
│       ├── text.py               #   脱敏、token 生成
│       ├── timeutil.py           #   ISO 时间、TTL 计算
│       └── url.py                #   URL 拼接、cookie 域解析
├── templates/                    # auth_server 用的 HTML 模板（string.Template 渲染）
│   ├── login.html
│   ├── expired.html
│   ├── message.html
│   └── 404.html
├── assets/                       # 静态资源，对外通过 /assets/<filename> 路由提供
│   └── logo.png
├── pages/credentials/            # Dashboard 凭证管理页
├── tests/                        # pytest + mock South Plus HTTP server
└── docs/                         # 维护文档
    ├── index.md                  # 你正在看的文件
    ├── development.md            # 开发记录与代码组织说明
    ├── security.md               # 安全边界
    └── southplus-capture.md      # **South Plus 抓包流程**（含 Capture 日期约束）
```

## 包边界速查

| 包 / 模块 | 是否含抓包知识 | 改动触发的同步项 |
| --- | --- | --- |
| `src/southplus/` | **是** | 必须同步 `docs/southplus-capture.md`（含顶部 Capture 日期）与 `tests/conftest.py` 的 mock 行为 |
| `src/core/` | 否 | 仅本目录 + 相关测试 |
| `src/shared/` | 否 | 仅本目录 |
| `src/utils/` | 否 | 仅本目录 + `tests/test_utils.py` |
| `templates/`、`assets/` | 否 | UI 资源；改动若涉及南+ logo/品牌需同步 `assets/` |

**分层规则**：`src/core/` 与 `main.py` 只允许 `from src.southplus.api import ...`，禁止直接 import `src/southplus/{client,models,constants,profile_client}.py`。测试可以白盒访问实现层。

## 数据位置

运行数据保存在 AstrBot 数据目录：

```text
data/plugin_data/astrbot_plugin_south_plus/southplus.db
```

该数据库不得提交到 Git。

## 抓包结论速查

完整抓包流程、当前抓包结果（端点、表单字段、cookie 行为、反爬、判定）、复测命令都在 [`docs/southplus-capture.md`](./southplus-capture.md)。

## 登录流程时序

```
用户         AstrBot                插件 HTTP server                 South Plus
 |             |                            |                              |
 |  /splogin   |                            |                              |
 |------------>|                            |                              |
 |             | create_session(token)      |                              |
 |             |--------------------------->|                              |
 |             | 链接 URL                    |                              |
 |             |<---------------------------|                              |
 |  访问 URL    |                            |                              |
 |---------------------------------------- >|                              |
 |             |                            | GET /login.php (cookie jar) |
 |             |                            |---------------------------> |
 |             |                            |<---------------------------|
 |             |                            | GET /ck.php?nowtime=<ms>     |
 |             |                            |---------------------------> |
 |             |                            |<--- PNG bytes -------------|
 |  填表+提交   |                            |                              |
 |---------------------------------------- >|                              |
 |             |                            | POST /login.php?            |
 |             |                            |---------------------------> |
 |             |                            |<--- Set-Cookie winduser ----|
 |             | on_login_success(cookie)   |                              |
 |             |<---------------------------|                              |
 |             | 通知"登录成功"              |                              |
 |<------------|                            |                              |
```

## 用户卡片渲染流程

```
用户         AstrBot                 SouthPlusProfileClient      user_card_render        South Plus
 |             |                            |                          |                       |
 |  /spprofile |                            |                          |                       |
 |------------>|                            |                          |                       |
 |             | 读 cookie from SQLite      |                          |                       |
 |             | fetch(cookie)              |                          |                       |
 |             |--------------------------->|                          |                       |
 |             |                            | GET bbs.../profile.php   |                       |
 |             |                            |---------------------------------------------- >|
 |             |                            |<-----------------HTML--------------------------|
 |             |                            | parse_profile_html → UserProfile                |
 |             |<---------------------------|                          |                       |
 |             | render_user_card(profile)  |                          |                       |
 |             |---------------------------------------------------- > |                       |
 |             |<- PNG bytes ----------------------------------------- |                       |
 |             | image_result(tmpfile)      |                          |                       |
 |<------------|                            |                          |                       |
```
