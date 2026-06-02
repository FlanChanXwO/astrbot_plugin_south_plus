# astrbot_plugin_south_plus

South Plus 多用户凭证与自动任务管理插件。

## 当前能力

- `/splogin` 生成一次性临时登录链接（默认有效 10 分钟）。
- 用户在临时网页表单里填写账号、密码、人工验证码；插件后端代理拉取站点验证码图片。
- 登录成功后只保存匹配域的 Cookie，并按配置加密写入 SQLite；账号密码不落库、不打日志。
- 链接超时、提交失败、用户取消都会有明确的页面提示和聊天回执。
- `/spbindcookie <cookie>` 支持管理员直接保存 Cookie。
- `/spstatus` 查看当前用户绑定状态。
- `/spunbind` 删除当前用户凭证。
- Dashboard 插件 Page 提供管理员凭证 CRUD。

## 开发与运行

本插件位于 AstrBot runtime：

```bash
/Users/flanchan/Development/SourceCode/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_south_plus
```

启动 AstrBot：

```bash
cd /Users/flanchan/Development/SourceCode/GithubProjects/astrbot-plugin-dev
astrbot run -r -p 6196
```

## 插件结构

- `main.py`：AstrBot 命令、Web API 注册与生命周期协调。
- `src/api/`：**对 South Plus 站点逆向得到的接口、数据模型与常量**（URL、表单字段、cookie 命名、成功/失败判定）。站点改版时只改这一层。
- `src/core/`：与站点解耦的框架代码（登录表单 server、SQLite data source、通用 datamodels、配置、日志）。
- `src/shared/`：项目级共享常量（`PLUGIN_NAME`、日志前缀等非抓包常量）。
- `src/utils/`：无状态工具子包（`crypto / text / timeutil / url`），通过 `from src.utils import ...` 统一引用。
- `pages/credentials/`：Dashboard 凭证管理页面。
- `docs/`：维护、开发、安全说明，以及 `docs/southplus-capture.md`——South Plus 抓包流程与最近一次抓包结果（含 Capture 日期约束）。

## 关键配置

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `auth_listen_host` | `127.0.0.1` | 登录 server 监听地址。 |
| `auth_listen_port` | `0` | 监听端口，0 表示随机。 |
| `auth_base_url` | 空 | 公网展示根地址，公网部署必须填 HTTPS 反代后的根。 |
| `auth_token_ttl_seconds` | `600` | 登录链接有效期（秒）。 |
| `cookie_encryption_key` | 空 | Cookie 加密 key；留空时明文存储（仅推荐本机调试）。 |
| `user_agent` | 空 | 留空时使用 `src/api/constants.py::DEFAULT_USER_AGENT`；反爬升级时可覆盖。 |

> South Plus 站点本身的 URL、cookie 域、表单字段等抓包结论硬编码在 `src/api/constants.py`，不暴露给 Dashboard 配置——改 South Plus 需要走"重新抓包 → 更新 `docs/southplus-capture.md` 的 Capture 日期 → 改 `src/api/`"的流程，不是改 Dashboard。

## 临时登录链接

默认监听 `127.0.0.1` 的随机端口。要让远程用户打开链接，请：

1. 把 `auth_listen_host` 改为可被反代访问的地址（或保持 `127.0.0.1` 由反代回源）。
2. 把 `auth_listen_port` 设为固定端口。
3. 把 `auth_base_url` 设为反代后的 HTTPS 根地址（不带尾斜杠）。

## 安全说明

- 账号、密码只在单次请求驻留内存，不写入 SQLite。
- 登录链接使用随机 token，提交成功后立即失效。
- 未提交的链接按 `auth_token_ttl_seconds` 失效并通知用户。
- `cookie_encryption_key` 配置后，SQLite 中的 Cookie 字段以 v1 加密格式存储；丢失 key 等同丢失 Cookie。
- Dashboard Page 依赖 AstrBot Dashboard 鉴权，适合管理员管理凭证。
