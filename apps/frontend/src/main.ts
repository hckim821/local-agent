import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Antd from 'ant-design-vue'
import App from './App.vue'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(Antd)
app.mount('#app')
