# astrbot_plugin_south_plus

<div align="center">

**支持社区签到、账号信息查询与定时签到的 SouthPlus AstrBot 插件**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue)
![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.24.0-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20MacOS-lightgrey)

</div>

## 项目简介

`astrbot_plugin_south_plus` 是面向 AstrBot 的 SouthPlus 插件，支持社区签到、账号信息查询，并可按配置开启定时签到。

核心能力：

- **多账号绑定**：同一聊天用户可绑定多个南+ UID，全局唯一持有约束。
- 一次性临时登录链接（默认有效 10 分钟，同平台同用户未过期时复用），网页表单代理拉取站点验证码。
- HTML+t2i 资料卡片（头像、用户名、UID、14 项数值，季节配色）。
- 日签+ 周签。
- Dashboard Plugin Pages 管理员管理账号、群组、调度任务、用户-群关系与签到历史。
  - 调度页“参与账号”可按会话排除/恢复某个 UID 的自动签到，不影响其他会话或账号全局开关。

## 命令速览

| 英文命令 | 中文别名 | 权限 | 说明 |
| --- | --- | --- | --- |
| `splogin` | `sp登陆` | 普通用户 | 生成或复用一次性网页登录链接，登录成功后新增或刷新 UID 绑定。 |
| `spstatus` | `sp状态` | 普通用户 | 查看当前激活账号。 |
| `spuidlist` | `spuid列表` | 普通用户 | 列出当前用户绑定的所有 UID。 |
| `spswitch <uid>` | `sp切换 <uid>` | 普通用户 | 切换当前激活 UID。 |
| `spdelete <uid>` | `sp删除 <uid>` | 普通用户 | 删除当前用户绑定的指定 UID。 |
| `spbindcookie <cookie>` | `sp绑定 <cookie>` | 普通用户 | 直接用 Cookie 绑定账号。 |
| `spprofile` | `sp资料` | 普通用户 | 抓取当前激活账号资料并渲染卡片。 |
| `spcheckin` | `sp签到` | 普通用户 | 对当前激活账号执行日签和周签，返回统一状态格式。 |
| `spautocheckin` | `sp自动签到` | 普通用户 | 切换当前激活账号的自动签到开关。 |
| `spsubcheckin` | `sp订阅签到` | 普通用户 | 订阅当前会话的当前账号签到结果推送。 |
| `spunsubcheckin` | `sp取消签到` | 普通用户 | 取消当前会话的当前账号签到结果推送。 |
| `spcheckinallsub` | `sp全局签到订阅` | 管理员 | 订阅或取消当前会话的全局签到结果推送，统计所有会话订阅参与账号的 UID 并集。 |
| `spallcheckin` | `sp全体签到` | 管理员 | 立即执行全部绑定账号签到，返回全体统计。 |
| `spcleanup` | `sp清理` | 管理员 | 清理退群或非好友用户的绑定数据。 |

自动签到会话订阅只统计当前会话订阅账号；全局订阅统计所有会话订阅参与账号的 UID 并集，同一 UID 多会话订阅只算一次。若尚无任何会话订阅，全局订阅回退为全部启用账号。会话级排除只影响该会话贡献的参与关系，同一 UID 在其他会话仍参与时会继续纳入全局统计。

## 免责声明

本项目仅供学习使用，请勿用于商业用途。使用本插件视为同意提供用户凭据，用户凭据仅用于查询社区数据。使用本插件造成的任何数据滥用行为与作者无关。

## 安装

推荐在 AstrBot 插件市场搜索 `south_plus` 安装。

手动安装：

```bash
cd AstrBot/data/plugins
git clone https://github.com/FlanChanXwO/astrbot_plugin_south_plus.git
```

安装后重启 AstrBot 或重载插件。

## 文档导航

| 文档 | 内容 |
|------|------|
| [开发与维护](docs/dev/maintenance.md) | 包边界、安全边界、文档纪律、迁移规则 |
| [项目概览](docs/project/README.md) | 能力说明与架构分层 |
| [安全说明](docs/dev/security.md) | Cookie 存储、密钥、边界 |

## 关键配置

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `auth_listen_host` | `127.0.0.1` | 登录 server 监听地址。 |
| `auth_listen_port` | `0` | 监听端口，0 表示随机。 |
| `auth_base_url` | 空 | 公网展示根地址，公网部署必须填 HTTPS 反代后的根。 |
| `auth_token_ttl_seconds` | `600` | 登录链接有效期（秒）；同平台同用户重复 `/splogin` 不顺延未过期链接。 |
| `cookie_encryption_key` | 空 | Cookie 加密 key；留空时明文存储（仅推荐本机调试）。 |
| `user_agent` | 空 | 留空时使用内置 UA；站点访问异常时可覆盖。 |

## 临时登录链接

同一平台的同一聊天用户重复执行 `/splogin` 时，若已有未过期且未完成的登录链接，会复用原 token，并按剩余有效期展示；成功、取消或过期后才会生成新 token。若网页表单已经提交并正在处理，重复 `/splogin` 只提示等待结果，不再生成第二条登录链路。

默认监听 `127.0.0.1` 的随机端口。要让远程用户打开链接，请：

1. 把 `auth_listen_host` 改为可被反代访问的地址。
2. 把 `auth_listen_port` 设为固定端口。
3. 把 `auth_base_url` 设为反代后的 HTTPS 根地址（不带尾斜杠）。

## 开发与测试

从插件目录运行：

```bash
python -m compileall .
python -m pytest
ruff check .
```

## 许可证

本项目使用 [GNU Affero General Public License v3.0](LICENSE)。
