import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import * as Icons from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import './styles/index.css'
const app = createApp(App)
Object.entries(Icons).forEach(([name, component]) => app.component(name, component))
app.use(createPinia()).use(router).use(ElementPlus,{locale:zhCn}).mount('#app')
