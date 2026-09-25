# Kairos 后端逐项复用与新契约建议

日期：2026-09-26。状态：设计建议，尚未迁入、实现或验证新服务。

## 1. 边界与结论

需求依据为根 `AGENTS.md`、[产品记忆](../PRODUCT_MEMORY.md)及本轮最新用户要求；旧后端 AGENTS 中“固定事件 only／不实现柔性任务”已被覆盖。
旧前端仅作参考，旧后端只能按下表逐项审查、抽取，不整体复制半成品，也不在旧目录继续开发新产品。
新后端建议沿用 Python / FastAPI 的分层方式，目标根目录为 `services/api/src/kairos/`；技术选择是建议，不是已确认部署方案。
可复用的核心价值是时间运算、草稿确认与事务模式；当前后端并不具备提醒确认、冲突错过、柔性任务、会话管理或天气闭环。
建议建立新的 `/api/v1` 契约，不承诺旧部署、旧 API、旧数据库或旧前端适配器兼容。
本轮仅形成规划；不修改旧源码、数据库、环境，不迁移数据，不启动旧服务或真实模型调用，不提交代码。

“迁入可复用”表示候选代码可小范围抽取，仍需通过新项目准入测试；不是免审复制。
“改造后迁入”表示保留算法或事务思想，先修正契约和边界；“不迁入”表示新建或明确延期。
下表源路径以 `XiAnHacker-backend-v1/后端/` 为基准，行号来自本轮静态读取；目标路径均相对上述新后端根目录。

## 2. 逐模块证据矩阵

| 模块 | 处理结论 | 源码证据 | 新目录与迁入条件 |
| --- | --- | --- | --- |
| 半开时间区间 | 迁入可复用 | `src/kairos/domain/scheduling.py:9–24` 校验 aware 时间并实现 `[start,end)` 与相交 | `domain/time_rules.py`；保留起点包含、终点排除与相邻不冲突 |
| DST 本地时间解析 | 迁入可复用 | `domain/scheduling.py:27–48` 用 UTC 往返区分 gap/fold，缺策略时报错 | `domain/recurrence.py`；保留显式 skip / earlier / later，不默认猜测 |
| 每日／每周实例展开 | 改造后迁入 | `domain/scheduling.py:67–125` 在窗口内展开，使用本地日历与 IANA 时区 | `domain/recurrence.py`；分离实例身份，限制查询成本，不继承旧产品范围上限 |
| 冲突检测 | 改造后迁入 | `domain/scheduling.py:128–141` 覆盖候选互相及候选与已有实例相交 | `domain/conflicts.py`；过滤取消／请假，接入提交复检；检测不可自行选择 |
| 实例 ID 编解码 | 不迁入当前身份方案 | `domain/occurrence_ids.py:5–21` 编码 event/key；`domain/scheduling.py:52,109` 的 key 含开始时间 | `domain/occurrence_identity.py` 新建；改时、跨时区展示后保持同一实例 ID |
| 事件与实例模型 | 改造后迁入 | `domain/models.py:6–52` 已分系列、实例、例外、快照，但 status 是未限定字符串 | `domain/events.py`、`domain/state.py`；拆分时间阶段、用户处置、提醒确认 |
| 应用层查询 | 改造后迁入 | `application/state.py:42–97` 把例外覆盖到 status，state 仅 active 与下次边界 | `application/state.py`；补提醒、冲突与 revision；以同一时刻计算一次快照 |
| 旧 events 列表语义 | 不迁入 | `application/state.py:99–115` 每个系列只取窗口首个实例；`api/routes.py:612–624` 将其命名 events | `api/events.py` / `api/occurrences.py` 分开系列与实例，不建立含混别名 |
| 单次请假／取消 | 改造后迁入 | `application/events.py:77–120` 校验实例存在；只接受 excused/cancelled | `application/occurrence_commands.py`；使用稳定 ID、所有权及版本，单次不改系列 |
| 系列更新／删除 | 改造后迁入 | `application/events.py:122–237` 有字段校验；`adapters/sqlite.py:241–247` 有例外则拒绝改时间 | `application/event_commands.py`；显式作用范围、变更草稿、例外重映射或明确拒绝 |
| 候选校验 | 改造后迁入 | `application/planning.py:29–138` 校验时区、时间、重复；`:63–64,94–95` 有旧 7/366 天上限 | `domain/drafts.py` / `api/draft_schemas.py`；保留正确性规则，资源限制与产品规则分开 |
| 草稿创建与澄清 | 改造后迁入 | `application/drafts.py:145–168,253–280` 保存 reference_now，澄清复用基准；`:123–125` 拒绝文本重复 | `application/drafts.py`；保留基准、过期和 revision，移除旧文本重复禁令 |
| 候选编辑 | 改造后迁入 | `application/drafts.py:345–376` 用传入整个 candidates 数组替换 | `application/drafts.py`；稳定 candidate_id 与逐项操作，遗漏候选不得视作删除 |
| 草稿提交 | 改造后迁入 | `application/drafts.py:442–471` 检查 revision、ready、过期后提交全部候选 | `application/draft_commit.py`；补用户确认凭据、权限、冲突复检、事务内过期复核 |
| SQLite 事务／幂等 | 改造后迁入 | `adapters/sqlite.py:334–435` CAS 更新；BEGIN IMMEDIATE、请求 hash、整批写入与幂等记录同事务 | `adapters/persistence/`；扩展 owner / 操作域，统一时钟，锁内再读并校验当前草稿 |
| 旧 SQL 迁移链 | 不直接迁入 | `migrations/001_initial.sql:6–18` 无 owner；`002_recurrence.sql:17–24` 仅两种例外；`003_drafts.sql:16–20` key 全局唯一 | 新 `services/api/migrations/` 从新 schema 初始化；参考约束，不运行在旧库上 |
| 真实时钟适配 | 迁入可复用 | `adapters/clock.py:4–6` 返回 UTC 当前时刻；`application/state.py:35–39` 校验 aware | `adapters/clock.py`、`application/ports.py`；所有业务时钟注入，测试使用固定时钟 |
| 模型传输与输出校验 | 改造后迁入 | `adapters/openai_compatible.py:194–238` 结构校验、超时、有限重试与错误分类 | `adapters/ai/`；按选定供应商重建配置，限制响应体／重试预算，输出仍须领域校验 |
| 旧模型提示与单轮助手 | 不迁入 | `adapters/openai_compatible.py:18–49` 拒绝柔性任务／禁止管理；`:161–192` 单问单答 | `application/conversations.py`、`adapters/ai/prompts/` 新建能力与工具权限边界 |
| 助手 HTTP 入口 | 不迁入 | `api/schemas.py:82–95` 无 session；`api/routes.py:220–225` 无论提问内容都读取未来 30 天事件 | `api/conversations.py`；按请求意图读取最小数据，支持用户消息、澄清、草稿关联 |
| 图片校验 | 迁入可复用，但延期接入 | `application/images.py:20–42` 校验格式、字节数、像素数及解压炸弹 | `application/images.py`；只有图片能力排期后才抽取，不挤占文本核心闭环 |
| HTTP 路由与 DTO | 不整体迁入 | `api/routes.py:552–655` 包含错误映射及混合旧路由；`api/schemas.py:120–122` commit 无冲突确认字段 | `api/` 按新域重写，参考错误分类；OpenAPI 生成客户端类型，不手写第二份协议 |
| 组装／配置 | 不迁入默认值 | `main.py:14–21` 自动读旧 .env；`settings.py:13–17` 指向旧 .data、模型与第三方 URL | `bootstrap.py` / `settings.py` 新建；配置显式注入，禁带旧地址、密钥和数据路径 |
| 历史测试 | 逐项改造后迁入 | `tests/unit/test_recurrence.py:52–129` 时间语义；`tests/integration/test_draft_commit.py:71,199,264` 持久化／回滚／并发 | 新 `services/api/tests/`；保留行为证据，淘汰旧产品禁令及旧接口快照 |

矩阵中省略 `src/kairos/` 的路径仍属于该源目录；tests 与 migrations 位于旧后端根目录。
不带入 `.env`、`.data`、`.venv`、缓存、运行产物或旧 AGENTS 限制；也不依靠跨目录 import 暗中运行旧后端。

## 3. 数据所有权与稳定实例身份

建议先建立服务端可信的 `owner_id` 边界；身份由请求上下文注入，不允许客户端指定任意 owner。
本地单用户可以用明确的本地 principal；若未来公网部署，需另行实现身份与授权，不能把该假设当成公网安全能力。
每个仓储查询、唯一键及关联校验都带 owner；返回中的 ID 不能替代权限检查。

| 数据 | 权威来源／持久化 | 关键字段建议 |
| --- | --- | --- |
| 刚性事件系列 | 服务端事件仓储 | `event_id, owner_id, version, title, location, timezone, recurrence` |
| 刚性实例 | 服务端身份登记与展开器 | `occurrence_id, event_id, original_slot, start_at, end_at, version, schedule_revision` |
| 实例处置 | 服务端用户操作记录 | `disposition, source_action_id, actor_id, decided_at, version` |
| 提前提醒 | 服务端提醒策略与确认记录 | `reminder_id, occurrence_id, schedule_revision, trigger_at, acknowledged_at, policy_version` |
| 冲突选择 | 服务端原子决策记录 | `decision_id, member_ids, selected_id, snapshot_revision, actor_id` |
| 草稿与动作提案 | 服务端草稿仓储 | `draft_id, revision, reference_now, candidate_ids, expires_at, status` |
| 柔性任务 | 服务端任务仓储 | `task_id, title, deadline, deadline_precision, timezone, version, source_message_id` |
| 对话消息 | 服务端会话仓储 | `conversation_id, message_id, sequence, role, content, related_draft_ids` |
| 未发送输入／画面过渡 | 前端本地交互状态 | `input_buffer, ai_open, pending_presentation, presented_occurrence_id` |
| 天气观测／预报 | 供应商事实经后端规范化 | `source, fetched_at, observed_at, valid_from, valid_to, availability` |

实例 ID 不由当前 start_at、列表顺序、版本或展示时区生成。建议使用不透明 ID 与不可变原始实例槽位的唯一映射。
单次事件在确认时登记实例；重复事件按已确认规则在有限窗口内懒登记，唯一约束保证并发展开不重复。
单次改时更新有效起止时间，保留 `occurrence_id` 与 `original_slot`；历史请假、提醒 ack 和冲突决定继续指向原实例。
时间安排变化独立递增 `schedule_revision`，新版本生成新 `reminder_id`；旧ack作为历史保留但不确认新提醒。标题等无时间变更仅递增普通version，不能无故再次催促。
冲突决策成员同时绑定安排版本；改期后不能盲目沿用旧时间区间下的选择或missed，变更草稿须展示受影响记录并按明确范围处理，否则拒绝变更。
系列改时涉及槽位重映射；未确定范围时不执行。需明确哪些实例保留 ID、哪些新增或失效，并保留历史关联。
初期可以明确拒绝尚未支持的系列变换，返回 `UNSUPPORTED_EDIT_SCOPE`，不能通过删旧建新悄悄丢弃用户操作。
数据库存 UTC 时间点；重复规则和日级截止同时存 IANA 时区与本地日历含义，不能只存 UTC 偏移。
查询重复实例使用有界窗口，不一次生成无限未来；没有 repeat 终止范围时先澄清。
是否允许用户明确选择“无结束日期”仍待产品决定；即使允许，查询上限也不能反写为用户的重复结束日。

## 4. 业务时间、用户处置与前端展示分离

建议实例拆成 `temporal_phase = scheduled | active | ended` 与 `disposition = normal | excused | cancelled | missed`。
时间阶段由服务器时钟及 `[start_at,end_at)` 派生，`ended` 只表示时间结束，不代表用户完成、参加或错过。
请假／取消由对应用户动作写入；**missed 只能由用户明确选择冲突中的主事件时产生**。
AI、定时器、未点“知道了”、无响应、关闭页面、离线恢复、时间结束都无权自动标记 missed。
冲突尚未选择时保留全部正常实例和 `unresolved` 状态，不按创建顺序、优先级或模型建议自动决定。

`state` 提供事实：服务器时间、当前实例、到期提醒、冲突成员与已确认选择；不规定主场景常驻显示这些字段。
提醒提前量由独立策略产生，五分钟仅是示例；未知策略不能在后端固化成全局产品规则。
提前提醒 ack 只确认 `reminder_id`，不改开始时间、不请假、不取消，也不将用户标记为参加。
前端点击可立即关闭并记录待同步项；服务端ack仍以成功响应为持久化依据。恢复重试先校验reminder绑定的schedule_revision，不接受旧ack确认新安排。
重复提交同一 ack 返回同一结果；建议同一提醒实例刷新／重连不重开，是否允许新一轮提醒仍待产品确认。
未 ack 的视觉增强由前端依据业务时间执行，后端不下发“再催一次”的自动任务。
正式事件“知道了”与提前提醒 ack 是不同动作；收起范围未定义前，不能复用提前提醒端点赋予业务效果。

冲突选择请求必须带已向用户展示的成员集合、选中实例及 `snapshot_revision`。
服务端在事务内重查当前冲突、权限和版本；选中项保留 normal，其余本次明确确认的冲突成员写 missed，并保存共同 decision_id。
确认成功才能收起冲突提示；过时选择返回 409 与新快照，不能把新加入的第三个事件悄悄记 missed。
选择只影响实例，不删除事件或重复系列；`selected_id` 并不等同于“完成”状态。
部分重叠、稍后新冲突、切换选中项与撤销 missed 的语义待决定；实现前必须给出可审阅的规则，不能自动扩散选择。

用户正在 AI 中时，服务器照常计算 active，前端只记待展示并给轻量提示，不关闭会话、不清输入。
退出 AI 时重新取快照，再决定当前画面；若事件已结束，不重播“正在发生”，也不因此写 missed。
`next_transition_at` 是重新同步的技术边界，可以包含提醒触发及事件开始／结束，不能当作倒计时文案。
后台恢复先重新同步再呈现；离线事实必须标记旧快照来源，禁止拿缓存起止时间覆盖请假／取消／missed。

## 5. 草稿、确认、版本与幂等

草稿保存是保存未确认工作，不是保存正式事件；只有提交事务成功返回事件 ID 后，助手才能说“已保存”。
草稿支持一条消息产生多个刚性事件；每个候选有稳定 `candidate_id`，可分别澄清与编辑。
候选数量超限必须显式报错或协商拆批，禁止只取 `candidates[0]`、截断数组或默认丢弃余项。
建议 PATCH 使用 `update_candidate / remove_candidate / add_candidate` 操作并带 revision；删除必须明确指定 candidate_id。
确认展示覆盖本次全部候选及动作范围，提交携带完整 `confirmed_candidate_ids` 与 `confirmation_digest`。
digest 由服务端对应版本的可审阅内容生成；它用于绑定确认内容，不替代真实用户确认行为或身份校验。
日期、具体起止时间／时长、重复频率与范围不足时保持 needs_clarification，不补 14:00、180 天或学期范围。
地点缺失保留 null 并展示未知；是否必须澄清由产品规则决定，不能伪造地点使草稿“完整”。
`reference_now` 在草稿初次解析时固定；跨午夜澄清仍基于同一参考，用户明确改日期才更新候选。
草稿过期只能要求重新确认新草稿，不得默默用新的“明天”提交；具体有效期作为实现配置单独决定。

提交事务内验证 owner、revision、状态、有效期、候选完整性、必填信息、实例冲突及确认摘要。
创建时检测重叠用于告知和显式接受并存，**不是**提前作出发生时“选一个、其余 missed”的决定。
若采用冲突接受令牌，绑定候选摘要和冲突快照；确认后发生新冲突须返回 409 重新审阅。
多个候选整体成功或整体回滚；事件写入、草稿状态、幂等结果和操作审计必须在同一事务。
所有写命令建议要求 `Idempotency-Key`；按 owner + 操作域约束，规范化请求 hash 区分重试与新请求。
同 key 同 payload 返回原结果；同 key 不同 payload 返回 409；两个不同 key 提交同一 revision 也只允许一批事件。
提交重试先读取已完成幂等结果，避免“提交成功但响应丢失，重试因过期又声称失败”。
建议将提交处理与模型连接解耦：已确认的有效草稿不因模型临时离线而无法提交。
修改／删除／请假通过明确目标和 scope 的动作提案进入同一命令层；是否逐类增加确认需产品定稿。
无歧义的直接用户命令和需要追问的模糊请求要区分；不能把 AI 推测当成用户确认整个系列。

## 6. 柔性任务与多轮会话权限

柔性任务必须真实入库，字段中没有固定开始时间；deadline 可以缺失，日期级与时间点级不可混淆。
“周日前完成实验”应保存用户表达及解析后的截止精度；若语义影响截止日需澄清，不自动变成某小时刚性事件。
创建成功返回 `task_id/version` 才可回复已添加；模型失败、校验失败、落库失败必须分别报告真实结果。
柔性任务不进入 `/state`、提醒队列、默认主页或自然场景，也不因 deadline 临近触发主动消息。
仅在用户主动询问相关任务后，服务端开启本轮任务读取；后台预取、页面加载和普通闲聊不得自动读取完整任务集。
本轮授权由服务端从用户消息和会话上下文判断并记录，不能接受模型自行声明 `user_asked=true` 绕过。
工具读取返回真实 task_id，回答只能引用已存在任务；紧迫程度可以分析，不能创造任务或自动安排自由时间。
完成／撤销、逾期保留与删除策略待确定；不能把 deadline 到期等同删除、完成或 missed。

建议会话由服务器持有连续消息及 sequence，客户端用 `client_message_id` 防止网络重试重复执行。
每轮区分用户原话、模型答复、工具事实与动作结果；会话摘要保留指代、候选 ID、未决问题与确认状态。
不将完整无限历史或全部用户数据塞入每次提示；上下文裁剪不能移除未解决的确认与范围信息。
未发送输入属于前端，服务器保存已提交消息和草稿；切换画面不能清空它们。

| AI 能力 | 读取边界 | 写入边界 |
| --- | --- | --- |
| 查询刚性事件 | 用户本轮问题需要的日期窗口；返回具体实例及处置 | 无权由查询改变任何事件 |
| 创建／管理刚性事件 | 解析、查找对象、显示歧义、生成草稿或动作提案 | 只有命令层校验用户确认／明确操作后写入；模型无数据库凭据 |
| 添加柔性任务 | 用户主动添加提供的内容 | 可提出 save_task 命令，由服务端检查来源和字段；成功结果后才宣称保存 |
| 查询柔性任务 | 用户主动询问后按本轮授权范围读取 | 无权顺带完成、删除或安排任务 |
| 天气问答 | 用户提问所需位置、日期及供应商覆盖范围 | 只读；不可把模型常识当实时天气 |
| 提醒／冲突 | 可解释状态，给出用户可操作的信息 | 模型不可自动 ack、自动选择主事件或写 missed |

权限由应用层工具白名单与参数校验执行，提示词只辅助；事件标题、网页、天气文本、图片文字均不能改变权限。
模型工具调用必须有 `source_message_id/action_id`，正式写命令仍经过权限、版本、幂等和事务校验。
模型、天气失败不影响已保存事件的开始／结束计算；使用独立端口与适配器，避免旧 planner 同时承担全部能力。

## 7. 新 API 精炼草案

以下均为 `/api/v1` 下的建议契约，名称可在实现前收敛；不宣称已有这些端点。
写请求除表内字段外均带 `Idempotency-Key`，更新带 expected version/revision；owner 来自身份上下文。

| 端点 | 用途与关键请求／响应 |
| --- | --- |
| `GET /state` | `server_now, state_revision, active_occurrences, due_reminders, conflicts, next_transition_at`；不返回柔性任务 |
| `GET /events` | 查询系列，游标分页；`event_id, version, recurrence`；只为对话按需查询，不要求管理页 |
| `GET /occurrences?from=&to=` | 有界窗口；每项 `occurrence_id, event_id, temporal_phase, disposition, start_at, end_at, version` |
| `POST /reminders/{reminder_id}/ack` | `expected_version, schedule_revision`；返回同一 reminder 的 `acknowledged_at/version`，旧安排版本返回409 |
| `POST /conflict-decisions` | `member_ids, selected_id, snapshot_revision, source_action_id`；返回 decision 与变更实例 |
| `POST /drafts` | `conversation_id, source_message_id, intent, text, timezone`；返回完整候选、问题、revision 与 reference_now |
| `GET /drafts/{draft_id}` | 恢复未完成草稿；包含状态、全部候选、过期时间与关联动作 |
| `POST /drafts/{draft_id}/clarifications` | `revision, answers`；新 revision；保留候选身份与原参考时间 |
| `PATCH /drafts/{draft_id}` | `revision, operations[]`；按 candidate_id 修改，显式删除 |
| `POST /drafts/{draft_id}/commit` | `revision, confirmed_candidate_ids, confirmation_digest, conflict_acceptance?`；返回全部资源 ID 与版本 |
| `POST /occurrences/{occurrence_id}/exceptions` | `type=excused|cancelled, expected_version, source_action_id`；只改当前实例，不接受 missed |
| `POST /event-change-proposals` | `target_id, scope, expected_version, changes/action, source_message_id`；生成可审阅变更草稿 |
| `POST /flexible-tasks` | 明确添加意图下 `title, deadline?, deadline_precision?, timezone, source_message_id`；返回已持久保存 task |
| `POST /flexible-task-queries` | `conversation_id, source_message_id, query_scope`；服务器验证本轮主动询问再返回匹配任务 |
| `POST /conversations` | 创建 owner 内会话；返回 `conversation_id, revision` |
| `POST /conversations/{id}/messages` | `client_message_id, content, timezone, expected_sequence`；返回 answer、tool_results、draft_refs |
| `GET /conversations/{id}/messages?cursor=` | 恢复已发送对话与未决草稿引用；不触发任务读取或模型运行 |
| `GET /weather?location_id=&from=&to=` | 实况／预报及 `availability, observed_at, fetched_at, valid_until, source`；范围不支持明确说明 |

动作提案可复用草稿提交机制，但响应须明确 `resource_type` 与操作结果，不能把删除结果包装成新建事件 ID。
错误统一提供 `code, message, request_id, field_errors?, current_revision?`；409 表示版本／幂等／确认快照冲突。
未授权 401/403，不存在 404，过期草稿 410，字段／范围错误 422，上游不可用 503；均不得附带伪造成功结果。
从新后端 OpenAPI 生成前端 DTO，并以真实 HTTP 契约验收；不从旧前端手写适配器反推新 schema。

## 8. 天气事实与环境显示

建议 WeatherProvider 统一实况与预报，位置输入可来自用户选择或获准定位；供应商、定位方式及缓存精度待选择。
返回规范化 condition、云量／降水／能见度等供应商实际可得字段；未知值为 null，不从缺失数据推导晴天。
实况与预报必须区分，并携带位置、来源、观测时间及有效期；超出预测范围返回 unavailable，不由 AI 编造。
供应商失败时可使用带 stale 标记和原时间戳的旧数据；没有有效数据则 availability=unavailable。
前端可呈现中性自然环境或保留带过时状态的观测，但不能把天气失败伪装成“当前晴朗”。
天气不改变事件业务时间或太阳时间位置；季节、天体轨迹与视觉渲染是另外的环境计算职责。
AI 天气回答必须来自该工具结果；不向模型暴露天气供应商密钥，也不把用户对话存入天气缓存。

## 9. 迁移准入、验证与来源记录

每次迁入只包含一个可说明的模块或窄切片；在新目录独立运行，不修改源目录验证其“可迁移”。
建议为每项维护来源记录：`source_path, source_lines, source_sha256, upstream_commit_if_available, target_path, retained_behavior, changes, tests, reviewer`。
旧目录尚无可依赖的独立提交身份时记录文件哈希和读取日期，不能编造上游 commit；正文行号随来源记录冻结。
迁入前确认来源／许可与依赖清单；只取所需代码及测试，不携带历史配置、示例用户数据或自动初始化旧库逻辑。
新数据库从空库和新迁移链建立；若未来用户要求导入旧数据，另做只读导出、转换校验与回滚方案，不隐式导入。
统一 Clock 端口，移除仓储直接读取系统时间的路径；旧 `adapters/sqlite.py:253` 仍直接调用 datetime.now。
提交前复核失效窗口与并发状态，不能只依赖 application 层早先的校验或模型返回。

| 必过验证 | 能证明什么 |
| --- | --- |
| 时间／重复单元测试 | 半开区间、午夜、跨日、IANA 时区、DST gap/fold、repeat 范围缺失必须澄清 |
| 稳定 ID 测试 | 同窗口重查／跨设备／单次改时 ID 不变；例外和 ack 关联不丢失；系列不支持范围显式拒绝 |
| 草稿提交集成测试 | 三个以上候选往返不丢项；过期与 stale revision 拒绝；同 key 重试、并发提交、部分失败全回滚 |
| 冲突与提醒集成测试 | ack 不改变事件；未选择永不写 missed；用户选择原子更新；新增冲突要求重新确认 |
| 柔性任务权限测试 | 真实保存后重启可查；普通会话／state 不读取任务；主动询问可查；截止到期不主动提醒 |
| 对话／工具测试 | 多轮指代与澄清、用户消息重试、确认版本绑定、注入文本不能获得写权限 |
| 天气适配测试 | 实况／预测区分；过期缓存、超时、范围不足与空字段都不伪装晴天 |
| 真实 API 联调 | DTO 状态完整传递；AI 到点不中断；退出后按当前事实显示；离线恢复不复活已请假实例 |
| 全新环境检查 | 无旧目录 import、旧 .env / .data / .venv 依赖；新库初始化、依赖锁定与最小配置可独立运行 |

本轮只做静态证据核对与文档检查，没有重跑后端测试；[旧研读记录](../CODEBASE_REVIEW.md)中的 59 passed 是历史基线。
该数字不证明新契约或上述新增状态已实现；后续迁入必须在新项目实际运行并记录命令、结果及环境。

## 10. 主要风险与实施前的决策点

最高风险是把旧开始时间编码当稳定实例身份、把时间结束当 missed、把前端延迟显示当事件延后开始。
其次是草稿候选替换造成静默丢项、只在预览查冲突、仅在模型提示中限制写权限、错误重试导致重复提交。
旧固定窗口查询与单用户假设不能直接扩成多用户服务；缓存与会话数据必须遵循同一 owner 边界。
供应商不可用必须显式降级，避免 AI 声称未落库内容已保存或天气失败时给出假实况。
尚需产品决定：提醒策略与再提醒、正式“知道了”收起范围、部分重叠／切换冲突、重复系列编辑范围。
尚需产品决定：柔性任务完成生命周期、截止精度表达、定位／天气供应商、登录同步和部署方式。
未决项不阻止定义独立架构和正确性测试，但依赖其行为的功能不能以实现者猜测静默落地。
