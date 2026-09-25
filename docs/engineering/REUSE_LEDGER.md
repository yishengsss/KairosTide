# T2 后端复用账本

状态：2026-09-26 新服务 T2 实现证据；源目录仅静态只读。此账本记录**算法与事务模式**的选择性迁入，未复制旧服务、运行环境、配置、数据库或产品限制。源路径基准为 `XiAnHacker-backend-v1/后端/`；hash 为源文件完整字节的 SHA-256。

| 新代码 | 源路径与 SHA-256 | 原有行为证据 | 迁入与改造 | 新验证 |
| --- | --- | --- | --- | --- |
| `domain/time_rules.py` | `src/kairos/domain/scheduling.py` · `82cc63078ebd0375ed981564381c807205fa48948c51fdee5995c0ae4615fa08` | `tests/unit/test_recurrence.py::test_adjacent_events_do_not_conflict` | 保留 aware 的半开区间规则；修正同一时区 DST fold 下的 Python 本地时间比较，统一用 UTC 时间点 | `tests/unit/test_time_rules.py` 的相邻区间及 fold 测试 |
| `domain/recurrence.py` | `src/kairos/domain/scheduling.py` · 同上 | `tests/unit/test_recurrence.py` 的周重复、DST gap/fold、until date 用例 | 保留 UTC 往返判定与本地日历展开；实例身份移到独立模块；查询窗口限制是资源限制，不会自动截成事件终止日；没有终止日期要澄清 | `tests/unit/test_time_rules.py` 的跨午夜和 DST 测试；`tests/integration/test_drafts.py::test_recurrence_without_end_date_stays_unconfirmed` |
| `domain/events.py`, `domain/state.py` | `src/kairos/domain/models.py` · `cb0819e6d8189859e247de974c6b3f917f8613d0b525dbcbba7ebbe15cc1e897` | 原模型分系列与实例但 status 为宽泛字符串 | 新模型显式分 disposition、temporal phase、schedule revision；旧模型结构未直接复制 | `tests/integration/test_exceptions.py` 单次请假及改期稳定性 |
| `domain/occurrence_identity.py` | 未迁入旧 `domain/occurrence_ids.py`（旧 ID 含开始时间） | 原 `tests/unit/test_recurrence.py::test_occurrence_id_round_trips_series_and_local_instance_key` | 新 ID 由事件 ID 与不可变原始槽位生成不透明 UUID，并登记在 `occurrences`；单次改时不换 ID | `tests/integration/test_exceptions.py::test_single_occurrence_reschedule_keeps_identity_and_increments_schedule_revision` |
| `domain/drafts.py`, `application/drafts.py` | `src/kairos/application/drafts.py` · `2032fc2577d73ae10001b77f4ba4da7fd29c1b396722424818e78a67ea5653e1` | 原 revision、reference_now、ready/commit、候选编辑 | 新草稿为结构化候选输入，不调用旧解析器或静默补时；以 candidate_id 逐项新增/修改/删除；源消息时间固定；完整摘要绑定审阅内容 | `tests/integration/test_drafts.py` 候选完整性、缺失时间、版本测试 |
| `application/draft_commit.py`, `adapters/persistence/sqlite.py` | `src/kairos/adapters/sqlite.py` · `3730370e79393eef3f0dafb711ee4afec77f7dd503f9caa7324e11ad7ea38ee2` | `tests/integration/test_draft_commit.py` 原子事务、重试、并发；源 `commit_draft` 用 BEGIN IMMEDIATE | 全新表与 owner 范围；事务内再查草稿、版本、过期、候选、冲突；完整批次、幂等记录、操作审计及状态同一事务；重试保持原结果；不继承旧库迁移链 | `tests/integration/test_drafts.py` 三候选、第二项失败、冲突过期、并发确认与回滚审计 |
| `adapters/clock.py`, `application/ports.py` | `src/kairos/adapters/clock.py` · `1a28c7bdcf6b9ae3969ceaedd33ff04a9305b3d7ea52c8707207ca2317182123` | 旧适配器 UTC 系统时钟 | 新 Clock 协议注入，领域无系统时钟读取；测试使用固定时钟 | 新集成测试均注入 `FixedClock` |
| `migrations/001_initial.sql` | 未迁入旧迁移链；源 `src/kairos/adapters/sqlite.py` 上述 hash 仅参考约束 | 旧表缺 owner，旧幂等键全局唯一 | 新库自建 owner 范围的事件、实例、草稿、幂等表；不运行旧数据库 | 临时 SQLite 的集成测试与重新打开后实例请假状态测试 |

## 边界和后续装配

- T2 的草稿输入是**已解析、可审阅的结构化候选**。自然语言解析与用户会话由后续 AI 任务承担；这一步没有模型调用或猜测时间。
- 当前 `main.py` 中业务 HTTP 路由仍是 T1 的 501 占位。协调者需要串行装配本用例到路由、映射 Pydantic schema 与错误码，并重新生成合同。本任务不编辑共享 `main.py` 或 `api/schemas.py`。
- 提前提醒 ack、冲突“选一个其余 missed”、柔性任务与真实天气分别属于后续任务。这里的冲突只在**创建提交**时要求显式接受并存，不替用户选择哪个事件会实际展示。
- 本地 principal 作为新服务第一阶段的 owner 输入；公网鉴权不在 T2 范围。重复系列改动如需重新映射实例，当前明确拒绝 `UNSUPPORTED_EDIT_SCOPE`，不删除重建。
