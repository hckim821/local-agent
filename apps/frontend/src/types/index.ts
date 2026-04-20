export interface Message {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  image?: string          // base64 data URL (user messages only)
  timestamp: Date
  isStreaming?: boolean
  toolCalls?: ToolCall[]
  skillResult?: SkillResult
}

export interface ToolCall {
  id: string
  name: string
  args: Record<string, unknown>
}

export interface SkillResult {
  status: 'running' | 'success' | 'error'
  skillName: string
  message: string
  data?: unknown
}

export interface Settings {
  endpointUrl: string
  apiKey: string
  model: string
  wikiPath: string
}

export interface Skill {
  name: string
  description: string
  parameters: Record<string, unknown>
}
