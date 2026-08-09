<template>
  <div class="page">
    <div class="page-header">
      <div>
        <el-button link @click="router.back()"><ArrowLeft />返回文件列表</el-button>
        <h1 class="page-title">{{ file.original_name || '文件详情' }}</h1>
        <p class="page-description">查看原文、解析进度与文本块。</p>
      </div>
      <el-button @click="loadPreview">预览原文</el-button>
    </div>

    <PageState :loading="loading" :error="error" @retry="load">
      <div class="card card-body">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="所属课程">{{ file.course_name }}</el-descriptions-item>
          <el-descriptions-item label="文件类型">{{ file.file_type }}</el-descriptions-item>
          <el-descriptions-item label="状态"><StatusTag :value="file.parse_status" /></el-descriptions-item>
          <el-descriptions-item label="字符数量">{{ file.char_count }}</el-descriptions-item>
          <el-descriptions-item label="文本块数量">{{ file.chunk_count }}</el-descriptions-item>
          <el-descriptions-item label="解析进度"><el-progress :percentage="file.parse_progress" /></el-descriptions-item>
          <el-descriptions-item v-if="file.error_message" label="失败原因" :span="3">
            <el-text type="danger">{{ file.error_message }}</el-text>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="card" style="margin-top: 18px">
        <div class="card-header">
          <span class="card-title">文本块</span>
          <el-button @click="loadChunks">刷新</el-button>
        </div>
        <el-table :data="chunks">
          <el-table-column prop="chunk_index" label="编号" width="80" />
          <el-table-column prop="page_number" label="页码" width="70" />
          <el-table-column prop="content" label="内容" min-width="500" show-overflow-tooltip />
          <el-table-column prop="char_count" label="字符数" width="90" />
          <el-table-column label="向量状态" width="110">
            <template #default="scope"><StatusTag :value="scope.row.vector_status" /></template>
          </el-table-column>
        </el-table>
        <div class="chunk-pagination">
          <el-pagination
            v-if="total > pageSize"
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="prev, pager, next, jumper, total"
            @current-change="loadChunks"
          />
        </div>
      </div>
    </PageState>

    <el-drawer v-model="drawer" title="原文预览" size="65%">
      <pre class="preview">{{ preview }}</pre>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { knowledgeApi } from '../../api'
import PageState from '../../components/PageState.vue'
import StatusTag from '../../components/StatusTag.vue'

const route = useRoute()
const router = useRouter()
const file = ref({})
const chunks = ref([])
const loading = ref(true)
const error = ref('')
const drawer = ref(false)
const preview = ref('')
const page = ref(1)
const pageSize = 100
const total = ref(0)

const loadChunks = async () => {
  const data = await knowledgeApi.chunks(route.params.id, {
    page: page.value,
    page_size: pageSize,
  })
  chunks.value = data.items
  total.value = data.total
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    file.value = await knowledgeApi.file(route.params.id)
    await loadChunks()
  } catch (exception) {
    error.value = exception.message
  } finally {
    loading.value = false
  }
}

const loadPreview = async () => {
  const data = await knowledgeApi.preview(route.params.id)
  preview.value = data.text
  drawer.value = true
}

onMounted(load)
</script>

<style scoped>
.preview {
  white-space: pre-wrap;
  line-height: 1.8;
  font-family: inherit;
  margin: 0;
}

.chunk-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px;
}
</style>
