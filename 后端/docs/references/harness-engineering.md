# Harness Engineering 参考与本项目取舍

阅读日期：2026-09-25。

主要来源：[OpenAI — Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)，2026-02-11。

本文的应用：让仓库成为需求与决策的可查依据；AGENTS 保持简短并指向深层文档；用可执行规则限制依赖方向；通过可复现测试、日志和持续更新的执行计划形成反馈。文档和执行状态应一起维护。

Kairos 的具体选择由本项目需求决定：单体后端、固定时钟、临时数据库、结构化模型草稿、原子提交和有限范围验证。并不照搬大规模多 Agent 系统、自动合并策略或完整观测平台，也不要求所有代码必须由 Agent 生成。

当前交付的是上述方法的项目规划。检查程序、运行环境和 CI 本身尚未落地，须在执行计划中建立后才称为可执行 Harness。
