# Kairos

弱化钟表时间，通过自然环境感知时间流动的专注空间。

**当前阶段：新前后端骨架和生成契约已建立，事件领域与连续自然场景正在实施。** 两个旧项目只是只读参考资料，不能直接用作交付产品。旧测试结果不代表新方案已经实现。

## 已确认的方向

- 全屏自然山水，光照更真实；太阳、天空与水面表达真实时间，天气与季节独立影响环境。
- 平时隐藏数字时间、任务清单、下一事件与完成率，长按才临时显示真实时间。
- 刚性事件提前提醒，点击“知道了”立即关闭，未点击则逐渐增强视觉提示；到点自动进入正式事件。
- 柔性事件由用户添加并保存，只有主动询问AI时读取展示；事件管理尽量在对话中完成。
- AI打开期间事件到点不打断输入或草稿，午夜也不重置体验。
- 前端全新开发；后端只迁入通过新验收的模块。

## 从这里阅读

| 内容 | 文档 |
| --- | --- |
| 用户决定与产品边界 | [产品记忆](docs/PRODUCT_MEMORY.md) |
| 桌面／手机布局、场景、材质与动效 | [前端设计](docs/design/FRONTEND_SPEC.md) |
| 提醒、事件、冲突、AI与时钟如何协作 | [状态设计](docs/design/STATE_MODEL.md) |
| 新目录、依赖方向、技术取舍 | [架构提案](ARCHITECTURE.md) |
| 后端哪些可复用、迁入条件与新API | [后端复用矩阵](docs/design/BACKEND_REUSE.md) |
| 16项核心验收、反馈与证据机制 | [Harness Engineering](docs/engineering/HARNESS.md) |
| 10个工作包、子代理边界与并行顺序 | [开发规划](docs/exec-plans/active/2026-09-26-rebuild.md) |
| 旧代码现状与历史验证 | [研读记录](docs/CODEBASE_REVIEW.md) |

## 拟建的新工程

```text
apps/web       全新 Vue / TypeScript 前端
services/api   新 FastAPI 服务，选择性迁入后端模块
contracts      OpenAPI 与生成的 TypeScript 契约
tests/e2e      新前后端联合验收
scripts        独立启动和机械检查入口
docs           产品、设计、规划与证据
```

可用 `python3 scripts/dev.py` 启动新的空场景与 API。事件领域和自然场景正在实现；AI 面板及端到端旅程尚未完成。先运行 `python3 scripts/check.py docs|architecture|contracts|api|web` 验证当前代码；浏览器端到端检查尚未实现。

不要用旧项目启动命令冒充新应用；不要把未来检查入口当作当前可运行工具。进入实现时以任务书的具体退出条件与实际证据判断进度。
