from django.db.models import Count
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action

from common.exceptions import BusinessError
from common.response import api_response
from .models import AgentDefinition, AgentWorkflowRun
from .serializers import AgentDefinitionSerializer, AgentStepSerializer, AgentWorkflowSerializer
from .services import create_paper_plan_workflow, ensure_agent_definitions, retry_workflow


class AgentDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AgentDefinitionSerializer
    pagination_class = None

    def get_queryset(self):
        ensure_agent_definitions()
        return AgentDefinition.objects.all()

    @action(detail=True, methods=["put", "patch"], url_path="settings")
    def agent_settings(self, request, pk=None):
        item = self.get_object()
        item.enabled = request.data.get("enabled", item.enabled)
        item.config = {**item.config, **(request.data.get("config") or {})}
        item.save()
        return api_response(AgentDefinitionSerializer(item).data, "智能体设置已保存", request=request)


class AgentWorkflowViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AgentWorkflowSerializer

    def get_queryset(self):
        queryset = AgentWorkflowRun.objects.prefetch_related("steps", "artifacts", "metrics")
        for key in ["status", "workflow_type", "quality_mode"]:
            if self.request.query_params.get(key):
                queryset = queryset.filter(**{key: self.request.query_params[key]})
        return queryset

    @action(detail=False, methods=["get"])
    def statistics(self, request):
        queryset = AgentWorkflowRun.objects.all()
        total = queryset.count()
        completed = queryset.filter(status__in=["SUCCESS", "AWAITING_REVIEW"]).count()
        data = {
            "total": total,
            "running": queryset.filter(status="RUNNING").count(),
            "waiting": queryset.filter(status="WAITING").count(),
            "awaiting_review": queryset.filter(status="AWAITING_REVIEW").count(),
            "failed": queryset.filter(status="FAILED").count(),
            "success_rate": round(completed / total * 100, 1) if total else 0,
            "by_type": list(queryset.values("workflow_type").annotate(count=Count("id")).order_by("workflow_type")),
        }
        return api_response(data, request=request)

    @action(detail=True, methods=["get"])
    def steps(self, request, pk=None):
        queryset = self.get_object().steps.all()
        if request.query_params.get("after"):
            queryset = queryset.filter(id__gt=request.query_params["after"])
        return api_response(AgentStepSerializer(queryset, many=True).data, request=request)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        workflow = self.get_object()
        if workflow.status not in {"WAITING", "RUNNING"}:
            raise BusinessError("当前工作流已经停止，无需取消。", 40932, 409)
        workflow.cancel_requested = True
        workflow.save(update_fields=["cancel_requested", "updated_at"])
        return api_response(None, "已提交取消请求", request=request)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        return api_response(AgentWorkflowSerializer(retry_workflow(self.get_object())).data, "工作流已重新加入队列", request=request)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        workflow = self.get_object()
        if workflow.workflow_type != "KNOWLEDGE_CURATION" or workflow.status != "AWAITING_REVIEW":
            raise BusinessError("当前工作流没有可确认的知识整理结果。", 40933, 409)
        from apps.courses.models import Course
        from apps.knowledge.models import Chapter, KnowledgePoint
        from apps.system_settings.models import AITaskResult
        course = Course.objects.get(pk=workflow.input_data["course_id"])
        result = request.data.get("result") or {key: workflow.result.get(key, []) for key in ["chapters", "knowledge_points"]}
        chapter_count = point_count = 0
        with transaction.atomic():
            for index, item in enumerate(result.get("chapters", [])):
                name = str(item.get("name", "")).strip()
                if not name: continue
                _, created = Chapter.objects.get_or_create(course=course, parent=None, name=name, defaults={"number": item.get("number", ""), "description": item.get("description", ""), "sort_order": index})
                chapter_count += int(created)
            for item in result.get("knowledge_points", []):
                name = str(item.get("name", "")).strip()
                if not name: continue
                chapter = Chapter.objects.filter(course=course, name=item.get("chapter_name", "")).first()
                _, created = KnowledgePoint.objects.get_or_create(course=course, chapter=chapter, name=name, defaults={"description": item.get("description", ""), "keywords": item.get("keywords", []), "importance": item.get("importance", "一般"), "difficulty": item.get("difficulty", "中等"), "source_type": "AI"})
                point_count += int(created)
            workflow.status = "SUCCESS"; workflow.finished_at = timezone.now(); workflow.result = {**workflow.result, "confirmed": True, "created_chapters": chapter_count, "created_knowledge_points": point_count}; workflow.save()
            if workflow.result.get("preview_id"):
                AITaskResult.objects.filter(pk=workflow.result["preview_id"]).update(status="CONFIRMED", confirmed_at=timezone.now())
        return api_response({"created_chapters": chapter_count, "created_knowledge_points": point_count}, "知识整理结果已确认导入", request=request)

    @action(detail=False, methods=["post"], url_path="paper-plan")
    def paper_plan(self, request):
        workflow = create_paper_plan_workflow(request.data.get("text"), request.data.get("course_id"))
        return api_response(AgentWorkflowSerializer(workflow).data, "组卷规划工作流已创建", request=request)
