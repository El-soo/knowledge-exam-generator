import axios from 'axios'
import { ElMessage } from 'element-plus'
const request = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1', timeout: 30000 })
request.interceptors.response.use(response => {
  const body = response.data
  if (body && typeof body.code !== 'undefined') {
    if (body.code !== 0) return Promise.reject(new Error(body.message || '请求失败'))
    return body.data
  }
  return body
}, error => {
  const message = error.response?.data?.message || (error.code === 'ECONNABORTED' ? '请求超时，请检查Ollama状态或稍后重试。' : error.message || '网络请求失败')
  ElMessage.error(message)
  return Promise.reject(new Error(message))
})
export default request
