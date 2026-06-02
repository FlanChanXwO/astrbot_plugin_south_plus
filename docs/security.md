# 安全约束

- 不在聊天消息中要求用户发送账号密码。
- 临时登录表单的账号、密码只在单次请求内驻留内存，不入库、不打日志。
- 持久化 Cookie 时，若配置了 `cookie_encryption_key`，则用 HMAC-SHA256 派生的密钥流 + HMAC-SHA256 MAC 加密后再写入 SQLite。未配置 key 时退化为明文，仅推荐本机调试。
- Dashboard Page 只展示脱敏 Cookie 值。
- 临时登录链接默认 600 秒有效期（`auth_token_ttl_seconds`），过期后链接失效并通知用户。
- 临时 HTTP server 默认只监听 `127.0.0.1`，公网部署必须放在 HTTPS 反向代理后，且 `auth_base_url` 必须设置为反代后的根地址。
- 验证码图片由插件后端代理拉取，复用同一个 South Plus 会话；插件不做验证码自动识别、破解或绕过。
- 登录失败按真实原因返回（验证码错误、账号或密码错误、账号锁定、登录过频、未知失败），不把失败伪装成成功。
- 登录成功后仅持久化匹配 `southplus_cookie_domains` 域的 Cookie；其他域的 Cookie（如 Cloudflare）不写入数据库。
- 数据库中以南+ **UID 为全局唯一主键**：同一个 UID 不能被两个聊天用户同时绑定，避免聊天端身份冒用南+账号。重复绑定时即使 cookie 合法也直接拒绝写库。
