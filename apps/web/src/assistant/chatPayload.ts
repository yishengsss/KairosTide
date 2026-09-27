export interface AssistantChatTextMessage {
  role: 'user' | 'assistant'
  content: string
}

/** Strip view-only message metadata before sending history to the API contract. */
export function toAssistantChatMessages<T extends AssistantChatTextMessage>(messages: readonly T[]): AssistantChatTextMessage[] {
  return messages.map(({ role, content }) => ({ role, content }))
}
