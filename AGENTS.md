# Kairos 项目协作约定

开始本项目的设计、开发或评审前，先阅读 [产品记忆](docs/memory/PRODUCT_MEMORY.md) 与 [新项目架构](ARCHITECTURE.md)。产品记忆记录用户决定；架构与设计中标为建议的内容不能冒充用户确认。

## 阅读地图

- 设计：[前端规范](docs/design/FRONTEND_SPEC.md)、[状态模型](docs/design/STATE_MODEL.md)。
- 记忆：[记忆目录索引](docs/memory/README.md)、[产品记忆](docs/memory/PRODUCT_MEMORY.md)、[旧代码研读](docs/memory/CODEBASE_REVIEW.md)。
- 画面与动画修改前必读：[视觉质量约束与当前审查](docs/design/VISUAL_QUALITY.md)。先修构图/遮挡，再加运动；测试通过不能替代视觉验收。
- 后端：[复用准入与契约草案](docs/design/BACKEND_REUSE.md)。
- 验收：[Harness 与 K01–K16](docs/engineering/HARNESS.md)。
- 分工：[当前开发规划](docs/exec-plans/active/2026-09-26-rebuild.md)。
- 现状：[项目入口](README.md)、[旧代码研读](docs/memory/CODEBASE_REVIEW.md)。

## 新旧边界

- 用户明确禁止直接使用两个旧半成品。`XiAnHacker-view-v1/`、`XiAnHacker-backend-v1/` 是只读参考，禁止作为新运行时、构建或依赖输入，也不在其中继续开发新产品。
- 新前端规划在 `apps/web` 全新实现；新后端规划在 `services/api`，仅迁入已审查的最小代码单元，并记录来源与新测试。
- 不复制旧环境、密钥、数据库、依赖目录或旧AGENTS。旧文档中的固定事件only等限制不覆盖当前产品要求。

## 协作与验证

- 用户后续明确指令优先于已有记忆；发生变化时同步更新产品记忆，避免保留互相冲突的规则。
- 区分用户已确认规则、暂定理解和待确认项，不将实现者的猜测写成用户决定。
- 保持 Kairos 的自然场景、弱化钟表时间和用户自主权；不要擅自加入常驻时钟、倒计时、任务列表、自动日程安排或主动柔性任务提醒。
- 不把产品记忆当作已经完成的实现。当前代码、接口、存储和验证结果应以项目实际文件为准。
- 用户已要求子代理分工；最多主协调＋3个子代理并行，每个文件只有一个写入负责人；契约和共享配置由协调者串行维护。
- 任务先声明依赖、允许写入路径、需求ID与验收，再实施和独立审查；不能用旧测试或合成服务结果证明新系统已接通真实服务。
- 当前检查接口为 `python3 scripts/check.py <scope>`。它已实现文档、隔离、契约、API与Web门禁；`e2e` 仍明确返回 `NOT_RUN`，不能据此声称浏览器旅程已验收。详情见Harness。
