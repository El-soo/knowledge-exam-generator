<template>
  <div class="page">
    <div class="page-header">
      <div>
        <el-button link @click="router.push('/generation/tasks')"><ArrowLeft />返回任务列表</el-button>
        <h1 class="page-title">生成任务 #{{ task.id }}</h1>
        <p class="page-description">模型：{{ task.model_name || '等待分配' }} · {{ modeLabel(task.quality_mode) }} · Embedding：{{ task.embedding_model || '等待分配' }}</p>
      </div>
      <div>
        <el-button v-if="task.workflow_id" @click="router.push(`/agents/workflows/${task.workflow_id}`)"><Share />查看协作轨迹</el-button>
        <el-button v-if="task.status === 'FAILED'" type="primary" :loading="retrying" @click="retry">重试补齐缺失题目</el-button>
        <el-button v-if="['WAITING', 'RUNNING'].includes(task.status)" type="danger" plain :loading="cancelling" @click="cancel">取消任务</el-button>
      </div>
    </div>

    <div v-if="task.agent_steps?.length" class="agent-strip card">
      <div v-for="(step,index) in task.agent_steps" :key="step.id" class="agent-chip" :class="step.status.toLowerCase()"><span>{{index+1}}</span><div><small>{{step.agent_name}}</small><b>{{step.step_name}}</b></div><i v-if="index<task.agent_steps.length-1" /></div>
    </div>

    <div class="card card-body">
      <div class="task-head">
        <StatusTag :value="task.status" />
        <span>目标 {{ task.total_count }} 道</span>
        <span>成功 {{ task.success_count }} 道</span>
        <span v-if="task.retained_count !== undefined && task.retained_count !== task.success_count">去重后保留 {{ task.retained_count }} 道</span>
        <span>待补 {{ task.failed_count }} 道</span>
      </div>
      <el-progress :percentage="task.progress || 0" :status="task.status === 'FAILED' ? 'exception' : task.status === 'SUCCESS' ? 'success' : ''" :stroke-width="14" />
      <el-alert v-if="task.error_message" :title="task.error_message" type="error" show-icon :closable="false" style="margin-top: 16px" />
      <div v-if="task.status === 'FAILED' && task.config?.failure_details?.length" class="failure-details">
        <div class="failure-title"><strong>为什么有题目没有生成？</strong><span>不合格的模型输出已被丢弃，不会混入题库。</span></div>
        <div v-for="(detail, index) in task.config.failure_details" :key="`${detail.batch}-${index}`" class="failure-item">
          <el-tag size="small" type="warning">{{ detail.question_type ? typeLabel(detail.question_type) : `第${detail.batch}批` }}</el-tag>
          <span>{{ detail.reason }}</span>
        </div>
      </div>
    </div>

    <div class="result-card card">
      <div class="card-header result-header">
        <div>
          <span class="card-title">已生成题目</span>
          <p>答案和解析直接显示在每道题下方，无需逐题点开。</p>
        </div>
        <div><el-checkbox v-if="task.questions?.length" :model-value="allSelected" @change="toggleAll">全选</el-checkbox><el-tag v-if="task.questions?.length" type="success" effect="plain">共 {{ task.questions.length }} 道</el-tag></div>
      </div>
      <PageState :loading="loading" :empty="!task.questions?.length" empty-text="尚未生成题目，页面会自动刷新。">
        <div class="question-list">
          <article v-for="(q, index) in task.questions" :key="q.id" class="question-card">
            <div class="question-meta">
              <el-checkbox :model-value="selectedIds.includes(q.id)" @change="value=>toggleQuestion(q.id,value)" />
              <span class="question-number">{{ index + 1 }}</span>
              <StatusTag :value="q.review_status" />
              <el-tag>{{ typeLabel(q.question_type) }}</el-tag>
              <el-tag type="info">{{ q.difficulty }}</el-tag>
              <span class="question-score">{{ q.score }} 分</span>
            </div>
            <h3><MathText :text="q.stem" /></h3>
            <div v-if="q.options?.length" class="options-grid">
              <div v-for="option in q.options" :key="option.id || option.label" class="option-item" :class="{ correct: isCorrect(q, option) }">
                <span>{{ option.label }}</span>
                <p><MathText :text="option.content" /></p>
              </div>
            </div>
            <div class="answer-panel">
              <div class="answer-row">
                <span class="answer-label">参考答案</span>
                <pre><MathText :text="formatAnswer(q.answer)" /></pre>
              </div>
              <div class="answer-row analysis-row">
                <span class="answer-label">题目解析</span>
                <p><MathText :text="q.analysis || '暂无解析'" /></p>
              </div>
              <div v-if="q.scoring_points?.length" class="answer-row">
                <span class="answer-label">评分要点</span>
                <ul><li v-for="point in q.scoring_points" :key="point"><MathText :text="point" /></li></ul>
              </div>
            </div>
            <div class="question-actions">
              <span v-if="q.knowledge_point_name" class="knowledge-point">知识点：{{ q.knowledge_point_name }}</span>
              <el-button link type="primary" @click="router.push(`/questions/${q.id}`)">编辑与审核</el-button>
            </div>
          </article>
        </div>
      </PageState>
      <div v-if="task.questions?.length" class="review-dock"><span>已选 <b>{{selectedIds.length}}</b> 道，智能体建议不会代替教师最终决定。</span><el-button :disabled="!selectedIds.length" @click="batchReview('revision_ids')">退回修改</el-button><el-button :disabled="!selectedIds.length" type="danger" plain @click="batchReview('reject_ids')">审核不通过</el-button><el-button :disabled="!selectedIds.length" type="success" @click="batchReview('approve_ids')">批量审核通过</el-button></div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { generationApi } from '../../api'
import PageState from '../../components/PageState.vue'
import StatusTag from '../../components/StatusTag.vue'
import MathText from '../../components/MathText.vue'

const route = useRoute()
const router = useRouter()
const task = ref({})
const loading = ref(true)
const retrying = ref(false)
const cancelling = ref(false)
const selectedIds = ref([])
let timer

const typeLabels = {
  single_choice: '单项选择题', multiple_choice: '多项选择题', judge: '判断题', fill_blank: '填空题',
  term_explanation: '名词解释题', short_answer: '简答题', essay: '论述题', calculation: '计算题',
  programming: '编程设计题', case_analysis: '案例分析题'
}
const typeLabel = type => typeLabels[type] || type
const modeLabel = value => ({FAST:'快速模式',STANDARD:'标准模式',DEEP:'深度模式'}[value] || value || '标准模式')
const allSelected = computed(() => Boolean(task.value.questions?.length) && selectedIds.value.length === task.value.questions.length)
const normalizeAnswers = answer => Array.isArray(answer) ? answer : (answer == null ? [] : [answer])
const formatAnswer = answer => normalizeAnswers(answer).map(item => typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)).join('\n') || '暂无答案'
const isCorrect = (question, option) => option.is_correct || normalizeAnswers(question.answer).map(String).includes(String(option.label))

const load = async () => {
  task.value = await generationApi.get(route.params.id)
  loading.value = false
  if (!['WAITING', 'RUNNING'].includes(task.value.workflow_status) && timer) {
    clearInterval(timer)
    timer = null
  }
}
const toggleQuestion = (id, value) => { selectedIds.value = value ? [...new Set([...selectedIds.value, id])] : selectedIds.value.filter(item => item !== id) }
const toggleAll = value => { selectedIds.value = value ? (task.value.questions || []).map(item => item.id) : [] }
const batchReview = async key => { await generationApi.batchReview(task.value.id, { [key]: selectedIds.value }); ElMessage.success('批量审核已完成'); selectedIds.value = []; await load() }
const cancel = async () => {
  cancelling.value = true
  try {
    task.value = await generationApi.cancel(task.value.id)
    ElMessage.success('任务已取消')
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  } finally { cancelling.value = false }
}
const retry = async () => {
  retrying.value = true
  try {
    const result = await generationApi.retry(task.value.id)
    task.value = result
    ElMessage.success(`已保留 ${result.success_count} 道成功题目，只补齐剩余 ${result.failed_count} 道`)
    if (!timer) timer = setInterval(load, 2500)
  } finally { retrying.value = false }
}
onMounted(() => {
  load()
  timer = setInterval(load, 2500)
})
onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped>
.task-head { display: flex; flex-wrap: wrap; gap: 22px; margin-bottom: 18px; }
.agent-strip{display:flex;align-items:center;gap:8px;margin:16px 0;padding:14px 16px;overflow-x:auto}.agent-chip{display:flex;align-items:center;gap:8px;min-width:max-content}.agent-chip>span{display:grid;place-items:center;width:27px;height:27px;border-radius:50%;color:#fff;background:#a5afbf;font-size:11px;font-weight:700}.agent-chip.success>span{background:var(--success)}.agent-chip.running>span{background:var(--primary)}.agent-chip small,.agent-chip b{display:block}.agent-chip small{color:var(--text-secondary);font-size:10px}.agent-chip b{font-size:12px}.agent-chip i{width:28px;height:1px;margin-left:4px;background:#d5dce7}
.failure-details { margin-top: 14px; padding: 14px 16px; border: 1px solid #f6d99a; border-radius: 10px; background: #fffaf0; }
.failure-title { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
.failure-title span { color: var(--text-secondary); font-size: 13px; }
.failure-item { display: flex; align-items: flex-start; gap: 10px; padding: 7px 0; border-top: 1px dashed #eddcb9; line-height: 1.55; }
.failure-item:first-of-type { border-top: 0; }
.result-card { margin-top: 18px; overflow: hidden; }
.result-header { align-items: center; }
.result-header > div p { margin: 5px 0 0; color: var(--text-secondary); font-size: 13px; }
.question-list { padding: 18px; background: #f8faff; }
.question-card { padding: 22px; margin-bottom: 16px; background: #fff; border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 5px 18px rgba(31, 41, 55, .045); }
.question-card:last-child { margin-bottom: 0; }
.question-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.question-number { display: grid; place-items: center; width: 30px; height: 30px; color: #fff; background: var(--primary); border-radius: 9px; font-weight: 700; }
.question-score { margin-left: auto; color: var(--text-secondary); }
.question-card h3 { margin: 18px 0; font-size: 16px; line-height: 1.75; font-weight: 600; color: var(--text); }
.options-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }
.option-item { display: flex; gap: 10px; padding: 11px 13px; border: 1px solid #e6ebf2; border-radius: 9px; background: #fbfcfe; }
.option-item > span { display: grid; place-items: center; flex: 0 0 24px; height: 24px; border-radius: 7px; background: #edf1f7; font-weight: 700; }
.option-item p { margin: 1px 0 0; line-height: 1.55; }
.option-item.correct { border-color: #9fe0c5; background: #f0fbf6; }
.option-item.correct > span { color: #fff; background: #22a66f; }
.answer-panel { border-left: 4px solid #13c2c2; border-radius: 8px; background: #f2fbfb; overflow: hidden; }
.answer-row { display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: 12px; padding: 13px 15px; border-bottom: 1px solid #dceeee; }
.answer-row:last-child { border-bottom: 0; }
.answer-label { color: #087f80; font-weight: 700; }
.answer-row p, .answer-row pre, .answer-row ul { margin: 0; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
.answer-row ul { padding-left: 19px; }
.question-actions { display: flex; align-items: center; justify-content: flex-end; min-height: 34px; margin-top: 10px; }
.knowledge-point { margin-right: auto; color: var(--text-secondary); font-size: 13px; }
.result-header>div:last-child{display:flex;align-items:center;gap:12px}.review-dock{position:sticky;bottom:14px;display:flex;align-items:center;gap:10px;margin:0 18px 18px;padding:13px 16px;border:1px solid #cfe1f7;border-radius:11px;background:rgba(255,255,255,.96);box-shadow:0 12px 30px rgba(35,65,105,.14);backdrop-filter:blur(10px)}.review-dock>span{margin-right:auto;color:var(--text-secondary)}.review-dock b{color:var(--primary)}
@media (max-width: 900px) { .options-grid { grid-template-columns: 1fr; } }
</style>
