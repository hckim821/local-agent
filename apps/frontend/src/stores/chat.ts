import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Message, Settings, Skill } from '@/types'
import { streamChat, resetChat, fetchSkills } from '@/api/client'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const isLoading = ref(false)
  const settings = ref<Settings>({
    endpointUrl: localStorage.getItem('llm_endpoint') || 'http://localhost:11434/v1',
    apiKey: localStorage.getItem('llm_api_key') || 'ollama',
    model: localStorage.getItem('llm_model') || 'llama3'
  })
  const skills = ref<Skill[]>([])
  const showSettings = ref(false)

  function saveSettings() {
    localStorage.setItem('llm_endpoint', settings.value.endpointUrl)
    localStorage.setItem('llm_api_key', settings.value.apiKey)
    localStorage.setItem('llm_model', settings.value.model)
  }

  async function sendMessage(content: string) {
    if (isLoading.value || !content.trim()) return

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      timestamp: new Date()
    }
    messages.value.push(userMsg)
    isLoading.value = true

    const assistantMsg: Message = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true
    }
    messages.value.push(assistantMsg)

    try {
      const apiMessages = messages.value
        .filter(m => m.id !== assistantMsg.id)
        .map(m => ({ role: m.role, content: m.content }))

      for await (const chunk of streamChat(apiMessages, settings.value)) {
        if (chunk.startsWith('{"type":"skill_result"')) {
          const result = JSON.parse(chunk)
          assistantMsg.skillResult = {
            status: result.status,
            skillName: result.skillName || '',
            message: result.message,
            data: result.data
          }
        } else {
          assistantMsg.content += chunk
        }
      }
    } catch (error: unknown) {
      assistantMsg.content = `오류가 발생했습니다: ${error instanceof Error ? error.message : '알 수 없는 오류'}`
    } finally {
      assistantMsg.isStreaming = false
      isLoading.value = false
    }
  }

  async function resetSession() {
    messages.value = []
    await resetChat(settings.value).catch(() => {})
  }

  async function loadSkills() {
    try {
      skills.value = await fetchSkills()
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
