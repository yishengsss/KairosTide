# 后端架构设计

状态：建议方案，2026-09-25。业务范围见 [第一版规划](第一版规划.md)。

## 主链路

自然语言 → AI 适配器 → 结构校验 → 草稿与澄清 → 规则校验/冲突检查 → 确认事务 → 正式事件。

读取正式事件 → 按时区展开实例 → 应用单次例外 → 使用服务端时钟计算当前状态。

第二条链路不依赖 AI。模型不可用时，已保存日程仍能正确运行。

## 计划中的目录（尚未创建代码）

```text
后端/
  pyproject.toml                 依赖、格式、测试和类型检查配置
  uv.lock                       在选定依赖后生成的锁文件
  src/kairos/
    main.py                     应用装配；唯一连接具体适配器的位置
    settings.py                 环境配置与本地绑定设置
    domain/
      models.py                 事件、草稿、实例与值类型
      scheduling.py             重复展开、重叠判断、状态计算
      errors.py                 稳定业务错误类型
    application/
      ports.py                  Clock、Repository、Planner 协议
      drafts.py                 解析、澄清、草稿生命周期
      events.py                 提交、修改、删除与例外事务
      state.py                  当前状态和下个边界查询
    adapters/
      sqlite.py                 持久化、事务、版本和幂等
      ai.py                     供应商请求与结构化输出校验
      clock.py                  真实时钟
    api/
      schemas.py                HTTP 输入输出模型
      routes.py                 路由、状态码与依赖注入
      errors.py                 统一错误转换
  migrations/                   带版本的数据库迁移
  tests/
    unit/                       不依赖网络或数据库的规则测试
    integration/                临时 SQLite 与 HTTP 测试
    architecture/               禁止跨层依赖的结构检查
  evals/                        固定输入、期望语义、模型评估程序
  scripts/                      契约导出、文档检查、验收入口
  docs/generated/               实现后生成的 OpenAPI，不手工维护
```

## 依赖方向

- domain 只依赖标准库及本域类型，禁止导入 FastAPI、数据库驱动、模型 SDK。
- application 依赖 domain 和自身 ports，不依赖具体 adapters 或 api。
- adapters 实现 ports，可以依赖 domain；api 只调用 application。
- main 是装配入口，允许导入各层；业务规则不能放在路由中。
- settings 只被装配层和适配器读取；domain 不读环境变量或系统当前时间。

M1 用 AST 导入检查将上述方向变成会失败的测试；必须用一个临时违规依赖证明检查不是空壳。目标是可机械检验的少量边界，不引入微服务、消息队列或通用 Agent 编排框架。

## 关键端口

以下是规划接口，M1/M2 定义真实类型后作为代码契约：

- Clock.now() → 带 UTC 时区的 datetime；测试注入固定时刻。
- Planner.parse(text, timezone, reference_now, answers) → 候选结果；不能取得 Repository。
- Repository 通过事务读取/写入事件、草稿、例外、幂等结果；只让提交服务写正式事件。

解析上下文中的原文与模型输出均是数据，不是可以执行的指令。模型提出的任意字段必须再次校验。

## 存储与时间

单次事件存 UTC 时刻及原始 IANA 时区；重复系列存本地日期、钟表时间与频率。实例按请求窗口生成，不预生成无限行。

SQLite 提交事务内完成版本检查、冲突复检、事件与例外写入、草稿状态更新、幂等结果保存。AI 请求在事务外执行，避免长期占用写锁。数据库忙时返回可重试错误，不无限等待。

请求 /state 时计算状态，不依赖常驻计时器修改数据库。浏览器根据返回的边界同步；后端不承担第一版的系统通知。

## 可观测性

结构化日志至少记录 request_id、operation、duration_ms、result_code；模型调用增加 provider、model、prompt_version、latency_ms。默认不记录输入原文、地点、完整提示词或密钥。

通过固定时钟、临时数据库、假 Planner 和 HTTP 测试重现问题。真实模型评估独立运行，结果保存模型版本与时间，不进入普通离线测试。
