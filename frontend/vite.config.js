import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({ plugins: [vue()], server: { port: 5173, strictPort: true, proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }, '/media': { target: 'http://127.0.0.1:8000' } } }, build: { chunkSizeWarningLimit: 1000, rollupOptions: { output: { manualChunks: { vue: ['vue','vue-router','pinia'], element: ['element-plus','@element-plus/icons-vue'], charts: ['echarts'] } } } } })
