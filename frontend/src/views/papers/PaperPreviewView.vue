<template>
  <div class="page">
    <div class="page-header">
      <div>
        <el-button link @click="router.push('/papers')"
          ><ArrowLeft />返回试卷列表</el-button
        >
        <h1 class="page-title">试卷预览</h1>
        <p class="page-description">
          当前预览基于试卷题目快照，不受题库后续修改影响。
        </p>
      </div>
      <div>
        <el-button @click="router.push(`/papers/${paper.id}/edit`)"
          >编辑</el-button
        ><el-dropdown @command="exportPaper"
          ><el-button type="primary">导出试卷<ArrowDown /></el-button
          ><template #dropdown
            ><el-dropdown-menu
              ><el-dropdown-item command="student-docx"
                >学生版Word</el-dropdown-item
              ><el-dropdown-item command="answer-docx"
                >答案版Word</el-dropdown-item
              ><el-dropdown-item command="analysis-docx"
                >解析版Word</el-dropdown-item
              ><el-dropdown-item command="student-pdf"
                >学生版PDF</el-dropdown-item
              ></el-dropdown-menu
            ></template
          ></el-dropdown
        >
      </div>
    </div>
    <PageState :loading="loading" :error="error" @retry="load"
      ><article class="paper-sheet">
        <h1>{{ paper.name }}</h1>
        <div class="paper-info">
          <span>专业：{{ paper.major }}</span
          ><span>班级：{{ paper.class_name }}</span
          ><span>姓名：____________</span><span>学号：____________</span>
        </div>
        <p style="text-align: center">
          <template v-if="paper.duration"
            >考试时间：{{ paper.duration }}分钟　</template
          >总分：{{ paper.total_score }}分
        </p>
        <p v-if="paper.instructions">
          <b>考试说明：</b>{{ paper.instructions }}
        </p>
        <section
          v-for="(section, sectionIndex) in paper.sections"
          :key="section.id"
        >
          <h2>
            {{ sectionTitle(section, sectionIndex) }}（{{
              sectionScoreText(section)
            }}）
          </h2>
          <div
            v-for="(item, i) in section.paper_questions"
            :key="item.id"
            class="preview-question"
          >
            <p>
              <b>{{ i + 1 }}. <MathText :text="item.question_snapshot.stem" /></b>
            </p>
            <p
              v-for="o in item.question_snapshot.options"
              :key="o.label"
              class="option"
            >
              {{ o.label }}. <MathText :text="o.content" />
            </p>
            <div v-if="showAnswers" class="answer">
              答案：<MathText :text="item.question_snapshot.answer.join('、')" /><br />解析：<MathText
                :text="item.question_snapshot.analysis || '暂无'"
              />
            </div>
            <div
              v-else-if="
                !['single_choice', 'multiple_choice', 'judge'].includes(
                  item.question_snapshot.question_type,
                )
              "
              class="answer-space"
            ></div>
          </div>
        </section></article></PageState
    ><el-switch
      v-model="showAnswers"
      active-text="显示答案与解析"
      class="answer-switch"
    />
  </div>
</template>
<script setup>
import { ref, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { papersApi } from "../../api";
import PageState from "../../components/PageState.vue";
import MathText from "../../components/MathText.vue";
const route = useRoute(),
  router = useRouter(),
  paper = ref({ sections: [] }),
  loading = ref(true),
  error = ref(""),
  showAnswers = ref(false);
const typeLabels = {
  single_choice: "选择题",
  multiple_choice: "多项选择题",
  judge: "判断题",
  fill_blank: "填空题",
  term_explanation: "名词解释题",
  short_answer: "简答题",
  essay: "论述题",
  calculation: "计算题",
  programming: "编程设计题",
  case_analysis: "案例分析题",
};
const chineseNumber = (value) => {
  const digits = "零一二三四五六七八九";
  const number = Number(value);
  if (number < 10) return digits[number];
  if (number < 20) return `十${number % 10 ? digits[number % 10] : ""}`;
  if (number < 100)
    return `${digits[Math.floor(number / 10)]}十${number % 10 ? digits[number % 10] : ""}`;
  return String(number);
};
const formatScore = (value) => Number(value || 0).toString();
const sectionTitle = (section, index) => {
  let title = String(section.title || "")
    .replace(
      /^(?:第\s*(?:\d+|[一二三四五六七八九十百]+)\s*部分|[一二三四五六七八九十百]+、)\s*/,
      "",
    )
    .trim();
  Object.entries(typeLabels).forEach(([code, label]) => {
    title = title.replace(new RegExp(`\\b${code}\\b`, "g"), label);
  });
  if (!title) {
    const types = [
      ...new Set(
        section.paper_questions
          .map((item) => item.question_snapshot.question_type)
          .filter(Boolean),
      ),
    ];
    title = types.length === 1 ? typeLabels[types[0]] : "综合题";
  }
  return `第${chineseNumber(index + 1)}部分 ${title}`;
};
const sectionScoreText = (section) => {
  const scores = [
    ...new Set(section.paper_questions.map((item) => formatScore(item.score))),
  ];
  const totalScore = section.paper_questions.reduce(
    (sum, item) => sum + Number(item.score || 0),
    0,
  );
  return `共${formatScore(totalScore)}分${
    section.paper_questions.length && scores.length === 1
      ? `，每题${scores[0]}分`
      : ""
  }`;
};
const load = async () => {
  loading.value = true;
  try {
    paper.value = await papersApi.get(route.params.id);
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
};
const exportPaper = async (cmd) => {
  const [export_type, file_format] = cmd.split("-");
  const r = await papersApi.export(paper.value.id, {
    export_type,
    file_format,
  });
  ElMessage.success("导出完成");
  location.href = r.download_url;
};
onMounted(load);
</script>
<style scoped>
.preview-question {
  margin: 18px 0;
  line-height: 1.8;
}
.option {
  margin: 3px 0 3px 24px;
}
.answer {
  padding: 10px;
  background: #f1f8ff;
  color: #234;
  margin-top: 8px;
}
.answer-space {
  height: 90px;
  border-bottom: 1px dashed #aaa;
}
.answer-switch {
  position: fixed;
  right: 32px;
  bottom: 28px;
  background: #fff;
  padding: 12px 16px;
  border-radius: 10px;
  box-shadow: var(--shadow);
  z-index: 5;
}
</style>
