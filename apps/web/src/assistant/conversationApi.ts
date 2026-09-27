import type { components } from '../../../../contracts/backend-api.d.ts'

export type Conversation = components['schemas']['Conversation']
export type MessageRequest = components['schemas']['MessageRequest']
export type MessageResponse = components['schemas']['MessageResponse']
export type MessagePage = components['schemas']['MessagePage']
export type DraftResponse = components['schemas']['DraftResponse']

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json() as Promise<T>
}

export function createConversation(idempotencyKey: string): Promise<Conversation> {
  return jsonRequest('/api/v1/conversations', {
    method: 'POST', headers: { 'Idempotency-Key': idempotencyKey },
  })
}

export function appendConversationTurn(conversationId: string, request: MessageRequest,
  idempotencyKey: string): Promise<MessageResponse> {
  return jsonRequest(`/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(request),
  })
}

export function loadConversation(conversationId: string, cursor?: string): Promise<MessagePage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''
  return jsonRequest(`/api/v1/conversations/${encodeURIComponent(conversationId)}/messages${query}`)
}

export function getConversationDraft(draftId: string): Promise<DraftResponse> {
  return jsonRequest(`/api/v1/drafts/${encodeURIComponent(draftId)}`)
}
