<template>
  <div class="page">
    <div class="page-header">
      <div>
        <el-button link @click="router.push('/papers')"
          ><ArrowLeft />返回试卷列表</el-button
        >
        <h1 class="page-title">试卷编辑器</h1>
        <p class="page-description">
          拖拽大题或题目调整顺序，保存后同步更新分值统计。
        </p>
      </div>
      <div>
        <el-button @click="router.push(`/papers/${paper.id}/preview`)"
          >预览</el-button
        ><el-button type="primary" :loading="saving" @click="saveAll"
          >保存试卷</el-button
        >
      </div>
    </div>
    <PageState :loading="loading" :error="error" @retry="load">
      <div class="stats-strip card">
        <span
          >题目总数 <b>{{ count }}</b></span
        ><span
          >当前总分 <b>{{ currentScore }}</b></span
        ><span
          >目标总分
          <b
            :class="{
              danger: Number(currentScore) !== Number(paper.target_score),
            }"
            >{{ paper.target_score }}</b
          ></span
        ><span
          >待审核题目 <b>{{ pending }}</b></span
        >
      </div>
      <div class="split-layout editor">
        <aside>
          <div class="card card-body">
            <h3>试卷信息</h3>
            <el-form label-position="top"
              ><el-form-item label="试卷名称"
                ><el-input v-model="paper.name"
              /></el-form-item>
              <div class="form-grid">
                <el-form-item
                  v-if="paper.paper_type !== 'AI辅助组卷'"
                  label="考试时间"
                  ><el-input-number
                    v-model="paper.duration"
                    :min="1" /></el-form-item
                ><el-form-item label="目标总分"
                  ><el-input-number
                    v-model="paper.target_score"
                    :min="1" /></el-form-item
                ><el-form-item label="学校名称"
                  ><el-input v-model="paper.school_name" /></el-form-item
                ><el-form-item label="专业"
                  ><el-input v-model="paper.major" /></el-form-item
                ><el-form-item label="班级"
                  ><el-input v-model="paper.class_name" /></el-form-item
                ><el-form-item label="考试说明" class="full"
                  ><el-input v-model="paper.instructions" type="textarea"
                /></el-form-item></div
            ></el-form>
          </div>
          <div class="card" style="margin-top: 18px">
            <div class="card-header">
              <span class="card-title">正式题库</span>
            </div>
            <div class="card-body">
              <div class="bank-filters">
                <el-input
                  v-model="keyword"
                  placeholder="搜索题目"
                  clearable
                  @clear="loadBank"
                  @keyup.enter="loadBank"
                />
                <el-select
                  v-model="questionType"
                  placeholder="全部题型"
                  clearable
                  @change="loadBank"
                >
                  <el-option
                    v-for="item in questionTypes"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
                <el-button type="primary" plain @click="loadBank">查询</el-button>
              </div>
              <el-table :data="bank" height="390">
                <el-table-column
                  prop="stem"
                  label="题目"
                  show-overflow-tooltip
                />
                <el-table-column label="题型" width="92">
                  <template #default="scope">{{
                    questionTypeLabel(scope.row.question_type)
                  }}</template>
                </el-table-column>
                <el-table-column prop="score" label="分" width="50" />
                <el-table-column label="" width="55">
                  <template #default="scope">
                    <el-button link @click="addToFirst(scope.row)">加入</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </aside>
        <main class="sections" ref="sectionsEl">
          <section
            v-for="(section, sectionIndex) in paper.sections"
            :key="section.id"
            class="section card"
            :data-id="section.id"
          >
            <div class="section-head drag-handle">
              <div>
                <h3>{{ sectionTitle(section, sectionIndex) }}</h3>
                <small
                  >{{ section.paper_questions.length }}题 ·
                  {{ sectionScore(section) }}分</small
                >
              </div>
              <el-button type="danger" link @click="removeSection(section)"
                >删除大题</el-button
              >
            </div>
            <div class="question-list" :data-section="section.id">
              <article
                v-for="(item, index) in section.paper_questions"
                :key="item.id"
                class="paper-question"
                :data-id="item.id"
              >
                <div class="question-drag"><Rank /></div>
                <div class="grow">
                  <b>{{ index + 1 }}. <MathText :text="item.question_snapshot.stem" /></b>
                  <div class="muted">
                    {{ questionTypeLabel(item.question_snapshot.question_type) }} ·
                    {{ item.question_snapshot.difficulty }}
                  </div>
                </div>
                <el-input-number
                  v-model="item.score"
                  :min="0.5"
                  :step="0.5"
                  size="small"
                /><el-button link type="danger" @click="removeQuestion(item)"
                  >移除</el-button
                >
              </article>
            </div>
          </section>
          <el-button class="add-section" @click="addSection"
            ><Plus />新增大题</el-button
          >
        </main>
      </div>
    </PageState>
  </div>
</template>
<script setup>
import { ref, computed, onMounted, nextTick } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import Sortable from "sortablejs";
import { papersApi, questionsApi } from "../../api";
import PageState from "../../components/PageState.vue";
import MathText from "../../components/MathText.vue";
const route = useRoute(),
  router = useRouter(),
  paper = ref({ sections: [] }),
  bank = ref([]),
  keyword = ref(""),
  questionType = ref(""),
  loading = ref(true),
  error = ref(""),
  saving = ref(false),
  sectionsEl = ref();
let sortables = [];
const questionTypes = [
  ["single_choice", "选择题"],
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
const questionTypeLabel = (value) =>
  questionTypes.find((item) => item.value === value)?.label || value || "未知题型";
const chineseNumber = (value) => {
  const digits = "零一二三四五六七八九";
  if (value < 10) return digits[value];
  if (value < 20) return `十${value % 10 ? digits[value % 10] : ""}`;
  return String(value);
};
const sectionTitle = (section, index) => {
  let title = String(section.title || "")
    .replace(
      /^(?:第\s*(?:\d+|[一二三四五六七八九十百]+)\s*部分|[一二三四五六七八九十百]+、)\s*/,
      "",
    )
    .trim();
  questionTypes.forEach(({ value, label }) => {
    title = title.replace(new RegExp(`\\b${value}\\b`, "g"), label);
  });
  return `第${chineseNumber(index + 1)}部分 ${title || "综合题"}`;
};
const sectionScore = (section) =>
  section.paper_questions.reduce((sum, item) => sum + Number(item.score), 0);
const count = computed(() =>
  paper.value.sections.reduce(
    (sum, section) => sum + section.paper_questions.length,
    0,
  ),
);
const currentScore = computed(() =>
  paper.value.sections.reduce((sum, section) => sum + sectionScore(section), 0),
);
const pending = computed(
  () =>
    paper.value.sections
      .flatMap((section) => section.paper_questions)
      .filter(
        (item) => item.question_status && item.question_status !== "APPROVED",
      ).length,
);
const loadBank = async () => {
  if (!paper.value.course) return;
  const data = await questionsApi.list({
    course: paper.value.course,
    review_status: "APPROVED",
    keyword: keyword.value,
    question_type: questionType.value,
    page_size: 100,
  });
  bank.value = data.items;
};
const initSort = () => {
  sortables.forEach((instance) => instance.destroy());
  sortables = [];
  if (sectionsEl.value) {
    sortables.push(
      new Sortable(sectionsEl.value, {
        animation: 180,
        handle: ".drag-handle",
        draggable: ".section",
        onEnd: (event) =>
          paper.value.sections.splice(
            event.newIndex,
            0,
            paper.value.sections.splice(event.oldIndex, 1)[0],
          ),
      }),
    );
  }
  document.querySelectorAll(".question-list").forEach((element) => {
    const sortable = new Sortable(element, {
      group: "paper-questions",
      animation: 180,
      handle: ".question-drag",
      draggable: ".paper-question",
      onEnd: (event) => {
        const from = paper.value.sections.find(
          (section) => String(section.id) === event.from.dataset.section,
        );
        const to = paper.value.sections.find(
          (section) => String(section.id) === event.to.dataset.section,
        );
        const item = from.paper_questions.splice(event.oldIndex, 1)[0];
        to.paper_questions.splice(event.newIndex, 0, item);
      },
    });
    sortables.push(sortable);
  });
};
const load = async () => {
  loading.value = true;
  try {
    paper.value = await papersApi.get(route.params.id);
    await loadBank();
    await nextTick();
    initSort();
  } catch (exc) {
    error.value = exc.message;
  } finally {
    loading.value = false;
  }
};
const saveAll = async () => {
  saving.value = true;
  try {
    const metadata = { ...paper.value };
    delete metadata.sections;
    await papersApi.update(paper.value.id, metadata);
    await papersApi.reorder(paper.value.id, {
      sections: paper.value.sections.map((section) => ({
        id: section.id,
        questions: section.paper_questions.map((item) => ({
          id: item.id,
          score: item.score,
        })),
      })),
    });
    ElMessage.success("试卷已保存");
    await load();
  } finally {
    saving.value = false;
  }
};
const addSection = async () => {
  await papersApi.addSection(paper.value.id, {
    title: `第${paper.value.sections.length + 1}部分`,
  });
  await load();
};
const removeSection = async (section) => {
  await ElMessageBox.confirm("只能删除没有题目的大题。", "删除大题", {
    type: "warning",
  });
  await papersApi.deleteSection(paper.value.id, section.id);
  await load();
};
const removeQuestion = async (item) => {
  await papersApi.deleteQuestion(paper.value.id, item.id);
  await load();
};
const addToFirst = async (question) => {
  if (!paper.value.sections.length) await addSection();
  await papersApi.addQuestion(paper.value.id, {
    section_id: paper.value.sections[0].id,
    question_id: question.id,
    score: question.score,
  });
  ElMessage.success("题目已加入");
  await load();
};
onMounted(load);
</script>
<style scoped>
.stats-strip {
  display: flex;
  gap: 36px;
  padding: 14px 20px;
  margin-bottom: 18px;
}
.stats-strip b {
  font-size: 18px;
  margin-left: 5px;
}
.danger {
  color: var(--danger);
}
.editor {
  align-items: start;
}
.sections {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.section {
  overflow: hidden;
}
.section-head {
  padding: 14px 18px;
  background: #f8fafc;
  display: flex;
  justify-content: space-between;
  cursor: grab;
}
.section-head h3 {
  margin: 0;
}
.section-head small {
  color: var(--text-secondary);
}
.paper-question {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  border-top: 1px solid var(--border);
}
.question-drag {
  cursor: grab;
  width: 24px;
  color: #8b96a8;
}
.question-drag svg {
  width: 18px;
}
.bank-filters {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) 138px auto;
  gap: 8px;
  margin-bottom: 12px;
}
.add-section {
  height: 48px;
  border-style: dashed;
}
</style>
