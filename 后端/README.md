# Kairos 后端

目标：将自然语言转成固定时间事件，让用户在需要行动时才看到明确时间。

**当前状态（2026-09-25）：M1、M2 已实现。** 本地健康接口、单次固定事件查询、当前状态与 SQLite 初始化可用；事件创建、重复规则和 AI 录入尚未实现。

## 阅读路径

| 需要了解 | 文档 |
| --- | --- |
| 第一版做什么 | [产品规划](第一版规划.md) |
| Agent 从哪里开始 | [AGENTS](AGENTS.md) |
| 模块如何分工 | [ARCHITECTURE](ARCHITECTURE.md) |
| 时间与 API 的精确语义 | [接口契约](docs/design-docs/contracts.md) |
| 为什么这样选 | [设计决策](docs/design-docs/decisions.md) |
| 开发顺序与交付标准 | [执行计划](docs/exec-plans/active/2026-09-25-backend-v1.md) |
| 如何证明正确 | [质量门禁](docs/QUALITY.md) |
| 如何运行与定位问题 | [运行手册](docs/RUNBOOK.md) |
| AI 如何评估 | [AI 评估规格](docs/design-docs/ai-evals.md) |
| 进度与未完成项 | [STATUS](docs/STATUS.md) |
| Harness Engineering 依据 | [参考资料](docs/references/harness-engineering.md) |

## 采用的方式

需求、接口、决策、测试标准和进度都保存在仓库。AGENTS 只作短入口；架构规则后续用检查程序执行；每个小阶段都提供可复现证据。

开发起点是执行计划的 M1：先建立可运行、可重复验证的最小服务，再实现单次固定事件。真实 AI 接口在确定性业务规则和草稿边界建立后接入。

## 范围与假设

第一版为单用户本地服务，建议 Python 3.12、FastAPI、Pydantic、SQLite。项目要求 Python 3.12–3.14；本机验证环境为 Python 3.14.4。依赖版本记录在 uv.lock。

原始需求及前端规划保留。本次修改仅在后端目录内完成，没有恢复根目录已删除的 README，没有修改数据库或现有环境。
