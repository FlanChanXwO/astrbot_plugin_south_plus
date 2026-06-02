# 开发记录

## 初始化

先尝试使用：

```bash
astrbot plug new astrbot_plugin_south_plus
```

但 GitHub 模板 zip 下载阶段超时，因此手工生成等价 AstrBot 插件骨架。

## 验证命令

在插件目录运行：

```bash
python -m compileall .
python -m pytest
ruff check .
```

## 代码组织

插件根目录只保留 `main.py` 作为 AstrBot 入口。其它运行时代码按职责分四个包：

### `src/api/`——South Plus 逆向产物

`src/api/` 的所有代码都来自对 South Plus 站点的抓包。详细抓包流程与"当前结果"见 [`docs/southplus-capture.md`](./southplus-capture.md)。

- `constants.py`：**抓包结论的唯一权威**。包含 `DEFAULT_SITE_BASE_URL`、`DEFAULT_LOGIN_PATH / CAPTCHA_PATH / VERIFY_PATH`、`DEFAULT_USER_AGENT`、`DEFAULT_LOGIN_TYPE / HIDE_ID / COOKIE_TTL / FORM_FORWARD / FORM_STEP / FORM_SUBMIT`、`LOGIN_COOKIE_NAME_SUFFIXES`、`FAILURE_KEYWORDS`。
- `models.py`：`SouthPlusEndpoints / LoginRequest / LoginResult / CaptchaPayload`，以及 `build_endpoints(...)` 工厂——根据 `constants.py` 把用户传入的不完整端点补齐为完整 `SouthPlusEndpoints`。
- `client.py`：
  - `SouthPlusClient`：无状态门面，`new_attempt()` 返回单次登录会话；`check_cookie(cookie)` 直接校验已有 cookie。
  - `SouthPlusLoginAttempt`：单次登录会话，复用 httpx cookie jar 跨 captcha + submit。
  - `_classify_failure / _looks_login_page / _has_phpwind_login_cookie / _cookie_header`：协议层判定函数，全部跟随抓包结论（直接消费 `constants.py` 暴露的常量）。

> **任何 South Plus 改版（字段、URL、cookie、错误关键字）都只改这一层，并且必须同步更新 `docs/southplus-capture.md` 顶部的 Capture 日期。**

### `src/core/`——插件框架层

不依赖 South Plus 任何细节。

- `auth_server.py`：一次性登录表单 HTTP server，状态机 / 验证码代理 / 提交 / 取消。仅通过 `SouthPlusClient` 与南+交互。
- `data_source.py`：SQLite 凭证表初始化、CRUD；写入/读取 Cookie 用 `utils.crypto` 透明加解密。
- `datamodels.py`：`CredentialSession / StoredCredential / AuthServerConfig / PluginConfigSnapshot`。
- `config_manager.py`：读取 `_conf_schema.json`，把用户配置喂给 `api.build_endpoints`；本身不持有任何抓包知识。
- `logger.py`：带 `[astrbot_plugin_south_plus]` 前缀的日志门面（前缀来自 `shared.constants`）。

### `src/shared/`——项目级共享常量

非抓包、跨包共用的常量集中地。

- `constants.py`：`PLUGIN_NAME`、`LOG_PREFIX`。后续若有别的"项目级身份"常量（例如统一 Web API 路径前缀）也放这里。

### `src/utils/`——无状态工具

完全独立、无副作用、无项目耦合的纯函数。

- `crypto.py`：`encrypt_secret / decrypt_secret`（HMAC-SHA256 派生密钥流 + MAC）。
- `text.py`：`mask_secret / generate_token`。
- `timeutil.py`：`now_iso / expires_at_after`。
- `url.py`：`join_url / derive_default_endpoint / parse_cookie_domains / derive_cookie_domains_from_url`。
- `__init__.py`：集中 re-export，下游统一通过 `from src.utils import ...` 引用。

## 包依赖方向

```
main.py
  ├──> src.api.{client, models}
  ├──> src.core.{auth_server, config_manager, data_source, datamodels, logger}
  ├──> src.shared.constants
  └──> src.utils (re-export)

src.core.* ──> src.api.{models, client}
src.core.* ──> src.shared.constants
src.core.* ──> src.utils

src.api.{models, client} ──> src.api.constants
src.api.{models, client} ──> src.utils  # 仅 url/text 等无副作用工具

src.shared, src.utils 不向上依赖任何包。
```

允许：上层（`main`、`core`）依赖下层（`api`、`shared`、`utils`）。
禁止：`api` 依赖 `core`；任何包反向依赖 `main`。

## 测试结构

- `tests/conftest.py` 启动 mock South Plus HTTP server，返回 PNG 验证码、登录 form HTML、登录 POST 校验、Set-Cookie 模拟。**当 `src/api/` 改动时，必须同步改这里**——否则 client 测试虽然过了，真实站点仍然挂。
- `tests/test_utils.py` 验证 cookie 加解密、URL 拼接、域名解析、token 熵。
- `tests/test_config_manager.py` 验证 schema 默认值、端点推导、cookie 域推导。
- `tests/test_client.py` 用 mock server 测试 `SouthPlusClient.new_attempt()`、`fetch_captcha`、`submit` 的成功/验证码错/密码错路径。
- `tests/test_auth_server.py` 测试 form 页面渲染、验证码代理、登录提交、空字段、过期、取消、并发去重。
- `tests/test_data_source.py` 测试明文与加密存储、跨 key 解密失败的降级。
