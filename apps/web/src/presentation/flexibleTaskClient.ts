import type { components } from '../../../../contracts/backend-api.d.ts'

export type FlexibleTask = components['schemas']['FlexibleTask']
export type LifecycleTarget = 'active' | 'planned' | 'completed'

export async function transitionFlexibleTaskRequest(
  taskId: string,
  status: LifecycleTarget,
  expectedVersion: number,
  fetcher: typeof fetch = fetch,
): Promise<FlexibleTask> {
  const response = await fetcher(`/api/v1/flexible-tasks/${encodeURIComponent(taskId)}/lifecycle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ status, expected_version: expectedVersion }),
  })
  if (!response.ok) {
    const error = new Error(response.status === 409 ? '任务状态已更新，请重新打开后再试。' : `保存失败（${response.status}）`)
    Object.assign(error, { status: response.status })
    throw error
  }
  return response.json() as Promise<FlexibleTask>
}
