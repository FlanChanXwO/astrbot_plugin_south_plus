# South Plus 插件维护文档

## 结构

```
astrbot_plugin_south_plus/
├── main.py                       # AstrBot 入口：命令、Web API、生命周期
├── _conf_schema.json             # 用户可配置项（Dashboard 渲染）
├── src/
│   ├── api/                      # ===== South Plus 站点逆向产物 =====
│   │   ├── constants.py          #   抓包得到的常量：URL 路径、UA、表单默认、cookie 后缀、失败关键字
│   │   ├── models.py             #   抓包数据模型：SouthPlusEndpoints / LoginRequest / LoginResult / CaptchaPayload；含 build_endpoints 工厂
│   │   └── client.py             #   HTTP 调用：SouthPlusClient / SouthPlusLoginAttempt
│   ├── core/                     # ===== 与站点解耦的插件框架代码 =====
│   │   ├── auth_server.py        #   一次性登录表单 HTTP server（验证码代理 / 状态机）
│   │   ├── data_source.py        #   SQLite 凭证数据源（Cookie 透明加解密）
│   │   ├── datamodels.py         #   框架数据模型：CredentialSession / StoredCredential / AuthServerConfig / PluginConfigSnapshot
│   │   ├── config_manager.py     #   读取 _conf_schema.json，喂给 api.build_endpoints
│   │   └── logger.py             #   带前缀的日志门面
│   ├── shared/                   # ===== 跨包共享的非抓包常量 =====
│   │   └── constants.py          #   PLUGIN_NAME / LOG_PREFIX 等项目级标识
│   └── utils/                    # ===== 无状态工具集 =====
│       ├── crypto.py             #   cookie 加解密原语
│       ├── text.py               #   脱敏、token 生成
│       ├── timeutil.py           #   ISO 时间、TTL 计算
│       └── url.py                #   URL 拼接、cookie 域解析
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
| `src/api/` | **是** | 必须同步 `docs/southplus-capture.md`（含顶部 Capture 日期）与 `tests/conftest.py` 的 mock 行为 |
| `src/core/` | 否 | 仅本目录 + 相关测试 |
| `src/shared/` | 否 | 仅本目录 |
| `src/utils/` | 否 | 仅本目录 + `tests/test_utils.py` |

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
 |             |                            | GET /ck.php?<nonce>         |
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
