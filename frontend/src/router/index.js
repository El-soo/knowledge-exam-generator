import { createRouter, createWebHistory } from 'vue-router'
import WorkbenchLayout from '../layouts/WorkbenchLayout.vue'

const routes = [{ path:'/', component:WorkbenchLayout, redirect:'/dashboard', children:[
  {path:'dashboard',component:()=>import('../views/dashboard/DashboardView.vue'),meta:{title:'首页工作台'}},
  {path:'courses',component:()=>import('../views/courses/CourseListView.vue'),meta:{title:'课程管理'}},
  {path:'courses/create',component:()=>import('../views/courses/CourseFormView.vue'),meta:{title:'新建课程'}},
  {path:'courses/:id',component:()=>import('../views/courses/CourseDetailView.vue'),meta:{title:'课程详情'}},
  {path:'knowledge/files',component:()=>import('../views/knowledge/FileListView.vue'),meta:{title:'知识库管理'}},
  {path:'knowledge/upload',component:()=>import('../views/knowledge/UploadView.vue'),meta:{title:'上传知识库'}},
  {path:'knowledge/files/:id',component:()=>import('../views/knowledge/FileDetailView.vue'),meta:{title:'文件详情'}},
  {path:'knowledge/search',component:()=>import('../views/knowledge/SearchView.vue'),meta:{title:'知识库检索测试'}},
  {path:'chapters',component:()=>import('../views/chapters/ChapterView.vue'),meta:{title:'章节管理'}},
  {path:'knowledge-points',component:()=>import('../views/chapters/KnowledgePointView.vue'),meta:{title:'知识点管理'}},
  {path:'generation/create',component:()=>import('../views/generation/GenerationCreateView.vue'),meta:{title:'AI智能出题'}},
  {path:'generation/tasks',component:()=>import('../views/generation/TaskListView.vue'),meta:{title:'生成任务'}},
  {path:'generation/tasks/:id',component:()=>import('../views/generation/TaskDetailView.vue'),meta:{title:'任务详情'}},
  {path:'agents',component:()=>import('../views/agents/AgentCenterView.vue'),meta:{title:'多智能体中心'}},
  {path:'agents/workflows/:id',component:()=>import('../views/agents/WorkflowDetailView.vue'),meta:{title:'智能体工作流'}},
  {path:'questions',component:()=>import('../views/questions/QuestionListView.vue'),meta:{title:'题库管理'}},
  {path:'questions/import',component:()=>import('../views/questions/QuestionImportView.vue'),meta:{title:'导入题目'}},
  {path:'questions/:id',component:()=>import('../views/questions/QuestionDetailView.vue'),meta:{title:'题目详情'}},
  {path:'papers',component:()=>import('../views/papers/PaperListView.vue'),meta:{title:'试卷管理'}},
  {path:'papers/create',component:()=>import('../views/papers/PaperCreateView.vue'),meta:{title:'创建试卷'}},
  {path:'papers/:id/edit',component:()=>import('../views/papers/PaperEditorView.vue'),meta:{title:'试卷编辑器'}},
  {path:'papers/:id/preview',component:()=>import('../views/papers/PaperPreviewView.vue'),meta:{title:'试卷预览'}},
  {path:'papers/:id/analysis',component:()=>import('../views/papers/PaperAnalysisView.vue'),meta:{title:'试卷质量分析'}},
  {path:'settings',component:()=>import('../views/settings/SettingsView.vue'),meta:{title:'系统设置'}}
]}]
const router=createRouter({history:createWebHistory(),routes,scrollBehavior:()=>({top:0})})
router.afterEach(to=>{document.title=`${to.meta.title||''} - 知识库智能出题与组卷系统`})
export default router
