<template>
  <div class="page">
    <div class="page-header">
      <div>
        <el-button link @click="router.back()"
          ><ArrowLeft />返回试卷列表</el-button
        >
        <h1 class="page-title">创建试卷</h1>
        <p class="page-description">
          支持手动选题、规则自动选题和自然语言辅助配置规则。
        </p>
      </div>
    </div>
    <el-tabs v-model="mode" class="card create-tabs">
      <el-tab-pane label="手动组卷" name="manual"
        ><ManualPaperForm
      /></el-tab-pane>
      <el-tab-pane label="规则组卷" name="rule"><RulePaperForm /></el-tab-pane>
      <el-tab-pane label="AI辅助组卷" name="ai">
        <div class="card-body ai-workbench">
          <el-alert
            title="AI只负责把自然语言转换成组卷规则，确认后才从已审核题库选题。"
            type="info"
            show-icon
            :closable="false"
          />
          <div class="request-area">
            <el-input
              v-model="naturalText"
              type="textarea"
              :rows="7"
              placeholder="例如：生成一套Python程序设计期末试卷，总分100分，包含10道单选题和5道简答题，难度以中等为主。"
            />
            <div class="request-actions">
              <el-select
                v-model="naturalCourse"
                placeholder="选择课程"
                style="width: 260px"
                ><el-option
                  v-for="course in store.courses"
                  :key="course.id"
                  :label="course.name"
                  :value="course.id"
              /></el-select>
              <el-button type="primary" :loading="parsing" @click="parseRule"
                ><MagicStick />解析组卷要求</el-button
              >
            </div>
            <div v-if="paperWorkflow" class="paper-agent-status"><div><span class="status-dot" :class="{ok:paperWorkflow.status==='AWAITING_REVIEW'}"></span><b>{{paperWorkflow.status==='WAITING'?'等待Worker调度':paperWorkflow.status==='RUNNING'?'组卷智能体正在协作':'结构化规则已完成'}}</b><small v-if="paperWorkflow.current_agent">当前：{{paperWorkflow.current_agent}}</small></div><el-progress :percentage="paperWorkflow.progress||0" /><el-button link type="primary" @click="router.push(`/agents/workflows/${paperWorkflow.id}`)">查看执行轨迹</el-button></div>
          </div>

          <section v-if="parsed" class="rule-sheet">
            <div class="rule-sheet-head">
              <div>
                <span class="eyebrow">AI 解析结果</span>
                <h2>确认并调整组卷规则</h2>
                <p>请检查总分、题型数量和难度比例，确认后再从题库选题。</p>
              </div>
              <el-tag type="success" effect="plain">规则已解析</el-tag>
            </div>

            <div class="rule-metrics">
              <div>
                <span>目标总分</span><strong>{{ parsed.target_score }}</strong
                ><em>分</em>
              </div>
              <div>
                <span>题目总数</span><strong>{{ totalQuestions }}</strong
                ><em>道</em>
              </div>
              <div>
                <span>配置分值</span><strong>{{ calculatedScore }}</strong
                ><em>分</em>
              </div>
            </div>

            <el-form label-position="top" class="rule-form">
              <div class="form-grid">
                <el-form-item label="试卷名称" required
                  ><el-input v-model="parsed.name"
                /></el-form-item>
                <el-form-item label="目标总分" required>
                  <div class="unit-input">
                    <el-input-number
                      v-model="parsed.target_score"
                      :min="1"
                      :max="1000"
                    /><span>分</span>
                  </div>
                </el-form-item>
              </div>

              <div class="section-title">
                <div>
                  <h3>题型配置</h3>
                  <p>AI识别出的题型、数量和每题分值</p>
                </div>
              </div>
              <div class="type-table">
                <div class="type-table-head">
                  <span>题型</span><span>数量</span><span>每题分值</span
                  ><span>小计</span>
                </div>
                <div
                  v-for="(item, index) in parsed.type_config"
                  :key="`${item.type}-${index}`"
                  class="type-row"
                >
                  <el-select v-model="item.type"
                    ><el-option
                      v-for="type in questionTypes"
                      :key="type.value"
                      :label="type.label"
                      :value="type.value"
                  /></el-select>
                  <div class="unit-input compact">
                    <el-input-number
                      v-model="item.count"
                      :min="1"
                      :max="100"
                    /><span>道</span>
                  </div>
                  <div class="unit-input compact">
                    <el-input-number
                      v-model="item.score_each"
                      :min="0.5"
                      :step="0.5"
                    /><span>分</span>
                  </div>
                  <strong
                    >{{
                      Number(item.count || 0) * Number(item.score_each || 0)
                    }}
                    分</strong
                  >
                </div>
              </div>

              <div class="section-title">
                <div>
                  <h3>难度比例</h3>
                  <p>三项合计必须为 100%</p>
                </div>
                <el-tag :type="ratioValid ? 'success' : 'danger'"
                  >当前 {{ Math.round(ratioTotal * 100) }}%</el-tag
                >
              </div>
              <div class="difficulty-grid">
                <label v-for="name in ['简单', '中等', '困难']" :key="name">
                  <span>{{ name }}</span>
                  <el-input-number
                    v-model="parsed.difficulty_ratio[name]"
                    :min="0"
                    :max="1"
                    :step="0.1"
                  />
                  <b
                    >{{
                      Math.round(
                        Number(parsed.difficulty_ratio[name] || 0) * 100,
                      )
                    }}%</b
                  >
                </label>
              </div>

              <el-alert
                v-if="calculatedScore !== Number(parsed.target_score)"
                :title="`题型配置合计为 ${calculatedScore} 分，与目标总分 ${parsed.target_score} 分不一致，请修改后再确认。`"
                type="warning"
                show-icon
                :closable="false"
              />
              <div class="rule-options">
                <el-checkbox v-model="parsed.prefer_unused"
                  >优先选择未使用题目</el-checkbox
                ><el-checkbox v-model="parsed.allow_similar"
                  >允许相似题</el-checkbox
                ><el-checkbox v-model="parsed.allow_ai_fill"
                  >题库不足时允许AI补题</el-checkbox
                >
              </div>
              <div class="confirm-bar">
                <span>确认后从正式题库选题，不会直接调用AI生成整张试卷。</span
                ><el-button
                  type="success"
                  size="large"
                  :loading="generating"
                  @click="confirmParsed"
                  >确认规则并组卷</el-button
                >
              </div>
            </el-form>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { papersApi, agentsApi } from "../../api";
import { useAppStore } from "../../stores/app";
import ManualPaperForm from "./components/ManualPaperForm.vue";
import RulePaperForm from "./components/RulePaperForm.vue";

const router = useRouter();
const store = useAppStore();
const mode = ref("manual");
const naturalText = ref("");
const naturalCourse = ref("");
const parsing = ref(false);
const generating = ref(false);
const parsed = ref(null);
const paperWorkflow = ref(null);
const questionTypes = [
  ["single_choice", "单项选择题"],
  ["multiple_choice", "多项选择题"],
  ["judge", "判断题"],
  ["fill_blank", "填空题"],
  ["term_explanation", "名词解释题"],
  ["short_answer", "简答题"],
  ["essay", "论述题"],
  ["calculation", "计算题"],
  ["programming", "编程设计题"],
  ["case_analysis", "案例分析题"],
].map(([value, label]) => ({ value, label }));
const totalQuestions = computed(() =>
  (parsed.value?.type_config || []).reduce(
    (sum, item) => sum + Number(item.count || 0),
    0,
  ),
);
const calculatedScore = computed(() =>
  (parsed.value?.type_config || []).reduce(
    (sum, item) => sum + Number(item.count || 0) * Number(item.score_each || 0),
    0,
  ),
);
const ratioTotal = computed(() =>
  Object.values(parsed.value?.difficulty_ratio || {}).reduce(
    (sum, value) => sum + Number(value || 0),
    0,
  ),
);
const ratioValid = computed(() => Math.abs(ratioTotal.value - 1) < 0.001);

const parseRule = async () => {
  if (!naturalCourse.value || !naturalText.value.trim())
    return ElMessage.warning("请选择课程并输入组卷要求");
  parsing.value = true;
  try {
    paperWorkflow.value = await agentsApi.paperPlan({
      text: naturalText.value,
      course_id: naturalCourse.value,
    });
    while (["WAITING", "RUNNING"].includes(paperWorkflow.value.status)) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      paperWorkflow.value = await agentsApi.workflow(paperWorkflow.value.id);
    }
    if (paperWorkflow.value.status === "FAILED") throw new Error(paperWorkflow.value.error_message || "组卷规划失败");
    parsed.value = paperWorkflow.value.result;
    ElMessage.success("组卷要求已解析，请检查下方规则");
  } finally {
    parsing.value = false;
  }
};
const confirmParsed = async () => {
  if (!parsed.value.name?.trim()) return ElMessage.warning("请填写试卷名称");
  if (!ratioValid.value) return ElMessage.warning("难度比例之和必须为100%");
  if (!parsed.value.type_config?.length)
    return ElMessage.warning("至少需要一种题型");
  if (calculatedScore.value !== Number(parsed.value.target_score))
    return ElMessage.warning("题型配置分值与目标总分不一致");
  await ElMessageBox.confirm(
    `将生成 ${totalQuestions.value} 道题、总分 ${parsed.value.target_score} 分的试卷。`,
    "确认AI组卷规则",
  );
  generating.value = true;
  try {
    const data = await papersApi.rule({
      ...parsed.value,
      course: naturalCourse.value,
      workflow_id: paperWorkflow.value?.id,
    });
    if (data.shortages.length)
      await ElMessageBox.alert(
        data.shortages
          .map(
            (item) =>
              `${item.type}需要${item.required}道，当前只有${item.available}道，缺少${item.missing}道`,
          )
          .join("\n"),
        "题库数量不足",
        { type: "warning" },
      );
    router.push(`/papers/${data.paper.id}/edit`);
  } finally {
    generating.value = false;
  }
};
onMounted(async () => {
  await store.loadCourses();
  naturalCourse.value = store.courses[0]?.id || "";
});
</script>

<style scoped>
.create-tabs:deep(.el-tabs__header) {
  padding: 0 20px;
  margin-bottom: 0;
}
.ai-workbench {
  max-width: 1050px;
  margin: 0 auto;
}
.request-area {
  margin-top: 18px;
  padding: 18px;
  background: #f7f9fc;
  border: 1px solid var(--border);
  border-radius: 12px;
}
.request-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}
.rule-sheet {
  margin-top: 22px;
  border: 1px solid #dbe7f7;
  border-radius: 14px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 8px 26px rgba(22, 119, 255, 0.07);
}
.rule-sheet-head {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  background: linear-gradient(135deg, #edf5ff, #f2fbfb);
}
.rule-sheet-head h2 {
  margin: 5px 0;
  font-size: 20px;
}
.rule-sheet-head p {
  margin: 0;
  color: var(--text-secondary);
}
.eyebrow {
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.rule-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-bottom: 1px solid var(--border);
}
.rule-metrics > div {
  padding: 18px 22px;
  border-right: 1px solid var(--border);
}
.rule-metrics > div:last-child {
  border-right: 0;
}
.rule-metrics span {
  display: block;
  color: var(--text-secondary);
  font-size: 12px;
}
.rule-metrics strong {
  margin-right: 5px;
  font-size: 25px;
  color: var(--text);
}
.rule-metrics em {
  color: var(--text-secondary);
  font-style: normal;
}
.rule-form {
  padding: 24px;
}
.unit-input {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
}
.paper-agent-status{display:grid;grid-template-columns:minmax(220px,.9fr) minmax(260px,1.4fr) auto;align-items:center;gap:16px;margin-top:14px;padding:13px 15px;border:1px solid #d5e6f8;border-radius:10px;background:#f7fbff}.paper-agent-status>div:first-child{display:grid;grid-template-columns:12px 1fr;column-gap:8px}.paper-agent-status .status-dot{grid-row:1/3;margin-top:6px}.paper-agent-status b,.paper-agent-status small{display:block}.paper-agent-status small{color:var(--text-secondary);font-size:11px}
.unit-input .el-input-number {
  width: 100%;
}
.unit-input span {
  flex: 0 0 auto;
  color: var(--text-secondary);
}
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 12px 0;
}
.section-title h3 {
  margin: 0;
}
.section-title p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.type-table {
  margin-bottom: 24px;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.type-table-head,
.type-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr 0.7fr;
  gap: 12px;
  align-items: center;
  padding: 11px 14px;
}
.type-table-head {
  background: #f5f7fb;
  color: var(--text-secondary);
  font-size: 13px;
}
.type-row {
  border-top: 1px solid var(--border);
}
.compact .el-input-number {
  max-width: 130px;
}
.difficulty-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}
.difficulty-grid label {
  display: grid;
  grid-template-columns: 46px 1fr 44px;
  gap: 8px;
  align-items: center;
  padding: 13px;
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 9px;
}
.difficulty-grid b {
  color: var(--primary);
  text-align: right;
}
.rule-options {
  display: flex;
  gap: 22px;
  margin-top: 20px;
}
.confirm-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin: 22px -24px -24px;
  padding: 16px 24px;
  background: #f7fafc;
  border-top: 1px solid var(--border);
}
.confirm-bar span {
  color: var(--text-secondary);
  font-size: 13px;
}
@media (max-width: 900px) {
  .rule-metrics {
    grid-template-columns: repeat(2, 1fr);
  }
  .difficulty-grid {
    grid-template-columns: 1fr;
  }
}
</style>
