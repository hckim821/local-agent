import axios from 'axios'
import type { Settings } from '@/types'

const BASE_URL = 'http://localhost:8000'

export function createApiClient(settings: Settings) {
  return axios.create({
    baseURL: BASE_URL,
    headers: {
      'Content-Type': 'application/json',
      'X-LLM-Endpoint': settings.endpointUrl,
      'X-LLM-Key': settings.apiKey,
      ...(settings.wikiPath ? { 'X-Wiki-Path': settings.wikiPath } : {})
    }
  })
}

export async function fetchSkills() {
  const res = await axios.get(`${BASE_URL}/api/skills`)
  return res.data
}

export async function connectWiki(wikiPath: string | null) {
  const res = await axios.post(`${BASE_URL}/api/wiki/connect`, null, {
    headers: wikiPath ? { 'X-Wiki-Path': wikiPath } : {}
  })
  return res.data
}

export async function resetChat(settings: Settings) {
  const client = createApiClient(settings)
  await client.post('/api/chat/reset')
}

// Streaming chat via SSE with proper partial-chunk handling
export async function* streamChat(
  messages: Array<{role: string, content: string}>,
  settings: Settings,
  image?: string
): AsyncGenerator<string> {
  const response = await fetch(`${BASE_URL}/api/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-LLM-Endpoint': settings.endpointUrl,
      'X-LLM-Key': settings.apiKey,
      ...(settings.wikiPath ? { 'X-Wiki-Path': settings.wikiPath } : {})
    },
    body: JSON.stringify({
      messages,
      model: settings.model,
      stream: true,
      ...(image ? { image } : {})
    })
  })

  if (!response.ok) {
    throw new Error(`서버 오류: ${response.status} ${response.statusText}`)
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  // Accumulate across TCP reads to handle partial SSE lines
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // Process all complete lines from the buffer
    const lines = buffer.split('\n')
    // Keep the last (possibly incomplete) line in the buffer
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6).trim()
      if (data === '[DONE]') return
      try {
        const parsed = JSON.parse(data)
        if (parsed.error) {
          yield `\n⚠️ 오류: ${parsed.error}`
          return
        }
        if (parsed.done && !parsed.content) return
        if (parsed.content) yield parsed.content
        if (parsed.skill_result) yield JSON.stringify({ type: 'skill_result', ...parsed.skill_result })
      } catch {}
    }
  }
}
