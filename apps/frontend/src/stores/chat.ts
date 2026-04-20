import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Message, Settings, Skill } from '@/types'
import { streamChat, resetChat, fetchSkills, connectWiki } from '@/api/client'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const isLoading = ref(false)
  const settings = ref<Settings>({
    endpointUrl: localStorage.getItem('llm_endpoint') || 'http://localhost:11434/v1',
    apiKey: localStorage.getItem('llm_api_key') || 'ollama',
    model: localStorage.getItem('llm_model') || 'llama3',
    wikiPath: localStorage.getItem('wiki_path') || ''
  })
  const skills = ref<Skill[]>([])
  const showSettings = ref(false)

  function saveSettings() {
    localStorage.setItem('llm_endpoint', settings.value.endpointUrl)
    localStorage.setItem('llm_api_key', settings.value.apiKey)
    localStorage.setItem('llm_model', settings.value.model)
    localStorage.setItem('wiki_path', settings.value.wikiPath)
    // 위키 경로가 바뀌었으면 서버에 즉시 반영하고 스킬 목록 갱신
    connectWiki(settings.value.wikiPath || null)
      .then(data => { if (data?.skills) skills.value = data.skills })
      .catch(() => {})
  }

  async function sendMessage(content: string, image?: string) {
    if (isLoading.value || (!content.trim() && !image)) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: content || (image ? '(이미지 첨부)' : ''),
      image,
      timestamp: new Date()
    }
    messages.value.push(userMsg)
    isLoading.value = true

    messages.value.push({
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true
    })
    // Use the reactive proxy that Vue created inside the array
    const assistantIdx = messages.value.length - 1

    try {
      const apiMessages = messages.value
        .slice(0, assistantIdx)
        .map(m => ({ role: m.role, content: m.content }))

      for await (const chunk of streamChat(apiMessages, settings.value, image)) {
        if (chunk.startsWith('{"type":"skill_result"')) {
          const result = JSON.parse(chunk)
          messages.value[assistantIdx].skillResult = {
            status: result.status,
            skillName: result.skillName || '',
            message: result.message,
            data: result.data
          }
        } else {
          messages.value[assistantIdx].content += chunk
        }
      }
    } catch (error: unknown) {
      messages.value[assistantIdx].content = `오류가 발생했습니다: ${error instanceof Error ? error.message : '알 수 없는 오류'}`
    } finally {
      messages.value[assistantIdx].isStreaming = false
      isLoading.value = false
    }
  }

  async function resetSession() {
    messages.value = []
    await resetChat(settings.value).catch(() => {})
  }

  async function loadSkills() {
    try {
      if (settings.value.wikiPath) {
        // 위키 경로가 있으면 서버에 위키 스킬을 먼저 등록하고 목록 수신
        const data = await connectWiki(settings.value.wikiPath)
        if (data?.skills) { skills.value = data.skills; return }
      }
      const data = await fetchSkills()
      skills.value = data.skills ?? []
    } catch {}
  }

  return {
    messages,
    isLoading,
    settings,
    skills,
    showSettings,
    saveSettings,
    sendMessage,
    resetSession,
    loadSkills
  }
})
