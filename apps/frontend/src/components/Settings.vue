<template>
  <a-modal
    v-model:open="store.showSettings"
    title="LLM 설정"
    :footer="null"
    :width="480"
    :bodyStyle="{ padding: '24px' }"
    @cancel="store.showSettings = false"
  >
    <a-form
      :model="store.settings"
      layout="vertical"
      class="settings-form"
    >
      <a-form-item label="Endpoint URL" name="endpointUrl">
        <a-input
          v-model:value="store.settings.endpointUrl"
          placeholder="http://localhost:11434/v1"
          allow-clear
        >
          <template #prefix>
            <LinkOutlined class="text-gray-500" />
          </template>
        </a-input>
      </a-form-item>

      <a-form-item label="API Key" name="apiKey">
        <a-input-password
          v-model:value="store.settings.apiKey"
          placeholder="Enter API key (e.g. ollama)"
          autocomplete="off"
        >
          <template #prefix>
            <KeyOutlined class="text-gray-500" />
          </template>
        </a-input-password>
      </a-form-item>

      <a-form-item label="Model Name" name="model">
        <a-input
          v-model:value="store.settings.model"
          placeholder="llama3"
          allow-clear
        >
          <template #prefix>
            <RobotOutlined class="text-gray-500" />
          </template>
        </a-input>
      </a-form-item>

      <a-form-item class="mb-0">
        <div class="flex gap-2 justify-end">
          <a-button @click="store.showSettings = false">Cancel</a-button>
          <a-button type="primary" @click="handleSave">
            <template #icon><SaveOutlined /></template>
            Save
          </a-button>
        </div>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { LinkOutlined, KeyOutlined, RobotOutlined, SaveOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useChatStore } from '@/stores/chat'

const store = useChatStore()

function handleSave() {
  store.saveSettings()
  store.showSettings = false
  message.success('Settings saved successfully')
}
</script>

<style scoped>
.settings-form :deep(.ant-form-item-label > label) {
  color: #d1d5db;
  font-size: 13px;
}
.settings-form :deep(.ant-input),
.settings-form :deep(.ant-input-password) {
  background: #1e2130;
  border-color: #2d3148;
  color: #e5e7eb;
}
.settings-form :deep(.ant-input:focus),
.settings-form :deep(.ant-input-affix-wrapper:focus),
.settings-form :deep(.ant-input-affix-wrapper-focused) {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}
.settings-form :deep(.ant-input-affix-wrapper) {
  background: #1e2130;
  border-color: #2d3148;
}
.settings-form :deep(.ant-input-affix-wrapper input) {
  background: transparent;
  color: #e5e7eb;
}
.settings-form :deep(.ant-input::placeholder),
.settings-form :deep(.ant-input-password input::placeholder) {
  color: #4b5563;
}
.settings-form :deep(.ant-input-password-icon) {
  color: #6b7280;
}
.settings-form :deep(.ant-input-clear-icon) {
  color: #6b7280;
}
</style>
