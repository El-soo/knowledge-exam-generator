<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">试卷管理</h1>
        <p class="page-description">
          管理草稿、质量分析和学生版、答案版、解析版导出。
        </p>
      </div>
      <el-button type="primary" @click="router.push('/papers/create')"
        ><Plus />创建试卷</el-button
      >
    </div>
    <div class="toolbar card card-body">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索试卷名称"
        style="width: 240px"
      /><el-select
        v-model="filters.course"
        placeholder="全部课程"
        clearable
        style="width: 180px"
        ><el-option
          v-for="c in store.courses"
          :key="c.id"
          :label="c.name"
          :value="c.id" /></el-select
      ><el-select
        v-model="filters.status"
        placeholder="全部状态"
        clearable
        style="width: 140px"
        ><el-option
          v-for="x in ['DRAFT', 'EDITING', 'COMPLETED', 'EXPORTED', 'ARCHIVED']"
          :key="x"
          :value="x" /></el-select
      ><el-button @click="load">查询</el-button>
    </div>
    <div class="card">
      <PageState
        :loading="loading"
        :empty="!items.length"
        empty-text="还没有试卷。"
        ><el-table :data="items"
          ><el-table-column
            prop="name"
            label="试卷名称"
            min-width="220"
          /><el-table-column
            prop="course_name"
            label="课程"
            width="150"
          /><el-table-column
            prop="paper_type"
            label="类型"
            width="110"
          /><el-table-column
            prop="question_count"
            label="题目"
            width="70"
          /><el-table-column
            prop="total_score"
            label="总分"
            width="70"
          /><el-table-column label="时间(分钟)" width="100"
            ><template #default="s">{{
              s.row.duration || "—"
            }}</template></el-table-column
          ><el-table-column label="状态" width="95"
            ><template #default="s"
              ><StatusTag :value="s.row.status" /></template></el-table-column
          ><el-table-column label="质量评分" width="90"
            ><template #default="s">{{
              s.row.quality_score ?? "未分析"
            }}</template></el-table-column
          ><el-table-column label="更新时间" width="170"
            ><template #default="s">{{
              new Date(s.row.updated_at).toLocaleString()
            }}</template></el-table-column
          ><el-table-column label="操作" width="300" fixed="right"
            ><template #default="s"
              ><el-button
                link
                @click="router.push(`/papers/${s.row.id}/preview`)"
                >预览</el-button
              ><el-button link @click="router.push(`/papers/${s.row.id}/edit`)"
                >编辑</el-button
              ><el-button
                link
                @click="router.push(`/papers/${s.row.id}/analysis`)"
                >分析</el-button
              ><el-button link @click="copy(s.row)">复制</el-button
              ><el-dropdown @command="(x) => exportPaper(s.row, x)"
                ><el-button link type="primary">导出<ArrowDown /></el-button
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
              ><el-button
                link
                type="danger"
                :loading="deletingId === s.row.id"
                :disabled="deletingId !== null"
                @click="remove(s.row)"
                >删除</el-button
              ></template
            ></el-table-column
          ></el-table
        ></PageState
      >
    </div>
  </div>
</template>
<script setup>
import { ref, reactive, onMounted } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { papersApi } from "../../api";
import { useAppStore } from "../../stores/app";
import PageState from "../../components/PageState.vue";
import StatusTag from "../../components/StatusTag.vue";
const router = useRouter(),
  store = useAppStore(),
  items = ref([]),
  loading = ref(true),
  deletingId = ref(null),
  filters = reactive({ keyword: "", course: "", status: "" });
const load = async () => {
  loading.value = true;
  try {
    const d = await papersApi.list({ ...filters, page_size: 100 });
    items.value = d.items;
  } finally {
    loading.value = false;
  }
};
const copy = async (x) => {
  await papersApi.copy(x.id);
  ElMessage.success("试卷已复制");
  load();
};
const remove = async (x) => {
  try {
    await ElMessageBox.confirm(
      `确认删除“${x.name}”？删除后将不再出现在试卷列表中。`,
      "删除试卷",
      {
        type: "warning",
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
      },
    );
    deletingId.value = x.id;
    await papersApi.remove(x.id);
    items.value = items.value.filter((item) => item.id !== x.id);
    ElMessage.success("试卷已删除");
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close")
      console.error("删除试卷失败", error);
  } finally {
    deletingId.value = null;
  }
};
const exportPaper = async (x, cmd) => {
  const [export_type, file_format] = cmd.split("-");
  const r = await papersApi.export(x.id, { export_type, file_format });
  ElMessage.success("导出完成");
  location.href = r.download_url;
};
onMounted(() => {
  store.loadCourses();
  load();
});
</script>
