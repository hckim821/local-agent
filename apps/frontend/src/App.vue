<template>
  <a-config-provider :theme="{ algorithm: darkAlgorithm }">
    <div class="h-screen flex flex-col overflow-hidden">
      <ChatWindow />
      <Settings />
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { theme } from 'ant-design-vue'
import ChatWindow from './components/ChatWindow.vue'
import Settings from './components/Settings.vue'

const { darkAlgorithm } = theme
</script>
