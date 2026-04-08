<template>
  <div class="flex flex-col h-full bg-[#0f1117]">
    <!-- Top bar -->
    <div
      class="flex items-center justify-between px-4 py-3 border-b border-gray-800 bg-[#13151f]"
      style="flex-shrink: 0;"
    >
      <div class="flex items-center gap-2">
        <RobotOutlined class="text-blue-400 text-lg" />
        <span class="text-gray-100 font-semibold text-base">Local AI Assistant</span>
      </div>
      <div class="flex items-center gap-1">
        <!-- Skills panel toggle -->
        <a-tooltip title="Available Skills">
          <a-button
            type="text"
            class="text-gray-400 hover:text-gray-200"
            @click="showSkillsPanel = !showSkillsPanel"
          >
            <template #icon><ApiOutlined /></template>
          </a-button>
        </a-tooltip>

        <!-- Settings button -->
        <a-tooltip title="Settings">
          <a-button
            type="text"
            class="text-gray-400 hover:text-gray-200"
            @click="store.showSettings = true"
          >
            <template #icon><SettingOutlined /></template>
          </a-button>
        </a-tooltip>

        <!-- Reset session -->
        <a-tooltip title="Reset Session">
          <a-button
            type="text"
            class="text-gray-400 hover:text-gray-200"
            @click="handleReset"
          >
            <template #icon><ReloadOutlined /></template>
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- Main area -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Messages area -->
      <div class="flex flex-col flex-1 overflow-hidden">
        <!-- Messages scroll container -->
        <div
          ref="messagesContainer"
          class="flex-1 overflow-y-auto px-4 py-4"
          style="scroll-behavior: smooth;"
        >
          <!-- Empty state -->
          <div
            v-if="store.messages.length === 0"
            class="flex flex-col items-center justify-center h-full text-center"
          >
            <RobotOutlined class="text-5xl text-gray-700 mb-4" />
            <p class="text-gray-500 text-base font-medium">How can I help you today?</p>
            <p class="text-gray-600 text-sm mt-1">Ask me anything or give me a task to perform.</p>
          </div>

          <!-- Message list -->
          <MessageItem
            v-for="msg in store.messages"
            :key="msg.id"
            :message="msg"
          />

          <!-- Loading indicator -->
          <div
            v-if="store.isLoading && lastMessageStreaming"
            class="flex items-center gap-2 px-3 py-2 text-gray-500 text-sm"
          >
            <a-spin size="small" />
            <span>thinking...</span>
          </div>
        </div>

        <!-- Input area -->
        <div
          class="px-4 py-3 border-t border-gray-800 bg-[#13151f]"
          style="flex-shrink: 0;"
        >
          <div class="flex gap-2 items-end">
            <a-textarea
              v-model:value="inputText"
              placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
              :auto-size="{ minRows: 1, maxRows: 6 }"
              :disabled="store.isLoading"
              class="flex-1 chat-input"
              @keydown="handleKeydown"
            />
            <a-button
              type="primary"
              :disabled="store.isLoading || !inputText.trim()"
              :loading="store.isLoading"
              class="send-btn"
              @click="handleSend"
            >
              <template #icon><SendOutlined /></template>
            </a-button>
          </div>
        </div>
      </div>

      <!-- Skills side panel -->
      <transition name="slide">
        <div
          v-if="showSkillsPanel"
          class="w-64 border-l border-gray-800 bg-[#13151f] overflow-y-auto flex-shrink-0"
        >
          <div class="px-3 py-3 border-b border-gray-800">
            <span class="text-gray-300 text-sm font-semibold">Available Skills</span>
          </div>
          <div class="p-3">
            <div v-if="store.skills.length === 0" class="text-gray-600 text-xs text-center py-4">
              No skills loaded
            </div>
            <div
              v-for="skill in store.skills"
              :key="skill.name"
              class="mb-3 p-2 rounded-lg bg-[#1a1d2b] border border-gray-800"
            >
              <div class="text-blue-400 text-xs font-semibold mb-1">{{ skill.name }}</div>
              <div class="text-gray-500 text-xs leading-relaxed">{{ skill.description }}</div>
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import {
  RobotOutlined,
  ReloadOutlined,
  SendOutlined,
  ApiOutlined,
  SettingOutlined
} from '@ant-design/icons-vue'
import { useChatStore } from '@/stores/chat'
import MessageItem from './MessageItem.vue'

const store = useChatStore()
const inputText = ref('')
const messagesContainer = ref<HTMLDivElement | null>(null)
const showSkillsPanel = ref(false)

const lastMessageStreaming = computed(() => {
  const msgs = store.messages
  if (msgs.length === 0) return false
  return msgs[msgs.length - 1].isStreaming === true
})

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

watch(
  () => store.messages.length,
  () => scrollToBottom()
)

watch(
  () => store.messages.map(m => m.content).join(''),
  () => scrollToBottom()
)

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || store.isLoading) return
  inputText.value = ''
  await store.sendMessage(text)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

async function handleReset() {
  await store.resetSession()
}

onMounted(() => {
  store.loadSkills()
})
</script>

<style scoped>
.chat-input :deep(textarea) {
  background: #1e2130 !important;
  border-color: #2d3148 !important;
  color: #e5e7eb !important;
  border-radius: 10px !important;
  resize: none;
}
.chat-input :deep(textarea:focus) {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15) !important;
}
.chat-input :deep(textarea::placeholder) {
  color: #4b5563;
}

.send-btn {
  height: 38px !important;
  width: 38px !important;
  min-width: 38px !important;
  border-radius: 10px !important;
  padding: 0 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}

.slide-enter-active,
.slide-leave-active {
  transition: width 0.25s ease, opacity 0.25s ease;
  overflow: hidden;
}
.slide-enter-from,
.slide-leave-to {
  width: 0 !important;
  opacity: 0;
}
.slide-enter-to,
.slide-leave-from {
  width: 256px;
  opacity: 1;
}
</style>
