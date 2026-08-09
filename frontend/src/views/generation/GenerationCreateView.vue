<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">AI智能出题</h1>
        <p class="page-description">根据课程自动匹配正式考试风格，生成需要计算、推理或应用的题目。</p>
      </div>
      <el-button @click="router.push('/generation/tasks')">查看生成任务</el-button>
    </div>

    <div class="card card-body generation-card">
      <el-alert
        title="系统会先检索例题、案例、代码、实验或材料，再自动匹配当前学科的正式考试风格。"
        type="info"
        show-icon
        :closable="false"
      />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="generation-form">
        <div class="form-grid">
          <el-form-item label="课程" prop="course">
            <el-select v-model="form.course" style="width:100%">
              <el-option v-for="c in store.courses" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="知识库文件">
            <el-select v-model="form.file_id" clearable style="width:100%" placeholder="可选：限定某个文件">
              <el-option v-for="f in files" :key="f.id" :label="f.original_name" :value="f.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="章节">
            <el-select v-model="form.chapter_id" clearable style="width:100%" placeholder="可选：限定章节">
              <el-option v-for="c in chapters" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="知识点">
            <el-select v-model="form.knowledge_point_id" clearable style="width:100%" placeholder="可选：限定知识点">
              <el-option v-for="p in points" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
          </el-form-item>

          <el-form-item label="设置每种题型的数量" class="full question-type-field">
            <div class="type-grid">
              <div
                v-for="x in types"
                :key="x.value"
                class="type-card"
                :class="{ selected: x.count > 0 }"
              >
                <span class="type-mark">{{ x.short }}</span>
                <span class="type-copy"><b>{{ x.label }}</b><small>{{ x.description }}</small></span>
                <div class="type-count">
                  <span>数量</span>
                  <el-input-number v-model="x.count" :min="0" :max="100" size="small" />
                </div>
              </div>
            </div>
            <div class="distribution">
              <span>已选 {{ selectedTypeCount }} 种题型</span>
              <el-tag v-for="x in selectedTypes" :key="x.value" effect="plain">{{ x.label }} {{ x.count }} 道</el-tag>
              <b class="total-count">共 {{ totalCount }} 道</b>
            </div>
          </el-form-item>

          <el-form-item label="难度">
            <el-select v-model="form.difficulty" style="width:100%">
              <el-option v-for="x in difficultyOptions" :key="x.value" :label="x.label" :value="x.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="单题分值">
            <el-input-number v-model="form.score" :min="0.5" :step="0.5" style="width:100%" />
          </el-form-item>
          <el-form-item label="使用场景">
            <el-select v-model="form.scenario" style="width:100%">
              <el-option v-for="x in scenarios" :key="x" :label="x" :value="x" />
            </el-select>
          </el-form-item>
          <el-form-item label="命题风格">
            <el-select v-model="form.subject_style" style="width:100%">
              <el-option label="自动识别课程（推荐）" value="auto" />
              <el-option label="中国高中数学" value="high_school_math" />
              <el-option label="通用学科考试" value="exam_oriented" />
            </el-select>
          </el-form-item>

          <el-form-item label="智能体协作深度" class="full quality-field">
            <div class="quality-grid">
              <button v-for="mode in qualityModes" :key="mode.value" type="button" class="quality-card" :class="{selected:form.quality_mode===mode.value}" @click="form.quality_mode=mode.value">
                <span>{{mode.short}}</span><div><b>{{mode.label}}</b><small>{{mode.description}}</small></div><el-tag size="small" type="success" effect="plain">默认</el-tag>
              </button>
            </div>
          </el-form-item>

          <el-form-item label="内容保障" class="full guarantees">
            <div class="guarantee-item"><CircleCheckFilled /><span><b>自动生成答案</b><small>每道题必须有明确答案</small></span></div>
            <div class="guarantee-item"><CircleCheckFilled /><span><b>自动生成解析</b><small>解释答案与考查的知识</small></span></div>
            <el-checkbox v-model="form.show_source">保留知识来源</el-checkbox>
            <el-checkbox v-model="form.strict">严格依据知识库</el-checkbox>
          </el-form-item>
          <el-form-item label="补充要求" class="full">
            <el-input v-model="form.supplement" type="textarea" :rows="4" placeholder="例如：重点考查实际应用，避免偏题怪题。" />
          </el-form-item>
        </div>
        <el-button type="primary" size="large" :loading="submitting" @click="submit">
          <MagicStick />开始生成题目
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { generationApi, knowledgeApi } from '../../api'
import { useAppStore } from '../../stores/app'

const router = useRouter()
const store = useAppStore()
const formRef = ref()
const files = ref([])
const chapters = ref([])
const points = ref([])
const submitting = ref(false)

const form = reactive({
  course: '', file_id: '', chapter_id: '', knowledge_point_id: '',
  difficulty: '中等', score: 2,
  scenario: '课堂练习', generate_answer: true, generate_analysis: true,
  show_source: true, strict: true, supplement: '', subject_style: 'auto'
  , quality_mode: 'DEEP'
})

const rules = {
  course: [{ required: true, message: '请选择课程' }]
}

const types = reactive([
  ['single_choice', '单项选择题', '单', '通过计算或推理，从4个选项中选出唯一答案', 5],
  ['multiple_choice', '多项选择题', '多', '多个正确答案，考查综合理解', 0],
  ['judge', '判断题', '判', '判断概念或技术表述是否正确', 0],
  ['fill_blank', '填空题', '填', '填写数值、区间、解析式或明确结论', 0],
  ['term_explanation', '名词解释题', '名', '准确解释专业概念', 0],
  ['short_answer', '简答题', '答', '完成解答、证明或说明关键步骤', 0],
  ['essay', '论述题', '论', '系统分析原理、特点与应用', 0],
  ['calculation', '计算/解答题', '算', '按高中数学规范写出推理、计算和结论', 0],
  ['programming', '编程设计题', '程', '包含题目要求、参考代码与评分点', 0],
  ['case_analysis', '案例分析题', '案', '运用知识解决具体问题', 0]
].map(([value, label, short, description, count]) => ({ value, label, short, description, count })))

const scenarios = ['课堂练习', '章节测试', '专项训练', '期中复习', '期末复习', '综合测试']
const difficultyOptions = [
  {value:'简单', label:'简单（原中等题难度）'},
  {value:'中等', label:'中等（原困难题难度）'},
  {value:'困难', label:'困难（特难/压轴题难度）'}
]
const qualityModes = [
  {value:'DEEP',short:'深',label:'深度模式',description:'每题生成3个候选择优，启用智能体独立验算、规则审核并允许两轮返工。'}
]
const flatten = list => list.flatMap(item => [item, ...flatten(item.children || [])])

const selectedTypes = computed(() => types.filter(item => Number(item.count) > 0))
const selectedTypeCount = computed(() => selectedTypes.value.length)
const totalCount = computed(() => selectedTypes.value.reduce((total, item) => total + Number(item.count), 0))

watch(() => form.course, async id => {
  form.file_id = ''
  form.chapter_id = ''
  form.knowledge_point_id = ''
  if (!id) return
  const [fileData, chapterData, pointData] = await Promise.all([
    knowledgeApi.files({ course: id, status: 'SUCCESS', page_size: 100 }),
    knowledgeApi.chapters({ course: id }),
    knowledgeApi.points({ course: id, page_size: 100 })
  ])
  files.value = fileData.items
  chapters.value = flatten(chapterData)
  points.value = pointData.items
})

const submit = async () => {
  await formRef.value.validate()
  if (totalCount.value < 1) return ElMessage.warning('请至少设置一种题型的数量。')
  if (totalCount.value > 100) return ElMessage.warning('单次出题总数不能超过100道。')
  const typeCounts = Object.fromEntries(selectedTypes.value.map(item => [item.value, Number(item.count)]))
  const payload = { ...form, type_counts: typeCounts, question_types: Object.keys(typeCounts), count: totalCount.value }
  submitting.value = true
  try {
    const task = await generationApi.create(payload)
    ElMessage.success('出题任务已创建，系统正在后台生成答案和解析。')
    router.push(`/generation/tasks/${task.id}`)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await store.loadCourses()
  form.course = store.courses[0]?.id || ''
})
</script>

<style scoped>
.generation-card { max-width: 1040px; }
.generation-form { margin-top: 20px; }
.question-type-field :deep(.el-form-item__content) { display: block; }
.type-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; width: 100%; }
.type-card { position: relative; display: grid; grid-template-columns: 42px minmax(0, 1fr) 138px; align-items: center; gap: 11px; min-height: 76px; padding: 11px 12px; border: 1px solid var(--border-color, #e5e7eb); border-radius: 10px; background: #fff; transition: border-color .18s ease, background .18s ease, box-shadow .18s ease; }
.type-card:hover { border-color: #91caff; box-shadow: 0 4px 14px rgba(22, 119, 255, .08); }
.type-card.selected { border-color: #1677ff; background: #f5f9ff; box-shadow: 0 0 0 1px rgba(22, 119, 255, .1); }
.type-mark { display: grid; place-items: center; width: 40px; height: 40px; color: #1677ff; background: #eaf3ff; border-radius: 9px; font-size: 16px; font-weight: 700; }
.type-card.selected .type-mark { color: #fff; background: #1677ff; }
.type-copy { display: flex; flex-direction: column; min-width: 0; line-height: 1.35; }
.type-copy b { color: #1f2937; font-size: 14px; }
.type-copy small { margin-top: 4px; color: #6b7280; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.type-count { display: flex; align-items: center; gap: 7px; color: #6b7280; font-size: 12px; }
.type-count :deep(.el-input-number) { width: 104px; }
.distribution { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin-top: 12px; padding: 10px 12px; color: #6b7280; background: #f8fafc; border-radius: 8px; }
.distribution > span { margin-right: 3px; font-size: 13px; }
.total-count { margin-left: auto; color: #1677ff; font-size: 15px; }
.guarantees :deep(.el-form-item__content) { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.guarantee-item { display: flex; align-items: center; gap: 8px; min-width: 210px; padding: 10px 12px; color: #1677ff; background: #f0f7ff; border-radius: 9px; }
.guarantee-item svg { width: 20px; }
.guarantee-item span { display: flex; flex-direction: column; color: #1f2937; line-height: 1.3; }
.guarantee-item small { margin-top: 2px; color: #6b7280; }
.quality-field :deep(.el-form-item__content){display:block}.quality-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;width:100%}.quality-card{display:grid;grid-template-columns:40px 1fr auto;align-items:center;gap:11px;padding:13px;text-align:left;border:1px solid var(--border);border-radius:10px;background:#fff;color:var(--text);cursor:pointer}.quality-card>span{display:grid;place-items:center;width:38px;height:38px;border-radius:10px;background:#eef3f9;color:#5d6b80;font-weight:800}.quality-card b,.quality-card small{display:block}.quality-card small{margin-top:3px;color:var(--text-secondary);font-size:11px;line-height:1.5}.quality-card.selected{border-color:#13a8a8;background:#f3fbfb;box-shadow:0 0 0 1px rgba(19,168,168,.1)}.quality-card.selected>span{color:#fff;background:#13a8a8}
@media (max-width: 900px) { .type-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .type-card { transition: none; } }
</style>
