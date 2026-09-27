# Kairos

### 找回「时间之流」，重新栖居在时间里

> Time as the rhythm of the opportune, not the measure of the clock.
>
> **时间是时机的节律，而非钟表的度量。**

KairosTide 从 Chronos（可计量的钟表时间）与 Kairos（情境中的时机）出发，尝试用自然场景恢复人对时间流动的感知。它不以最大化利用时间为目标，而是尊重外部约定与个人期许的差异、人的精力边界和自由选择：不问几点，只问何时。

![KairosTide 项目海报](https://raw.githubusercontent.com/yishengsss/xianaihack-GK024--/main/%E6%B5%B7%E6%8A%A5.png)

> 愿你来时带着钟表，离开时与万物同频。

本文是**当前版本的使用指南**；已确认的产品规则和后续开发约束统一记录在[产品记忆](docs/memory/PRODUCT_MEMORY.md)。介绍表达产品愿景，不代表所有规划能力已实现；当前功能以代码与本指南的“当前版本范围”为准。如本文与产品记忆不一致，以产品记忆和当前代码为准。

## 快速开始

需要 Python 3.11+、Node.js 和 npm。macOS/Linux 在项目根目录运行：

```bash
./start.sh
```

脚本会创建 API 虚拟环境，并在依赖缺失时安装根目录 [`requirements.txt`](requirements.txt) 和前端 `package-lock.json` 中的依赖，然后启动前后端。浏览器打开启动日志中 Vite 显示的地址，通常是 `http://127.0.0.1:5173/`；API 默认在 `http://127.0.0.1:8000/`。按 `Ctrl+C` 停止服务。

本地开发数据保存在 `var/kairos-dev.sqlite3`，重启服务后仍会保留。不要删除这个文件，除非你确实要清除本地日程和任务数据。

## 启用 MiMo 助手

复制 `.env.example` 为根目录 `.env`，在 `.env` 的 `MIMO_API_KEY` 中填写自己的密钥，然后重启服务：

```bash
cp .env.example .env
```

`.env` 已被 Git 忽略。密钥由后端读取，不会传给前端。没有配置密钥时，自然场景仍可打开，但 AI 对话功能不可用。也可以将 `MIMO_API_KEY` 留空并设置 `MIMO_API_KEY_FILE`，让后端从本地文件读取密钥。

## 页面使用

- **查看真实时间**：在自然场景的空白处按住，时间会短暂显示后淡出。点击按钮、事件提示或对话面板不会触发查时。
- **打开助手**：点击右下角“问 Kairos”。例如，可以请求记录一项待完成任务、查询已保存的柔性任务或固定日程，或用自然语言创建日程。固定日程会先生成待确认草稿，检查内容后再确认保存；修改或删除也会先显示提案供确认。
- **发送消息**：按 Enter 发送，Shift + Enter 换行。可以附加 JPEG、PNG 或 WebP 图片（最大 10 MiB）用于课表识别；图片仅供本轮处理，不作为 Kairos 的日程内容保存。
- **处理刚性事件**：提前提醒出现时，“知道了”会关闭本次提醒。事件正式开始后，可在事件卡点“知道了”将其收起为红圈；点击红圈可重新展开。点“例外”会直接对本次事件实例记请假，不经过 AI。
- **处理柔性任务**：已保存任务可能以无文字的黄色圆圈短暂出现在水面下方。点击可查看详情并选择接受；接受后圆圈会持续显示，之后可选择暂停或完成。它不是固定日程，也不会自动安排开始时间。

## 当前版本范围

主场景、长按查时、助手事件与任务操作、红黄圈交互已接入当前应用。真实浏览器端到端验收尚未完成；通过构建和自动测试不等于所有实际浏览器流程已验收。主页面的场景地点选择与真实天气展示也尚未接入，因此当前页面不会因为 README 或产品规划的描述就自动显示实时天气。

## 开发检查

依赖已安装时，也可以直接运行 `python3 scripts/dev.py`。常用检查需逐项运行：

```bash
python3 scripts/check.py docs
python3 scripts/check.py architecture
python3 scripts/check.py contracts
python3 scripts/check.py api
python3 scripts/check.py web
```

`python3 scripts/check.py e2e` 当前会报告 `NOT_RUN`，因为仓库还没有自动化浏览器旅程。

## 项目文档

- [产品记忆](docs/memory/PRODUCT_MEMORY.md)：唯一维护已确认产品决策、边界和待确认项的文件。
- [记忆目录索引](docs/memory/README.md)：说明长期记忆与历史研读记录的用途。
- [前端规范](docs/design/FRONTEND_SPEC.md) · [状态模型](docs/design/STATE_MODEL.md) · [视觉质量记录](docs/design/VISUAL_QUALITY.md)
- [架构提案](ARCHITECTURE.md) · [Harness 与验收](docs/engineering/HARNESS.md)
