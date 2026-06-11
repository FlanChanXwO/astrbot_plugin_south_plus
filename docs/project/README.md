# 项目概览 — astrbot_plugin_south_plus

South Plus 凭证与任务自动化 AstrBot 插件。

## 能力说明

- `/splogin` — 生成一次性临时登录链接，在网页表单完成账号/密码/验证码提交。首次绑定成功时若插件开启了自动签到，会附加提示。
- `/spprofile` — 抓取当前激活账号的资料并渲染 HTML+t2i 卡片（头像 + 14 项数值）。
- `/spcheckin` — 日签（cid=15）+ 周签（cid=14），已签期直接提示请勿重复签到。
- `/spuidlist` / `/spswitch` / `/spdelete` — 多 UID 绑定、切换、删除。
- `/spbindcookie` — 直接用 Cookie 绑定（拉 profile 取 UID 入库）。
- `/spstatus` — 查看当前激活账号状态。
- `/spautocheckin` — 切换当前激活账号的自动签到开关。
- `/spsubcheckin` / `/spunsubcheckin` — 订阅/取消订阅当前会话的**当前账号**签到汇报推送。
- `/spcheckinallsub`（别名 `/sp全局签到订阅`）— 管理员订阅或取消当前会话的**全部账号**签到汇报推送。
- `/spallcheckin` — 管理员立即执行全部绑定账号签到，返回全体账号统计。
- `/spcleanup`（别名 `/sp清理`）— 管理员清理退群或非好友用户的绑定数据。
- Dashboard Plugin Pages — 管理员管理账号、群组、调度任务、用户-群关系与签到历史。

主动签到返回统一状态格式：`/spcheckin` 显示单个 UID 的日签/周签状态，`/spallcheckin` 显示全部账号的账号数、完成数与日签/周签三态统计；已签过的项目显示 `请勿重复签到`，不暴露本地缓存细节。

自动签到订阅推送会在标题区分范围：全局订阅显示 `South Plus 自动签到（全局订阅）`，会话订阅显示 `South Plus 自动签到（会话订阅）`。正文按参与账号数、完成账号数、日签/周签三态统计输出；本轮有效签到流程经 verify 确认完成、或本地可信 `success` 缓存计入 `✅`，本轮开始前站点已签或本地可信 `already_done` 缓存计入 `⏭️`，失败计入 `❌`。日签和周签均未失败的账号计入完成，任一维度失败时仍会按原逻辑 @ 对应账号。

订阅命令只变更后续定时汇报的订阅状态，不会立即执行签到；需要立即执行时使用 `/spcheckin` 或管理员命令 `/spallcheckin`。

## 架构分层

```
main.py              AstrBot 命令注册与生命周期
src/southplus/       South Plus 逆向层（URL、表单、cookie、解析）
  api/               唯一对外接口层
src/core/            框架代码（config、datamodels、db、checkin_scheduler）
  db/                SQLite 持久化（5 个 Store + 版本化迁移）
    migrations/      V{N}_{描述}.py 迁移脚本
src/web/             HTTP 层（auth server + 静态模板）
src/pages/           Plugin Pages Web API 后端
src/render/          HTML+t2i 卡片渲染
src/shared/          项目级共享常量
src/utils/           无状态工具（events/messages/season/crypto/text/timeutil/url）
pages/               Dashboard Plugin Pages
tests/               pytest 测试套件
docs/                维护与开发文档
assets/              静态资源（logo 等）
```

## Plugin Pages

Dashboard 静态前端位于 `pages/dashboard/`，旧 `pages/credentials/` 仅保留跳转入口。后端 Web API 集中在 `src/pages/` 包中注册和处理，`main.py` 只在完成 store / scheduler 初始化后调用 `register_page_apis(...)`。

管理面只读取或管理插件数据库中的运行态资料：账号、群组、用户-群关系、调度任务与签到历史。登录、验证码、账号密码提交仍走 `/splogin` 一次性登录链路，不放进 Dashboard。

调度任务页的“参与账号”采用会话级排除语义：排除某 UID 只写入 `checkin_session_exclusion(umo, sp_uid)`，只影响该会话的自动签到调度；不修改 `user.auto_checkin`，也不影响同一 UID 在其他会话继续参与或恢复。账号页的自动签到按钮如使用，语义是用户账号自己的全局开关。

列表筛选由 Dashboard 前端组织，服务端 `suggestions` 接口只对账号、群组、调度、签到历史、关系页与参与账号面板的白名单字段返回去重候选；候选项包含 `value/label/kind/meta`，用于前端自绘补全菜单。输入停顿后只刷新当前列表数据，不重建筛选栏或参与账号面板，搜索按钮仍保留为主动刷新入口。

## 数据库迁移

启动时 `setup_db(db_path)` 自动执行所有未应用的 `V{N}_*.py` 脚本（幂等）。
追踪表 `sp_migration_record`，每行记录版本号、应用时间和描述。

当前自动签到相关表：

- `user.auto_checkin`：账号全局自动签到开关，由 `/spautocheckin` 或账号页全局操作修改。
- `schedule`：会话订阅与 cron；插件初始化或重载配置时，会把 `auto_checkin_time` 转换后的 cron 同步到已有 `sp.checkin.*` 订阅。
- `checkin_session_exclusion`：Dashboard 对某个会话的 UID 排除关系。
