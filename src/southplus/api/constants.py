"""South Plus API 常量（抓包结论）。

本文件是所有 API 相关常量的唯一权威来源。改动须同步
``docs/dev/southplus-capture.md`` 顶部的 ``Capture 日期`` 与"当前抓包结果"小节。

放置原则：

* **抓包来的事实**（URL 路径、表单字段默认值、cookie 名后缀、失败关键字、
  站点域名、签到 ID 等）放在本文件。
* **项目级且与站点无关的常量**（``PLUGIN_NAME``、日志前缀等）放在
  ``src/shared/constants.py``。
"""

from __future__ import annotations

# ---- 站点域名 ---------------------------------------------------------------

# 主站：见 docs/dev/southplus-capture.md 的"当前抓包结果 → 端点"。镜像如
# bbs.south-plus.org 字段集一致但 cookie 前缀 hash 不同。
DEFAULT_SITE_BASE_URL = "https://www.south-plus.net"

# 用户截图里 profile.php / plugin.php 的真实入口域名。主域 www.south-plus.net
# 的 profile.php 字段布局不同（截图来自 bbs 镜像）。
BBS_BASE_URL = "https://bbs.south-plus.org"

# ---- phpwind 登录路径 -------------------------------------------------------

DEFAULT_LOGIN_PATH = "login.php"
DEFAULT_CAPTCHA_PATH = "ck.php"
DEFAULT_VERIFY_PATH = "index.php"

# ---- phpwind 登录表单 hidden 字段默认值（抓包步骤 2）-------------------------

DEFAULT_FORM_FORWARD = ""
DEFAULT_FORM_STEP = "2"
DEFAULT_FORM_SUBMIT = "登 录"

# 登录表单 user-selectable 默认值。
DEFAULT_LOGIN_TYPE = "0"  # 0=用户名 / 1=UID / 2=Email
DEFAULT_HIDE_ID = "0"  # 0=显示在线 / 1=隐身登录
DEFAULT_COOKIE_TTL = "31536000"  # 一年；可选 31536000/2592000/86400/3600/0

# 用于通过 Cloudflare 的浏览器风格 UA。改 UA 时建议先在
# docs/dev/southplus-capture.md 步骤 1 复测一次连通性。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# ---- Cookie 判定 ------------------------------------------------------------

# 站点登录成功的 cookie 名后缀（phpwind 通用，前缀是站点 hash）。
LOGIN_COOKIE_NAME_SUFFIXES = ("_winduser", "_winduid")

# ---- 登录失败关键字 ---------------------------------------------------------

# 失败页面中的中文关键字 -> 面向用户的错误信息。顺序即优先级；先匹配
# 验证码错误以引导用户重填验证码。
FAILURE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("认证码", "验证码错误或站点要求验证码，请刷新验证码后重试。"),
    ("验证码", "验证码错误或站点要求验证码，请刷新验证码后重试。"),
    ("密码错误", "账号或密码错误。"),
    ("密码不正确", "账号或密码错误。"),
    ("用户名不存在", "账号不存在。"),
    ("账号被锁定", "账号被站点锁定。"),
    ("登录次数", "登录失败次数过多，请稍后再试。"),
)

# ---- Profile 抓取 -----------------------------------------------------------

BBS_PROFILE_URL = f"{BBS_BASE_URL}/profile.php"
BBS_REFERER = f"{BBS_BASE_URL}/"

# 没拉到头像时的占位 URL。优先用站点 logo，避免渲染时再去网络拉一次失败。
FALLBACK_AVATAR_URL = f"{BBS_BASE_URL}/images/logo.png"

# 登录态判定关键字。命中其中任何一个就视为 Cookie 失效。
NOT_LOGGED_IN_KEYWORDS = (
    "还没有登录",
    "暂时不能使用此功能",
    "您没有登录",
    "请先登录",
    "请登录",
)

# 已登录证据关键字。profile.php 渲染成功时必出现"数字ID"或"个人资料"。
LOGGED_IN_MARKERS = (
    "数字ID",
    "个人资料",
    "会员头衔",
    "在线时间",
)

# ---- 签到 -------------------------------------------------------------------

# 签到任务页面 URL。"进行中任务"页 = 申请入口；"已完成任务"页 / "失败任务"页
# 用于 collect 完成后做页面级 verify（state C 验证）。三个 URL 都以
# ``.html.html`` 结尾——phpwind 路由习惯，不要修剪。
TASKS_NEW_URL = f"{BBS_BASE_URL}/plugin.php?H_name-tasks-actions-newtasks.html.html"
TASKS_END_URL = f"{BBS_BASE_URL}/plugin.php?H_name-tasks-actions-endtasks.html.html"
TASKS_ERRO_URL = f"{BBS_BASE_URL}/plugin.php?H_name-tasks-actions-errotasks.html.html"

# 签到入口 Referer（兼容旧名；指向"进行中任务"页）。
TASKS_REFERER = TASKS_NEW_URL

# 任务 ID。
DAILY_CID = "15"
WEEKLY_CID = "14"

# phpwind 的"申请任务" / "领取奖励"两段动作。
ACTION_APPLY = "job"
ACTION_COLLECT = "job2"

# verify 在 MeYangGe 参考仓库里观察到是固定值。新版本若校验更严，应改为
# 从 tasks 页面 HTML 抓出该 token。
# TODO(southplus-capture): 若 verify 校验生效，改为预先 GET tasks 页面解析。
DEFAULT_CHECKIN_VERIFY = "5af36471"

# ---- 任务接口的语义关键字（按 phpwind 任务状态机分类） ------------------------
#
# state A = 未申请（任务不在"进行中"也不在"已完成"），需先 apply。
# state B = 已申请未领取（在"进行中"），需 collect。
# state C = 已领取（在"已完成"），无需再做任何事；可能伴随 18 小时冷却拒绝。
#
# 关键字检测顺序（apply）：登录态 -> state-B（NEEDS_COLLECT）-> state-C
#                          （ALREADY_COLLECTED）-> 兜底失败。
#                          注意：先 B 再 C，因为 state-C 的关键字（如"已完成"）
#                          可能出现在 state-B 文案的子串里，而 state-B 的关键字
#                          （"请赶紧 / 去完成"）只在 state-B 出现。
#
# 关键字检测顺序（collect）：登录态 -> state-C 旁路（继续 verify）-> 刚领取
#                            成功（继续 verify）-> 兜底失败。
#                            注意：先 C 再 SUCCESS，因为"你[日常]已经完成!"等
#                            state-C 文案含"完成"子串，会被宽松的 SUCCESS 误命中。
#
# 关键字检测顺序（verify）：登录态 -> state-C（ALREADY_COLLECTED 视为 SUCCESS）
#                          -> 兜底失败。
#
# 字典里的串都来自抓包/参考仓库观察到的原始中文文案，匹配用 ``in``。

# 任务接口的"登录已失效"提示：``apply`` / ``collect`` 都共用这串。
NOT_LOGGED_IN_TASK_KEYWORDS = (
    "还没有登录",
    "暂时不能使用此功能",
    "请先登录",
    "请登录",
)

# apply 阶段命中 = 整个任务已经领取过了（state C），跳过 collect。
# 区分点：state-C 必须出现"请勿重复 / 已领取 / 已完成 / 已经完成 / 拒离 / 还没超过"
# 等明确闭合语义；像 "已经申请[日常]完成,请赶紧去完成任务吧!" 这种 state-B 的
# 文案虽含 "已经"，但带 "请赶紧 / 去完成"，由 NEEDS_COLLECT_KEYWORDS 优先命中。
APPLY_ALREADY_COLLECTED_KEYWORDS = (
    "请勿重复",
    "已领取",
    "已经领取",
    "已经完成",  # 你[日常]已经完成
    "已完成",  # 本周已完成 / 今天已完成 / 已完成任务
    "拒离",  # 拒离上次申请[日常]还没超过 N 小时（state-C 18hr 冷却）
    "还没超过",  # 同上的另一种说法兜底
    "本周已经",
    "今天已经",
    "本日已经",
)

# apply 阶段命中 = state B（已申请，待领取），继续走 collect。也覆盖
# state A->B 刚申请成功的情况。
# 注意：不要把 "申请[" 加进来——冷却消息 "拒离上次申请[日常]还没超过..." 也
# 含此串，会把 state-C 误判为 state-B。
APPLY_NEEDS_COLLECT_KEYWORDS = (
    "请赶紧",
    "去完成",
    "申请成功",
    "进行中",
)

# collect 阶段命中 = 站点表达"任务已经处于终态/不在进行中列表"。
#
# 这里包含两类语义合并：
# 1. 经典 state-C：明确告诉你"你已经完成 / 已领取 / 请勿重复"。
# 2. "未申请任务!"：表面像 state-A，但当前流程已经先跑过 apply。collect 仍说
#    "未申请"通常意味着任务已在 endtasks 列表里，phpwind 不再把它视为
#    "进行中"——典型场景是用户在站点手动签到 + 领取后，再调本插件触发签到。
#    若本轮 apply 已进入 state-B，继续 verify；verify 确认后按 SUCCESS。
#
# 顺序：先于 COLLECT_SUCCESS_KEYWORDS 检查——"你[日常]已经完成!" 含"完成"
# 子串，会被宽松的 SUCCESS 误命中。
COLLECT_ALREADY_DONE_KEYWORDS = (
    "请勿重复",
    "已领取",
    "已经领取",
    "已经完成",
    "已完成",
    "未申请",
    "拒离",
    "还没超过",
)

# collect 阶段命中 = 本次刚领取成功（state B -> C）。
# 注意：不要加 "完成"——"你[日常]已经完成!" 是 state-C 文案、同样含"完成"；
# 已由 COLLECT_ALREADY_DONE_KEYWORDS 优先吃掉，但留出最小集合更稳。
COLLECT_SUCCESS_KEYWORDS = (
    "获得",
    "奖励",
    "成功",
    "领取",
)

# 兼容旧名（已无逻辑使用，保留以免外部 import 直接挂掉；下个清理周期可删）。
SUCCESS_KEYWORDS = COLLECT_SUCCESS_KEYWORDS
ALREADY_DONE_KEYWORDS = APPLY_ALREADY_COLLECTED_KEYWORDS
REPEAT_KEYWORDS = COLLECT_ALREADY_DONE_KEYWORDS
# COLLECT_REQUIRES_APPLY 已废弃：phpwind 在 state-C 场景也会返回"未申请任务"，
# 强制 FAILED 的判定会误伤"用户已在站点手动完成"的合法用例。保留空 tuple
# 仅为 backward-compatible import。
COLLECT_REQUIRES_APPLY_KEYWORDS: tuple[str, ...] = ()
