import { defineStore } from 'pinia'
import { ref } from 'vue'
import { dashboardApi, coursesApi } from '../api'
export const useAppStore = defineStore('app', () => {
  const collapsed = ref(false), health = ref({database:false,ollama:false,worker:false,current_model:'未配置'}), courses = ref([])
  const toggle = () => collapsed.value = !collapsed.value
  const refreshHealth = async()=>{ try{health.value=await dashboardApi.health()}catch{} }
  const loadCourses = async()=>{ const data=await coursesApi.list({page_size:100}); courses.value=data.items||data }
  return { collapsed, health, courses, toggle, refreshHealth, loadCourses }
})
