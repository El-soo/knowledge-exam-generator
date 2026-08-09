<template>
  <div class="page">
    <div class="page-header">
      <div>
        <el-button link @click="router.push('/papers')"><ArrowLeft />返回试卷列表</el-button>
        <h1 class="page-title">试卷质量分析</h1>
        <p class="page-description">从难度、知识覆盖、题型平衡、重复控制和完整性分析试卷。</p>
      </div>
      <el-button type="primary" :loading="loading" @click="load"><Refresh />重新分析</el-button>
    </div>
    <PageState :loading="loading" :error="error" @retry="load">
      <div class="analysis-grid">
        <div class="score-card card"><div ref="gaugeEl" class="gauge"></div><h2>{{ data.grade }}</h2></div>
        <div class="card card-body dimensions">
          <div v-for="(value, key) in data.dimensions" :key="key">
            <div><span>{{ labels[key] || key }}</span><b>{{ value }}</b></div>
            <el-progress :percentage="value" :color="color(value)" />
          </div>
        </div>
        <div class="card"><div class="card-header"><span class="card-title">综合维度</span></div><div ref="radarEl" class="radar"></div></div>
      </div>
      <div class="issues-grid">
        <div class="card card-body"><h3>发现的问题</h3><el-alert v-for="item in data.issues" :key="item" :title="item" type="warning" show-icon :closable="false" /><el-empty v-if="!data.issues?.length" description="未发现明显问题" :image-size="70" /></div>
        <div class="card card-body"><h3>优化建议</h3><el-alert v-for="item in data.suggestions" :key="item" :title="item" type="info" show-icon :closable="false" /><el-empty v-if="!data.suggestions?.length" description="当前没有额外建议" :image-size="70" /></div>
      </div>
    </PageState>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { papersApi } from '../../api'
import PageState from '../../components/PageState.vue'

const route = useRoute()
const router = useRouter()
const data = ref({ dimensions: {}, issues: [], suggestions: [] })
const loading = ref(true)
const error = ref('')
const gaugeEl = ref(null)
const radarEl = ref(null)
const labels = { difficulty_balance: '难度平衡', knowledge_coverage: '知识覆盖', question_type_balance: '题型平衡', duplication_control: '重复控制', completeness: '内容完整' }
let charts = []

const color = value => value >= 90 ? '#16a874' : value >= 75 ? '#1677ff' : value >= 60 ? '#f59e0b' : '#ef4444'
const disposeCharts = () => {
  charts.forEach(chart => chart.dispose())
  charts = []
}
const renderCharts = () => {
  if (!gaugeEl.value || !radarEl.value) return
  disposeCharts()
  const gauge = echarts.init(gaugeEl.value)
  const radar = echarts.init(radarEl.value)
  const keys = Object.keys(data.value.dimensions || {})
  gauge.setOption({ series: [{ type: 'gauge', startAngle: 210, endAngle: -30, progress: { show: true, width: 14 }, axisLine: { lineStyle: { width: 14 } }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, pointer: { show: false }, detail: { valueAnimation: true, fontSize: 38, offsetCenter: [0, '8%'], formatter: '{value}分' }, data: [{ value: data.value.total_score || 0 }] }] })
  radar.setOption({ radar: { indicator: keys.map(key => ({ name: labels[key] || key, max: 100 })), radius: '65%' }, series: [{ type: 'radar', data: [{ value: keys.map(key => data.value.dimensions[key]), areaStyle: { color: 'rgba(22,119,255,.18)' }, lineStyle: { color: '#1677ff' } }] }] })
  charts = [gauge, radar]
}
const resizeCharts = () => charts.forEach(chart => chart.resize())
const load = async () => {
  disposeCharts()
  loading.value = true
  error.value = ''
  try {
    data.value = await papersApi.analysis(route.params.id)
  } catch (exception) {
    error.value = exception.message
  } finally {
    loading.value = false
  }
  if (!error.value) {
    await nextTick()
    renderCharts()
  }
}
onMounted(() => {
  window.addEventListener('resize', resizeCharts)
  load()
})
onUnmounted(() => {
  window.removeEventListener('resize', resizeCharts)
  disposeCharts()
})
</script>

<style scoped>
.analysis-grid { display: grid; grid-template-columns: 280px 1fr 1fr; gap: 18px; }
.score-card { text-align: center; }
.score-card h2 { margin-top: -25px; }
.gauge, .radar { height: 300px; }
.dimensions > div { margin-bottom: 17px; }
.dimensions > div > div { display: flex; justify-content: space-between; }
.issues-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
.el-alert { margin: 10px 0; }
@media (max-width: 1100px) { .analysis-grid { grid-template-columns: 1fr 1fr; } .score-card { grid-column: 1 / -1; } }
</style>
