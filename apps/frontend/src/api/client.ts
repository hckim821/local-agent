import axios from 'axios'
import type { Settings } from '@/types'

const BASE_URL = 'http://localhost:8000'

export function createApiClient(settings: Settings) {
  return axios.create({
    baseURL: BASE_URL,
    headers: {
      'Content-Type': 'application/json',
      'X-LLM-Endpoint': settings.endpointUrl,
      'X-LLM-Key': settings.apiKey
    }
  })
}

export async function fetchSkills() {
  const res = await axios.get(`${BASE_URL}/api/skills`)
  return res.data
}

export async function resetChat(settings: Settings) {
  const client = createApiClient(settings)
  await client.post('/api/chat/reset')
}

// Streaming chat - returns EventSource-compatible fetch
export async function* streamChat(
  messages: Array<{role: string, content: string}>,
  settings: Settings
): AsyncGenerator<string> {
  const response = await fetch(`${BASE_URL}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-LLM-Endpoint': settings.endpointUrl,
      'X-LLM-Key': settings.apiKey
    },
    body: JSON.stringify({
      messages,
      model: settings.model,
      stream: true
    })
  })

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value)
    const lines = chunk.split('\n')

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim()
        if (data === '[DONE]') return
        try {
          const parsed = JSON.parse(data)
          if (parsed.content) yield parsed.content
          if (parsed.skill_result) yield JSON.stringify({ type: 'skill_result', ...parsed.skill_result })
        } catch {}
      }
    }
  }
}
