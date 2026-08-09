from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.courses.models import Course
from apps.knowledge.models import Chapter, KnowledgePoint
from apps.questions.models import Question
from apps.questions.services import create_question, snapshot_question
from apps.papers.models import Paper, PaperSection, PaperQuestion
from apps.papers.services import recalculate_paper
from apps.system_settings.models import PromptTemplate

class Command(BaseCommand):
    help = "生成明确标记的演示课程、章节、知识点、题目和试卷"
    @transaction.atomic
    def handle(self, *args, **kwargs):
        courses = []
        for code, name, desc in [("DEMO-PY", "Python程序设计（演示）", "面向程序设计初学者的演示课程"), ("DEMO-LA", "线性代数（演示）", "矩阵与线性方程组演示课程"), ("DEMO-DS", "数据结构（演示）", "基础数据结构与算法演示课程")]:
            course, _ = Course.objects.get_or_create(code=code, defaults={"name": name, "description": desc, "grade": "本科", "major": "计算机类", "is_demo": True})
            courses.append(course)
        point_names = ["变量与数据类型", "条件语句", "循环语句", "函数定义", "列表操作", "矩阵基本运算", "线性方程组", "向量空间", "顺序表", "栈与队列"]
        points = []
        for i, point_name in enumerate(point_names):
            course = courses[0] if i < 5 else courses[1] if i < 8 else courses[2]
            chapter, _ = Chapter.objects.get_or_create(course=course, number=str(i + 1), defaults={"name": f"第{i + 1}章 {point_name}", "sort_order": i})
            point, _ = KnowledgePoint.objects.get_or_create(course=course, chapter=chapter, name=point_name, defaults={"description": f"{point_name}的核心概念与基本应用。", "keywords": [point_name], "importance": "核心" if i % 3 == 0 else "重要", "difficulty": ["简单", "中等", "较难"][i % 3], "source_type": "DEMO"})
            points.append(point)
        for i in range(20):
            course = courses[i % 3]; point = next((p for p in points if p.course_id == course.id), points[0]); stem = f"【演示题目{i + 1}】关于{point.name}，下列说法正确的是？"
            if Question.objects.filter(course=course, stem=stem).exists(): continue
            create_question(course, {"type": "single_choice", "stem": stem, "options": [{"label":"A", "content":"演示正确选项"}, {"label":"B", "content":"演示干扰项一"}, {"label":"C", "content":"演示干扰项二"}, {"label":"D", "content":"演示干扰项三"}], "answer":["A"], "analysis":"这是用于展示系统功能的演示解析，不代表正式教学内容。", "difficulty":["简单", "中等", "较难"][i % 3], "score":2, "knowledge_point_id":point.id, "chapter_id":point.chapter_id, "source_summary":"演示数据，无知识库来源。", "review_status":"APPROVED"}, source_type="DEMO")
        for q in Question.objects.filter(source_type="DEMO"): q.is_demo = True; q.review_status = "APPROVED"; q.save()
        for idx, course in enumerate(courses[:2]):
            paper, created = Paper.objects.get_or_create(course=course, name=f"{course.name}示例试卷", defaults={"paper_type":"演示试卷", "duration":90, "target_score":20, "is_demo":True})
            if created:
                section = PaperSection.objects.create(paper=paper, title="一、单项选择题", sort_order=0)
                for order, q in enumerate(Question.objects.filter(course=course, is_demo=True)[:10]): PaperQuestion.objects.create(paper=paper, section=section, question=q, sort_order=order, score=2, question_snapshot=snapshot_question(q))
                recalculate_paper(paper)
        prompt_dir = settings.BASE_DIR / "prompts"
        mapping = {"knowledge_point":"knowledge_point_prompt.txt", "question_generation":"question_generation_prompt.txt", "question_review":"question_review_prompt.txt", "paper_rule":"paper_rule_prompt.txt", "query_rewrite":"query_rewrite_prompt.txt"}
        for key, filename in mapping.items():
            content = (prompt_dir / filename).read_text(encoding="utf-8")
            PromptTemplate.objects.get_or_create(key=key, version=1, defaults={"content":content, "is_default":True, "is_active":True})
        self.stdout.write(self.style.SUCCESS("演示数据创建完成：3门课程、10个知识点、20道题目、2套试卷。"))
