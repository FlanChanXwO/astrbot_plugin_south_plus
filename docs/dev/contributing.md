# 贡献指南

本文记录 `astrbot_plugin_south_plus` 的贡献入口规则。提交改动前，请先阅读 [`maintenance.md`](./maintenance.md) 中的维护约束。

## 分支与 PR

- 所有 PR 只能提交到 `dev` 分支。
- 不接受直接提交到 `main`、`master` 或其他分支的 PR；目标分支错误时，请先改回 `dev`。
- 维护者会在 `dev` 完成集成验证后，再合并到主分支发布。

## 提交前检查

代码改动至少完成以下检查：

```bash
python -m compileall .
python -m pytest
ruff check .
```

仅修改文档时，可以只做 Markdown diff 与空白检查，并在 PR 描述中说明未运行代码测试的原因。

## PR 描述

PR 描述建议包含：

- 背景问题
- 改动范围
- 风险点
- 验证方式

如果是命令、配置、登录、签到、数据库或安全边界变化，请同步更新对应文档。
