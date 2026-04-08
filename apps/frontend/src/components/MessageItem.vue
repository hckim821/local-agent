<template>
  <div
    class="flex gap-3 mb-4"
    :class="isUser ? 'flex-row-reverse' : 'flex-row'"
  >
    <!-- Avatar -->
    <div
      class="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm"
      :class="isUser ? 'bg-blue-600' : 'bg-gray-700'"
    >
      <UserOutlined v-if="isUser" />
      <RobotOutlined v-else />
    </div>

    <!-- Message content -->
    <div class="flex flex-col max-w-[75%]" :class="isUser ? 'items-end' : 'items-start'">
      <!-- Bubble -->
      <div
        class="px-4 py-3 rounded-2xl text-sm leading-relaxed"
        :class="[
          isUser
            ? 'bg-blue-600 text-white rounded-tr-sm'
            : 'bg-[#1e2130] text-gray-200 rounded-tl-sm',
          'max-w-full'
        ]"
        style="white-space: pre-wrap; word-break: break-word;"
      >
        <span>{{ message.content }}</span>
        <span
          v-if="message.isStreaming"
          class="inline-block w-0.5 h-4 bg-current ml-0.5 align-middle animate-pulse"
        >|</span>
        <span v-if="!message.content && message.isStreaming" class="text-gray-400 italic">
          thinking...
        </span>
      </div>

      <!-- Skill result card -->
      <div v-if="message.skillResult" class="mt-2 w-full max-w-md">
        <a-card
          size="small"
          :bordered="true"
          class="skill-card"
          :style="{ background: '#141722', borderColor: '#2d3148' }"
        >
          <template #title>
            <div class="flex items-center gap-2 text-xs">
              <ApiOutlined class="text-blue-400" />
              <span class="text-gray-300 font-medium">
                Skill: {{ message.skillResult.skillName }}
              </span>
            </div>
          </template>
          <div class="flex items-center gap-2">
            <a-tag
              v-if="message.skillResult.status === 'running'"
              color="processing"
            >
              running
            </a-tag>
            <a-tag
              v-else-if="message.skillResult.status === 'success'"
              color="success"
            >
              success
            </a-tag>
            <a-tag
              v-else-if="message.skillResult.status === 'error'"
              color="error"
            >
              error
            </a-tag>
            <span class="text-xs text-gray-400">{{ message.skillResult.message }}</span>
          </div>
        </a-card>
      </div>

      <!-- Timestamp -->
      <span class="text-xs text-gray-600 mt-1 px-1">{{ formattedTime }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { UserOutlined, RobotOutlined, ApiOutlined } from '@ant-design/icons-vue'
import type { Message } from '@/types'

const props = defineProps<{
  message: Message
}>()

const isUser = computed(() => props.message.role === 'user')

const formattedTime = computed(() => {
  const d = props.message.timestamp
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
})
</script>

<style scoped>
.skill-card :deep(.ant-card-head) {
  min-height: 36px;
  padding: 0 12px;
  border-bottom-color: #2d3148;
}
.skill-card :deep(.ant-card-body) {
  padding: 8px 12px;
}
</style>
