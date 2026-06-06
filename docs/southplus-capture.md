# South Plus 抓包与逆向流程

> **Capture 日期：2026-06-04**（关键字状态机扩容：apply 阶段加入 `"拒离" / "还没超过" / "已经完成" / "已完成"` 等 state-C 别名（覆盖 18 小时冷却拒绝消息）；apply NEEDS_COLLECT 中移除 `"申请["`，避免被冷却消息 `"拒离上次申请[日常]..."` 错配；collect 阶段把 `"未申请任务!"` / `"你已经完成!"` 一并归到 state-C，统一向用户输出"请勿重复签到"，不再判 FAILED——回应"用户在站点手动签到 + 领取后再触发 /spcheckin"的合法场景。）
>
> **维护规则（仅适用于本文档）**
> - 每次重新抓包，无论结果是否变化，都必须更新顶部 "Capture 日期" 为当次抓包的日期 (YYYY-MM-DD)。
> - 修改本文档的"工具与前置条件"、"步骤"、"当前抓包结果"、"如何把结果落到代码"任何一节，都必须同步更新该日期。
> - 只读修改（修正错别字、调整排版、补充注释而不改抓包结果）也必须更新日期；这样可以把"文档与站点真实状态有多新"压缩成一个易读字段。
> - `docs/` 其他文档不适用该规则。

## 这份文档存在的目的

本插件的 `src/southplus/api/` 包封装了对 South Plus 站点的 HTTP 调用。所有 URL、表单字段、cookie 命名、成功/失败判定、验证码格式都是逆向得来的，South Plus 改版时会失效。本文档记录：

1. 当前 `src/southplus/api/` 反映的是哪一天抓包的结果。
2. 任何接手的人（维护者或 agent）如何零账号、零先验地重做一次抓包。
3. 抓包结论应该如何映射到 `src/southplus/api/` 的具体符号。
4. 验证抓包结果是否仍然有效的方法。

读懂这份文档应当足以独立完成"South Plus 改版 → 重新抓包 → 更新 src/southplus/api/ → 跑测试通过"的全流程。

## 工具与前置条件

| 项 | 说明 |
| --- | --- |
| 本机 HTTP 代理 | `http://127.0.0.1:7890`（macOS 上 Clash/Mihomo 默认端口）；用于穿透 Cloudflare 和地域限制。 |
| Playwright (MCP) | 用于打开登录页、执行 `page.evaluate(...)` 抓取表单结构和验证码 fetch。 |
| `curl` | 用于离开浏览器后再确认 Set-Cookie、Content-Type 等响应头。 |
| 浏览器 DevTools | 后备方案，当 Playwright MCP 不可用时手工抓。 |
| 真实账号 | **非必须**。只在采集"失败页面中文关键字"时才需要；可以用一次性测试账号或不做（保留默认关键字）。 |
| 目标 URL | 默认 `https://www.south-plus.net`；镜像如 `https://bbs.south-plus.org` 字段一致但 cookie 前缀可能不同。 |

> 安全约束：**抓包过程不得提交真实主账号密码**。需要时使用一次性测试账号。

## 步骤 1：连通性确认

```bash
PROXY=http://127.0.0.1:7890
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

for url in \
    https://www.south-plus.net/ \
    https://bbs.south-plus.org/ ; do
  curl -sS -x "$PROXY" -A "$UA" -o /dev/null \
    -w "host=%{url_effective} code=%{http_code} time=%{time_total}\n" \
    -L --max-time 20 "$url"
done
```

- 期望：至少有一个镜像返回 `200`。
- 如果两个都超时，先排查代理可用性，再考虑站点是否整体不可用。

## 步骤 2：登录页 HTML 与表单结构

用 Playwright 打开 `/login.php`，然后 evaluate 抓取所有 `<form>`：

```js
() => {
  const forms = Array.from(document.querySelectorAll('form'));
  return forms.map(f => ({
    action: f.getAttribute('action'),
    method: f.getAttribute('method'),
    name: f.getAttribute('name'),
    fields: Array.from(f.elements).map(el => ({
      tag: el.tagName,
      type: el.type,
      name: el.name,
      value: el.value,
      checked: el.checked,
    })),
    html: f.outerHTML,
  }));
}
```

记录：

- form `action` 是否还是 `login.php?`、method 是否仍是 POST。
- 隐藏字段：当前为 `forward / jumpurl / step`。新增字段（例如 CSRF token）必须落到 `LoginRequest` 或 `SouthPlusLoginAttempt.submit`。
- 用户字段：当前为 `gdcode / lgt / pwuser / pwpwd / hideid / cktime / submit`。任一字段重命名都要更新 `LoginRequest`。
- 默认值（`lgt=0`、`hideid=0`、`cktime=31536000` 等）若变化，更新 `LoginRequest` 默认值。

如果出现 `<script>` 计算的动态字段（如基于时间的 nonce、本地 hash 的 fingerprint），必须新增 JS 反向工程小节并在 `client.py` 里复现，**不要**直接读默认值跳过。

## 步骤 3：验证码图片探测

> ⚠️ **关键陷阱**：直接 `fetch('/ck.php?')`（或带任意自造 query，例如 `_=xxx`）会返回**淡水印**图（"WS / sgw" 之类的浅色背景），看着像是 PNG 但完全无法辨认。South Plus 用 query 形态区分"前端真用户点开 vs 后端直接探测"——**必须**用 `ck.php?nowtime=<毫秒时间戳>` 才能拿到带数字的清晰验证码。
>
> phpwind 前端逻辑：用户聚焦 `gdcode` input 触发 `opencode('menu_gd', this)`，把 `<img id=ckcode>` 的 src 改为 `ck.php?nowtime=<Date.now()>` 并显示。

仍在 Playwright 浏览器上下文里 evaluate：

```js
async () => {
  // 反例：拿到的是水印，看不清字符
  const watermark = await fetch('https://www.south-plus.net/ck.php?', {credentials: 'include'});
  // 正例：phpwind 前端真实发出的请求
  const real = await fetch('https://www.south-plus.net/ck.php?nowtime=' + Date.now(),
                           {credentials: 'include'});
  const realBuf = await real.arrayBuffer();
  return {
    realStatus: real.status,
    contentType: real.headers.get('content-type'),
    realBytes: realBuf.byteLength,
    realFirstBytesHex: Array.from(new Uint8Array(realBuf).slice(0, 16))
      .map(b => b.toString(16).padStart(2, '0')).join(''),
    watermarkStatus: watermark.status,
  };
}
```

- 期望首字节 `89504e47...`（PNG 魔数）。
- 期望 `realBytes` 在每次调用都不同（说明每次返回新图，验证码是服务端生成的）。
- **必须人工解码 `/tmp/ck_real.png` 看一眼图**——South Plus 既会"返回 200 + PNG 但内容是水印"也会"返回 200 + PNG 内容是真验证码"，HTTP 层面看不出区别。
- 若 contentType 改成 `image/png`、`image/jpeg` 等，更新 `SouthPlusLoginAttempt.fetch_captcha` 的 `if "image" not in content_type ...` 分支。
- 若 query 形态变化（`nowtime` 改名 / 改加密 / 改成 token），更新 `SouthPlusLoginAttempt.fetch_captcha` 的 `params={"nowtime": ...}`。
- 若出现 base64 内嵌、SVG 滑块、JS challenge、行为验证码 → **停止抓包**，把发现写回本文档"反爬"节并向上游汇报；不要绕过任何反爬措施。

## 步骤 4：cookie 行为确认

`document.cookie` 看不到 `HttpOnly` cookie，必须用 `curl` 抓响应头：

```bash
PROXY=http://127.0.0.1:7890
JAR="$(mktemp)"

echo '== GET /login.php =='
curl -sS -x "$PROXY" -A "$UA" -c "$JAR" -D - -o /tmp/sp_login.html \
  --max-time 30 'https://www.south-plus.net/login.php' | head -30

echo '== GET /ck.php (复用 jar) =='
curl -sS -x "$PROXY" -A "$UA" -b "$JAR" -c "$JAR" -D - -o /tmp/sp_captcha.bin \
  --max-time 30 'https://www.south-plus.net/ck.php?' | head -30

file /tmp/sp_captcha.bin
```

记录：

- 站点 cookie 前缀（当前 `eb9e6_`）。镜像不同 cookie hash 不同。
- 首次 GET 下发的 cookie（当前 `<prefix>_lastvisit`）。
- 验证码请求是否绑定 session（当前无 PHPSESSID，验证码可能基于 IP + cookie 一起绑定，或者 phpwind 内部 hash）。
- **登录成功时下发的 cookie**：当前为 `<prefix>_winduser / <prefix>_winduid / <prefix>_windpwd`。`SouthPlusLoginAttempt` 的 `_has_phpwind_login_cookie` 通过判断 `_winduser` / `_winduid` 后缀认定登录成功，若 phpwind 改命名（极少见）必须同步。

## 步骤 5：失败响应文案采集（可选，需测试账号）

如果有一次性测试账号，提交故意错误的字段，记录响应中的中文关键字。当前关键字表（按优先级）：

| 关键字 | 用户可见信息 |
| --- | --- |
| `认证码` / `验证码` | 验证码错误或站点要求验证码，请刷新验证码后重试。 |
| `密码错误` / `密码不正确` | 账号或密码错误。 |
| `用户名不存在` | 账号不存在。 |
| `账号被锁定` | 账号被站点锁定。 |
| `登录次数` | 登录失败次数过多，请稍后再试。 |

若 South Plus 把错误文案换成英文或换字（例如 "验证码错误" → "验证码不正确"），更新 `src/southplus/api/login.py::_classify_failure`。

## 步骤 6：登录跳转与登录后页面（可选）

登录成功后 phpwind 一般返回 200 + meta-refresh 跳到 `index.php`。校验登录态的方法：带 cookie GET `/index.php`，看页面里是否出现 `退出` 链接。当前 `_looks_login_page` 的逻辑就是反着判断：

- URL 还含 `login.php` → 没登录
- 正文含 `登录` 且不含 `退出` → 没登录

更换 verify URL 时同步更新 `SouthPlusEndpoints.verify_url` 默认值。

## 当前抓包结果（2026-06-03）

### 端点

| 项 | 值 |
| --- | --- |
| 登录 POST URL | `{site_base_url}/login.php?`（method=POST，name=login） |
| 验证码 GET URL | `{site_base_url}/ck.php?nowtime=<毫秒时间戳>`（**必须用 `nowtime` 名字**，否则返回水印背景） |
| 登录态校验 URL | `{site_base_url}/index.php` |
| 主站 site_base_url | `https://www.south-plus.net` |
| 镜像示例 | `https://bbs.south-plus.org` |

### 表单字段

| 字段 | 当前默认值 | 含义 | 是否敏感 |
| --- | --- | --- | --- |
| `forward` | 空 | 登录后跳转参考；保持空。 | 否 |
| `jumpurl` | `{site_base_url}/index.php` | 登录后默认跳转 URL。 | 否 |
| `step` | `2` | phpwind 多步流程标记；登录用 2。 | 否 |
| `gdcode` | 空 | 验证码答案（用户填）。 | 否 |
| `lgt` | `0` | 0=用户名, 1=UID, 2=Email。 | 否 |
| `pwuser` | 空 | 用户名/UID/邮箱（用户填）。 | **是** |
| `pwpwd` | 空 | 密码（用户填）。 | **是** |
| `hideid` | `0` | 0=显示在线, 1=隐身登录。 | 否 |
| `cktime` | `31536000` | cookie TTL 秒；可选 31536000/2592000/86400/3600/0。 | 否 |
| `submit` | `登 录` | submit 按钮值；phpwind 校验存在。 | 否 |

### Cookie 行为

| 状态 | 站点下发 cookie |
| --- | --- |
| 首次 GET `/login.php` | `<prefix>_lastvisit` |
| GET `/ck.php` | 追加 `<prefix>_lastpos`，更新 `lastvisit` |
| 登录成功 POST `/login.php` | `<prefix>_winduser` (URL-encoded 用户名)、`<prefix>_winduid` (用户 ID)、`<prefix>_windpwd` (密码 hash) |

**站点 cookie 前缀**：当前主站为 `eb9e6_`。镜像可能不同，因此代码用后缀匹配 `_winduser` / `_winduid` 判定登录成功，不写死前缀。

### 反爬

- Cloudflare 在前，普通 UA + 本机代理可直接穿透；没有强制 JS challenge 或滑块。
- 没有发现 CSRF token、frontend 加密、device fingerprint。
- 若 Cloudflare 升级到 Turnstile / Managed Challenge，本流程失效，需要换浏览器自动化方案。

### 成功 / 失败判定

| 判定 | 实现位置 | 当前逻辑 |
| --- | --- | --- |
| 登录成功 | `src/southplus/api/login.py::_has_phpwind_login_cookie` 读 `constants.LOGIN_COOKIE_NAME_SUFFIXES` | cookie jar 出现 `*_winduser` 或 `*_winduid` |
| Cookie 未生效 | `src/southplus/api/login.py::_looks_login_page` | URL 含 `login.php` 或正文含 `登录` 且不含 `退出` |
| 失败原因分类 | `src/southplus/api/login.py::_classify_failure` 读 `constants.FAILURE_KEYWORDS` | 见步骤 5 关键字表 |
| 验证码字节合法 | `src/southplus/api/login.py::SouthPlusLoginAttempt.fetch_captcha` | content-type 含 `image/` 或字节以 `\x89PNG` 起头 |

## 如何把抓包结果落到代码

`src/southplus/api/` 是抓包结论的唯一权威。改动按下表对号入座：

| 抓包结论 | 落点 |
| --- | --- |
| 站点默认 URL / 路径 / UA | `src/southplus/api/constants.py::DEFAULT_SITE_BASE_URL / DEFAULT_LOGIN_PATH / DEFAULT_CAPTCHA_PATH / DEFAULT_VERIFY_PATH / DEFAULT_USER_AGENT` |
| 表单 user-selectable 默认值 | `src/southplus/api/constants.py::DEFAULT_LOGIN_TYPE / DEFAULT_HIDE_ID / DEFAULT_COOKIE_TTL`（同时是 `LoginRequest` 字段默认） |
| 表单 hidden 字段默认值 | `src/southplus/api/constants.py::DEFAULT_FORM_FORWARD / DEFAULT_FORM_STEP / DEFAULT_FORM_SUBMIT`（被 `SouthPlusLoginAttempt.submit` 消费） |
| 登录请求模型 | `src/southplus/models.py::LoginRequest`（字段名与 phpwind 表单 1:1 映射） |
| 登录结果模型 | `src/southplus/models.py::LoginResult / CaptchaPayload` |
| 端点工厂 | `src/southplus/models.py::build_endpoints`——把用户配置补齐为 `SouthPlusEndpoints`；`config_manager` 仅负责把配置喂进去 |
| 登录字段映射（构造 POST body） | `src/southplus/api/login.py::SouthPlusLoginAttempt.submit` |
| 登录成功 cookie 后缀 | `src/southplus/api/constants.py::LOGIN_COOKIE_NAME_SUFFIXES`（被 `_has_phpwind_login_cookie` 消费） |
| 失败关键字表 | `src/southplus/api/constants.py::FAILURE_KEYWORDS`（顺序 = 优先级；被 `_classify_failure` 消费） |
| 登录态 URL/正文判定 | `src/southplus/api/login.py::_looks_login_page` |
| 验证码字节合法性 | `src/southplus/api/login.py::SouthPlusLoginAttempt.fetch_captcha` |
| cookie 域过滤 | `src/southplus/client.py::_cookie_header` + `SouthPlusEndpoints.cookie_domains` |
| 用户可配项 | `_conf_schema.json` 中的 `southplus_*` / `site_base_url` / `user_agent` 字段——只声明 schema，**不写抓包默认值**；空值由 `build_endpoints` 兜底 |

每次修改 `src/southplus/api/`：

1. 同步更新本文档"当前抓包结果"小节。
2. 同步更新本文档顶部 **Capture 日期**（哪怕只是落点重命名也要更新——日期反映"文档与代码状态的对齐时间戳"）。
3. 同步更新 `tests/conftest.py` 的 mock South Plus server（让 mock 行为与真实站点一致）。
4. 跑 `python -m pytest`，确保所有 client / auth_server 测试通过。

## 社区签到接口（plugin.php tasks）

> 参考实现：[`MeYangGe/SouthPlusQianDao`](https://github.com/MeYangGe/SouthPlusQianDao) 的 `APPLYDAILY.py / COLLECTDAILY.py / APPLYWEEKLY.py / COLLECTWEEKLY.py`。

南+ 的"社区论坛任务"位于 `https://bbs.south-plus.org/plugin.php?H_name-tasks.html`，由"进行中任务 / 已完成任务 / 失败任务"三个 tab 表达状态。可见入口：

| URL | 含义 |
| --- | --- |
| `plugin.php?H_name-tasks-actions-newtasks.html.html` | 进行中任务（state B）。也是签到唯一入口的 Referer。 |
| `plugin.php?H_name-tasks-actions-endtasks.html.html` | 已完成任务（state C）。verify 阶段的语义对应物。 |
| `plugin.php?H_name-tasks-actions-errotasks.html.html` | 失败任务。落到这里的就不算成功（当前实现不直接访问该页，靠 verify 反推）。 |

| 任务 | cid |
| --- | --- |
| 日常签到 | `15` |
| 周常签到 | `14` |

### 任务状态机（phpwind tasks）

| 状态 | 含义 | 所在 tab |
| --- | --- | --- |
| **A** | 未申请 | 不在 newtasks / endtasks |
| **B** | 已申请未领取 | newtasks（进行中） |
| **C** | 已领取（完成）；常伴 18 小时冷却拒绝 | endtasks（已完成） |

一次完整签到必须把任务从 A 推到 C。**用户在站点手动完成签到**等同于把任务直接推到 C，此时本插件再触发 /spcheckin 会被 phpwind 反映为以下任意一种 state-C 文案，全部按 ALREADY_DONE 处理（向用户提示"请勿重复签到"）：

| 阶段 | 抓包到的 state-C 文案 | 关键字命中 |
| --- | --- | --- |
| apply | `请勿重复申请,该任务已完成!` | `请勿重复` / `已完成` |
| apply | `拒离上次申请[日常]还没超过 18 小时` | `拒离` / `还没超过` |
| apply | `本周已完成签到任务,请勿重复申请!` | `本周已完成` / `已完成` |
| collect | `你[日常]已经完成!` | `已经完成` / `已完成` |
| collect | `请勿重复申请,该任务已完成!` | `请勿重复` / `已完成` |
| collect | `未申请任务!\t14`（任务已不在 progress 列表的副作用） | `未申请` |

### 三段动作（apply → collect → verify）

| 步骤 | URL params | 期望状态迁移 |
| --- | --- | --- |
| apply | `H_name=tasks&action=ajax&actions=job&cid=<cid>&nowtime=<ms>&verify=5af36471` | A → B；B → B；C → C（重入幂等） |
| collect | `H_name=tasks&action=ajax&actions=job2&cid=<cid>&nowtime=<ms>&verify=5af36471` | B → C；A → 报错"未申请"；C → 报错"请勿重复" |
| **verify** | 再调一次 `apply` | 期望响应命中 state-C 关键字，证明 endtasks 列表里能查到本任务 |

verify 通过"再次 apply 看响应是否为 state-C"实现，等价于"用户在浏览器里打开 endtasks 页能看到本任务"。这样既满足用户要求"签到必须真的领到完成列表里才算成功"，又不需要额外请求 / 解析 HTML 列表。

GET，cookie 必带 `eb9e6_winduser` 等登录 cookie，UA 与登录抓包同。

### 响应解析

`<root><![CDATA[ action\tmessage[\textra] ]]></root>`。`action` 暂未消费；`message` 是面向用户的中文文案；`extra` 在 collect 阶段可能携带具体奖励额度（拼接到成功消息尾部）。

### 关键字判定（按状态机）

关键字检测顺序固定为：

* **apply**：登录态 → state-B (NEEDS_COLLECT) → state-C (ALREADY_COLLECTED) → 兜底 FAILED；
* **collect**：登录态 → state-C (ALREADY_DONE) → 刚领取 (SUCCESS) → 兜底 FAILED；
* **verify**：登录态 → state-C (ALREADY_COLLECTED) 视为 SUCCESS → 兜底 FAILED。

所有关键字来自抓包 / 参考仓库观察到的原始中文文案，匹配用 `in`。表与 `src/southplus/api/constants.py` 一一对应。

| 关键字常量 | 阶段 | 命中含义 | 关键字举例 |
| --- | --- | --- | --- |
| `NOT_LOGGED_IN_TASK_KEYWORDS` | apply / collect / verify | Cookie 已失效，整体 FAILED 并提示重新 /splogin | `还没有登录`、`暂时不能使用此功能` |
| `APPLY_NEEDS_COLLECT_KEYWORDS` | apply | state-B：继续走 collect + verify | `请赶紧`、`去完成`、`申请成功`、`进行中` |
| `APPLY_ALREADY_COLLECTED_KEYWORDS` | apply / verify | state-C：apply 阶段命中 → ALREADY_DONE 短路；verify 阶段命中 → SUCCESS 确认 | `请勿重复`、`已领取`、`已经完成`、`已完成`、`拒离`、`还没超过`、`本周已完成`、`今天已完成` |
| `COLLECT_ALREADY_DONE_KEYWORDS` | collect | state-C：用户已外部完成 / cooldown / 任务从 progress 列表消失 → ALREADY_DONE，输出"请勿重复签到" | `请勿重复`、`已领取`、`已经完成`、`已完成`、`未申请`、`拒离`、`还没超过` |
| `COLLECT_SUCCESS_KEYWORDS` | collect | state-B → C：刚领取成功 | `获得`、`奖励`、`成功`、`领取` |

**关键陷阱 / 设计决定**：

* 不要把 `"申请["` 放进 `APPLY_NEEDS_COLLECT_KEYWORDS`——冷却消息 `"拒离上次申请[日常]还没超过 18 小时"` 也含此串，会把 state-C 错配为 state-B。state-B 文案 `"申请[日常]任务完成,请赶紧去完成任务吧!"` 已被 `"请赶紧 / 去完成"` 覆盖，不需要 `"申请["`。
* 不要把 `"完成"` 放进 `COLLECT_SUCCESS_KEYWORDS`——state-C 文案 `"你[日常]已经完成!"` 同样含 `"完成"`。collect 阶段必须 ALREADY_DONE 先于 SUCCESS 检查。
* `COLLECT_REQUIRES_APPLY_KEYWORDS` 已被废弃为空 tuple。phpwind 在 state-C 场景同样会返回 `"未申请任务!"`（任务已不在 progress 列表的副作用），按 `FAILED` 处理会误伤"用户已手动签到"的合法用例；现统一归到 `COLLECT_ALREADY_DONE_KEYWORDS`。
* ALREADY_DONE 的用户可见消息固定为 `"<label>：已签到，请勿重复签到。"`——不向用户暴露站点原文，避免 `"未申请任务!"` 之类的反直觉文案直达用户。
* verify 必须命中 `APPLY_ALREADY_COLLECTED_KEYWORDS`；如果仍返回 state-B 文案，无论 collect 自报多成功都判 FAILED，并把 collect / verify 两段原文一起塞 `error`。

### 失败兜底

| 触发 | 落到 |
| --- | --- |
| 任意阶段都不命中关键字 | `FAILED`，message 包含阶段名 + 站点原文，error 保留 raw_body |
| `<root>` parse 失败 | `FAILED`（视为 message=raw 文本，走兜底分支） |
| 网络异常 | `FAILED`，message 提示"网络错误"，error 保留 `httpx` repr |
| Cookie 失效 | `FAILED`，message 提示"Cookie 已失效，请重新 /splogin" |

### verify 字段 / nowtime 字段

* `verify=5af36471`：参考仓库观察到是固定值，似乎暂未做严格校验；保留为常量 `DEFAULT_CHECKIN_VERIFY`。若改版后出现 401 / 拒绝，应改为预先 GET tasks 页面解析 token。已在 `src/southplus/api/constants.py` 上方挂 TODO。
* `nowtime`：`int(time.time() * 1000)`，毫秒整数。参考仓库直接用固定时间戳也能跑——证明 nowtime 当前未强校验。

### 落点

| 抓包结论 | 落点 |
| --- | --- |
| 任务 URL / Referer | `src/southplus/api/constants.py::TASKS_NEW_URL / TASKS_END_URL / TASKS_ERRO_URL / TASKS_REFERER` |
| 任务 ID | `src/southplus/api/constants.py::DAILY_CID / WEEKLY_CID` |
| 动作名 | `src/southplus/api/constants.py::ACTION_APPLY / ACTION_COLLECT` |
| verify 常量 | `src/southplus/api/constants.py::DEFAULT_CHECKIN_VERIFY` |
| 状态机关键字 | `src/southplus/api/constants.py::*_KEYWORDS`（见上表） |
| apply → collect → verify 主流程 | `src/southplus/checkin_service.py::run_checkin` |
| 单任务安全包装（吃异常） | `src/southplus/checkin_service.py::_safe_run` |
| 日 + 周门面 | `src/southplus/checkin_service.py::CheckinService` |

## 验证抓包结果是否仍然有效

不重做完整抓包时，可以做一次"低破坏面"的探测：

```bash
PROXY=http://127.0.0.1:7890
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

# 1. 登录页是否还存在
curl -sS -x "$PROXY" -A "$UA" -o /tmp/sp_login.html \
  -w "code=%{http_code}\n" 'https://www.south-plus.net/login.php'

# 2. 表单字段是否仍是预期集合
grep -oE 'name="[^"]+"' /tmp/sp_login.html | sort -u

# 3. 验证码是否仍是 PNG
curl -sS -x "$PROXY" -A "$UA" -o /tmp/sp_captcha.bin \
  'https://www.south-plus.net/ck.php?'
file /tmp/sp_captcha.bin
```

预期：步骤 2 列出的 `name=` 集合是 `forward, jumpurl, step, gdcode, lgt, pwuser, pwpwd, hideid, cktime, submit` 的超集；步骤 3 报告 PNG。任一不符合就要回到完整抓包流程。
