from pathlib import Path
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from common.response import api_response
from common.exceptions import BusinessError
from apps.questions.models import Question
from apps.questions.services import snapshot_question
from .models import Paper, PaperSection, PaperQuestion, ExportRecord
from .serializers import PaperSerializer, PaperSectionSerializer, ExportRecordSerializer
from .services import ExportService, find_similar_question_in_paper, parse_natural_rule, quality_analysis, recalculate_paper, rule_generate


def ensure_distinct_paper_question(question, existing_questions):
    conflict, score = find_similar_question_in_paper(question, existing_questions)
    if conflict is not None:
        raise BusinessError(f"该题与试卷中的题目#{conflict.id}过于接近，请选择其他题目。", 40953, 409)

class PaperViewSet(viewsets.ModelViewSet):
    serializer_class = PaperSerializer
    def get_queryset(self):
        qs = Paper.objects.filter(is_deleted=False).select_related("course").prefetch_related("sections__paper_questions")
        for key in ["course", "status", "paper_type"]:
            if self.request.query_params.get(key): qs = qs.filter(**{f"{key}_id" if key == "course" else key: self.request.query_params[key]})
        if self.request.query_params.get("keyword"): qs = qs.filter(name__icontains=self.request.query_params["keyword"])
        return qs
    def destroy(self, request, *args, **kwargs):
        paper = self.get_object()
        paper.is_deleted = True
        paper.save(update_fields=["is_deleted", "updated_at"])
        return api_response({"id": paper.id}, "试卷已删除", request=request)
    @action(detail=False, methods=["post"], url_path="manual-generate")
    def manual_generate(self, request):
        with transaction.atomic():
            paper = Paper.objects.create(course_id=request.data["course"], name=request.data["name"], paper_type=request.data.get("paper_type", "手动组卷"), duration=request.data.get("duration", 90), target_score=request.data.get("target_score", 100), instructions=request.data.get("instructions", ""))
            selected_questions = []
            for sec_no, section_data in enumerate(request.data.get("sections", [])):
                section = PaperSection.objects.create(paper=paper, title=section_data["title"], description=section_data.get("description", ""), sort_order=sec_no)
                for q_no, item in enumerate(section_data.get("questions", [])):
                    question = get_object_or_404(Question, pk=item["question_id"], is_deleted=False)
                    ensure_distinct_paper_question(question, selected_questions)
                    PaperQuestion.objects.create(paper=paper, section=section, question=question, sort_order=q_no, score=item.get("score", question.score), question_snapshot=snapshot_question(question))
                    selected_questions.append(question)
            recalculate_paper(paper)
        return api_response(PaperSerializer(paper).data, "试卷已创建", request=request)
    @action(detail=False, methods=["post"], url_path="rule-generate")
    def rule_generate_action(self, request):
        paper, shortages = rule_generate(request.data)
        workflow_id = request.data.get("workflow_id")
        if workflow_id:
            from apps.agents.models import AgentWorkflowRun
            AgentWorkflowRun.objects.filter(pk=workflow_id, workflow_type="PAPER_PLAN").update(status="SUCCESS", result={"paper_id": paper.id, "shortages": shortages}, finished_at=__import__("django.utils.timezone", fromlist=["now"]).now())
        message = "试卷已生成" if not shortages else "题库数量不足，已生成当前可用题目"
        return api_response({"paper": PaperSerializer(paper).data, "shortages": shortages}, message, request=request)
    @action(detail=False, methods=["post"], url_path="parse-natural-rule")
    def parse_natural_rule_action(self, request): return api_response(parse_natural_rule(request.data.get("text", ""), request.data.get("course_id")), "规则解析完成，请确认后组卷", request=request)
    @action(detail=True, methods=["post"], url_path="quality-analysis")
    def quality_analysis_action(self, request, pk=None):
        paper = self.get_object(); report = quality_analysis(paper)
        from apps.agents.services import record_paper_quality_workflow
        workflow = record_paper_quality_workflow(paper, report)
        return api_response({**report, "workflow_id": str(workflow.id)}, request=request)
    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        source = self.get_object()
        with transaction.atomic():
            clone = Paper.objects.create(course=source.course, name=request.data.get("name") or f"{source.name} - 副本", paper_type=source.paper_type, duration=source.duration, target_score=source.target_score, total_score=source.total_score, status="DRAFT", instructions=source.instructions, school_name=source.school_name, major=source.major, class_name=source.class_name, config=source.config)
            for sec in source.sections.all():
                new_sec = PaperSection.objects.create(paper=clone, title=sec.title, description=sec.description, sort_order=sec.sort_order, score=sec.score)
                PaperQuestion.objects.bulk_create([PaperQuestion(paper=clone, section=new_sec, question=x.question, sort_order=x.sort_order, score=x.score, question_snapshot=x.question_snapshot) for x in sec.paper_questions.all()])
        return api_response(PaperSerializer(clone).data, "试卷已复制", request=request)
    @action(detail=True, methods=["post"])
    def export(self, request, pk=None):
        record = ExportService().export(self.get_object(), request.data.get("export_type", "student"), request.data.get("file_format", "docx"))
        return api_response(ExportRecordSerializer(record).data, "导出完成", request=request)
    @action(detail=True, methods=["get"])
    def exports(self, request, pk=None): return api_response(ExportRecordSerializer(self.get_object().exports.all(), many=True).data, request=request)
    @action(detail=True, methods=["post"], url_path="reorder")
    def reorder(self, request, pk=None):
        paper = self.get_object()
        with transaction.atomic():
            for sec_index, sec_data in enumerate(request.data.get("sections", [])):
                section = get_object_or_404(PaperSection, pk=sec_data["id"], paper=paper); section.sort_order = sec_index; section.save()
                for q_index, q_data in enumerate(sec_data.get("questions", [])):
                    PaperQuestion.objects.filter(pk=q_data["id"], paper=paper).update(section=section, sort_order=q_index, score=q_data.get("score"))
            recalculate_paper(paper)
        return api_response(PaperSerializer(paper).data, "试卷顺序与分值已保存", request=request)
    @action(detail=True, methods=["post"], url_path="sections")
    def add_section(self, request, pk=None):
        paper = self.get_object()
        section = PaperSection.objects.create(paper=paper, title=request.data.get("title", "新大题"), description=request.data.get("description", ""), sort_order=paper.sections.count())
        return api_response(PaperSectionSerializer(section).data, "大题已新增", request=request)
    @action(detail=True, methods=["delete"], url_path=r"sections/(?P<section_id>[^/.]+)")
    def delete_section(self, request, pk=None, section_id=None):
        paper = self.get_object(); section = get_object_or_404(PaperSection, pk=section_id, paper=paper)
        if section.paper_questions.exists(): raise BusinessError("请先移出或删除该大题中的题目。", 40951, 409)
        section.delete(); return api_response(None, "大题已删除", request=request)
    @action(detail=True, methods=["post"], url_path="questions")
    def add_question(self, request, pk=None):
        paper = self.get_object(); section = get_object_or_404(PaperSection, pk=request.data.get("section_id"), paper=paper); question = get_object_or_404(Question, pk=request.data.get("question_id"), is_deleted=False)
        if PaperQuestion.objects.filter(paper=paper, question=question).exists(): raise BusinessError("该题已经在试卷中。", 40952, 409)
        ensure_distinct_paper_question(question, [item.question for item in PaperQuestion.objects.filter(paper=paper).select_related("question")])
        item = PaperQuestion.objects.create(paper=paper, section=section, question=question, sort_order=section.paper_questions.count(), score=request.data.get("score", question.score), question_snapshot=snapshot_question(question)); recalculate_paper(paper)
        return api_response({"id": item.id}, "题目已加入试卷", request=request)
    @action(detail=True, methods=["delete"], url_path=r"questions/(?P<item_id>[^/.]+)")
    def delete_question(self, request, pk=None, item_id=None):
        paper = self.get_object(); get_object_or_404(PaperQuestion, pk=item_id, paper=paper).delete(); recalculate_paper(paper)
        return api_response(None, "题目已从试卷移除", request=request)

@api_view(["GET"])
def download_export(request, pk):
    record = get_object_or_404(ExportRecord, pk=pk, status="SUCCESS")
    path = __import__("django.conf", fromlist=["settings"]).settings.MEDIA_ROOT / record.file_path
    if not path.exists(): raise BusinessError("导出文件不存在，请重新导出。", 40451, 404)
    return FileResponse(open(path, "rb"), as_attachment=True, filename=record.file_name)
