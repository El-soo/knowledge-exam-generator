<template>
  <div class="page">
    <div class="page-header"><div><h1 class="page-title">生成任务</h1><p class="page-description">查看批量出题进度、成功数量和未补齐原因。</p></div><el-button type="primary" @click="router.push('/generation/create')">新建出题任务</el-button></div>
    <div class="card"><PageState :loading="loading" :empty="!items.length" empty-text="还没有生成任务。">
      <el-table :data="items">
        <el-table-column prop="id" label="任务ID" width="90" />
        <el-table-column prop="course_name" label="课程" min-width="140" />
        <el-table-column label="进度" width="190"><template #default="scope"><el-progress :percentage="scope.row.progress" /></template></el-table-column>
        <el-table-column prop="total_count" label="目标" width="70" />
        <el-table-column prop="success_count" label="成功" width="70" />
        <el-table-column prop="failed_count" label="待补" width="70" />
        <el-table-column label="状态" width="100"><template #default="scope"><StatusTag :value="scope.row.status" /></template></el-table-column>
        <el-table-column prop="error_message" label="结果说明" min-width="280" show-overflow-tooltip><template #default="scope">{{ scope.row.error_message || '任务正常' }}</template></el-table-column>
        <el-table-column prop="model_name" label="模型" width="130" />
        <el-table-column label="创建时间" width="170"><template #default="scope">{{ new Date(scope.row.created_at).toLocaleString() }}</template></el-table-column>
        <el-table-column label="操作" width="230" fixed="right"><template #default="scope"><el-button link type="primary" @click="router.push(`/generation/tasks/${scope.row.id}`)">详情</el-button><el-button v-if="['WAITING','RUNNING'].includes(scope.row.status)" link type="danger" :loading="cancellingId === scope.row.id" @click="cancel(scope.row)">取消</el-button><el-button v-if="['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(scope.row.status)" link @click="retry(scope.row)">重试</el-button><el-button v-if="!['WAITING','RUNNING'].includes(scope.row.status)" link type="danger" @click="remove(scope.row)">删除</el-button></template></el-table-column>
      </el-table>
    </PageState></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { generationApi } from '../../api'
import PageState from '../../components/PageState.vue'
import StatusTag from '../../components/StatusTag.vue'

const router = useRouter()
const items = ref([])
const loading = ref(true)
const cancellingId = ref(null)
let timer
const load = async () => { const data = await generationApi.list({ page_size: 100 }); items.value = data.items; loading.value = false }
const cancel = async task => {
  cancellingId.value = task.id
  try {
    const result = await generationApi.cancel(task.id)
    const index = items.value.findIndex(item => item.id === task.id)
    if (index >= 0) items.value[index] = { ...items.value[index], ...result }
    ElMessage.success('任务已取消')
  } finally { cancellingId.value = null }
}
const retry = async task => { const result = await generationApi.retry(task.id); ElMessage.success(`已保留 ${result.success_count} 道成功题目，将补齐 ${result.failed_count} 道`); load() }
const remove = async task => { await ElMessageBox.confirm(`确认删除生成任务 #${task.id} 的记录？已生成题目会继续保留在题库中。`, '删除生成任务', { type: 'warning' }); await generationApi.remove(task.id); ElMessage.success('生成任务记录已删除'); load() }
onMounted(() => { load(); timer = setInterval(load, 3000) })
onUnmounted(() => clearInterval(timer))
</script>
