# 第一版接口补充契约

状态：拟定，2026-09-25。端点集合继承 [第一版规划](../../第一版规划.md)，本文补齐开发所需语义；尚未发布或实现。涉及冲突窗口及错误字段的前端配合将在联调阶段同步。

## 边界输入

API 前缀 /api/v1；JSON 使用 snake_case。输入 text 1–4000 字符，单次解析最多 10 个候选。时区必须是有效 IANA 标识。单次事件时长大于 0 且不超过 7 天；重复事件单次时长大于 0 且不超过 24 小时。超出返回明确的 UNSUPPORTED_DURATION，不静默截断。

weekdays 使用 ISO 星期 1–7；until_date 为原时区下最后允许开始的日期，含该日。跨午夜使用 end_day_offset。重复初版仅 daily 和 weekly。

请求范围必须 from < to 且跨度不超过 90 天；展开查询还要包含在 from 之前开始、但结束晚于 from 的跨夜实例。相邻区间 end == start 不算冲突。

## 草稿生命周期

needs_clarification → ready → committed。柔性任务或不支持的规则返回 422，不创建可提交草稿。

reference_now 和 timezone 在首次解析时固定。草稿有效期 30 分钟；过期返回 DRAFT_EXPIRED，保留原输入以便重新解析。澄清与编辑必须提供 revision，成功递增；重复或过时版本返回 409。

候选须包括 title、timezone 和 single/recurring 对应时间字段。初次录入中的请假例外关联到候选临时 ID，确认时一并映射正式 event_id 并原子写入；仅在该例外对应的实例真实存在时允许提交。

ready 返回的结构包括：

```json
{
  "draft_id": "opaque-id",
  "revision": 1,
  "status": "ready",
  "candidates": [],
  "questions": [],
  "conflicts": [],
  "conflict_check": {
    "from": "2026-09-25T00:00:00Z",
    "to": "2026-12-24T00:00:00Z",
    "covers_entire_series": false
  }
}
```

以上是字段形状示例；真正 ready 草稿必须至少包含一个有效候选。冲突同时检查候选之间和已存事件之间；例外失效实例不参与冲突。

## 提交与幂等

提交参数继承 revision、idempotency_key、allow_conflicts；冲突确认同时提交最后一次预览的 conflict_revision（冲突集合指纹）。如果保存前冲突集合变化，返回 CONFLICT_CHANGED 并要求重新查看，不沿用旧确认。

唯一键保存请求摘要和结果。相同键/相同内容返回原结果，相同键/不同内容返回 IDEMPOTENCY_KEY_REUSED。草稿只允许提交一次；网络重试不得产生第二组事件。幂等写入和事件写入必须在同一事务中。

确认失败整批回滚，包含例外和草稿状态。已提交草稿不能继续编辑。

## 事件与例外

PATCH /events/{id}、DELETE /events/{id} 需 version；DELETE 通过查询参数 version 传入。版本过时返回 VERSION_CONFLICT。删除系列显式级联删除其例外，事务失败则全部保留。

occurrence_id 是服务端生成的不透明标识；内部包含事件 ID 与原始本地计划开始时间，对夏令时重复钟点增加 offset/fold 区分。不存在、超出规则或早已改变的实例不能创建例外。

相同实例重复提交相同例外返回原结果；同一实例已是另一种例外时返回 EXCEPTION_CONFLICT，初版不提供隐式覆盖或撤销接口。

对于无限重复系列遇到未来 DST 空缺/重叠时，不静默移动时间：创建/修改时需确认明确策略。初版缺省要求澄清；可确认跳过不存在的本地时刻，以及重叠时采用较早/较晚偏移，并将 gap_policy、fold_policy 存到系列。实际已选单次时刻也需明确偏移。这是对原需求中“夏令时要求澄清”的实现补充。

## 当前状态

```json
{
  "server_now": "2026-09-25T06:00:00Z",
  "active_occurrences": [],
  "next_transition_at": null
}
```

active 判定严格为 start_at ≤ now < end_at；excused/cancelled 不参与。active 不代表已出席。返回全部同时进行实例，排序为 start_at、occurrence_id。

next_transition_at 为查询时刻之后最近的有效开始或结束边界，只向前查 90 天，无结果返回 null；客户端定期重新查询，null 不表示此后永远没有事件。边界可含当前 active 实例结束时间。

## 错误语义

统一响应：code、message、field_errors、retryable、request_id。

| HTTP | 代码示例 | 行为 |
| --- | --- | --- |
| 404 | EVENT_NOT_FOUND / OCCURRENCE_NOT_FOUND | 刷新已有数据 |
| 409 | VERSION_CONFLICT / CONFLICT_CHANGED / SERIES_HAS_EXCEPTIONS | 重新检查后提交 |
| 410 | DRAFT_EXPIRED | 用保留原文重新解析 |
| 422 | INVALID_TIME / UNSUPPORTED_TASK / INVALID_TIMEZONE | 修改输入 |
| 502 | MODEL_INVALID_OUTPUT | 原文保留，不写正式事件 |
| 503 | MODEL_UNAVAILABLE / STORAGE_BUSY | 有界重试 |
| 504 | MODEL_TIMEOUT | 提示重试，不隐式保存 |

模型错误不返回供应商原始响应或密钥。业务日志用 request_id 关联。未配置供应商时解析接口返回 MODEL_UNAVAILABLE，已保存事件查询仍正常。
