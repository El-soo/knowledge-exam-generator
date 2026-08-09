import shutil
from django.conf import settings
from django.db import connection
from django.db.models import Count
from rest_framework.decorators import api_view
from common.response import api_response
from apps.ai_service.services import get_config
from apps.courses.models import Course
from apps.knowledge.models import KnowledgeFile, KnowledgePoint, ParseTask
from apps.questions.models import Question
from apps.papers.models import Paper
from apps.system_settings.models import SystemConfig
from apps.knowledge.serializers import KnowledgeFileSerializer
from apps.questions.serializers import QuestionSerializer
from apps.papers.serializers import PaperSerializer

@api_view(["GET"])
def statistics(request):
    data = {"courses": Course.objects.filter(is_deleted=False).count(), "files": KnowledgeFile.objects.filter(is_deleted=False).count(), "knowledge_points": KnowledgePoint.objects.count(), "questions": Question.objects.filter(is_deleted=False).count(), "pending_questions": Question.objects.filter(is_deleted=False, review_status="PENDING").count(), "papers": Paper.objects.filter(is_deleted=False).count()}
    return api_response(data, request=request)

@api_view(["GET"])
def recent_files(request): return api_response(KnowledgeFileSerializer(KnowledgeFile.objects.filter(is_deleted=False).select_related("course")[:6], many=True).data, request=request)
@api_view(["GET"])
def recent_questions(request): return api_response(QuestionSerializer(Question.objects.filter(is_deleted=False).select_related("course", "chapter", "knowledge_point").prefetch_related("options", "reviews")[:6], many=True).data, request=request)
@api_view(["GET"])
def recent_papers(request): return api_response(PaperSerializer(Paper.objects.filter(is_deleted=False).select_related("course")[:6], many=True).data, request=request)

def chart(model, field, base_filter=None):
    qs = model.objects.filter(**(base_filter or {})).values(field).annotate(value=Count("id")).order_by(field)
    return [{"name": x[field] or "未设置", "value": x["value"]} for x in qs]
@api_view(["GET"])
def question_type_chart(request): return api_response(chart(Question, "question_type", {"is_deleted": False}), request=request)
@api_view(["GET"])
def difficulty_chart(request): return api_response(chart(Question, "difficulty", {"is_deleted": False}), request=request)
@api_view(["GET"])
def parse_status_chart(request): return api_response(chart(KnowledgeFile, "parse_status", {"is_deleted": False}), request=request)

@api_view(["GET"])
def health(request):
    database_ok = True
    try:
        with connection.cursor() as cursor: cursor.execute("SELECT 1"); cursor.fetchone()
    except Exception: database_ok = False
    try:
        import requests
        ollama_ok = requests.get(f"{get_config()['ollama_base_url'].rstrip('/')}/api/tags", timeout=2).ok
    except Exception: ollama_ok = False
    worker_row = SystemConfig.objects.filter(config_key="worker_heartbeat", config_value__status="RUNNING", updated_at__gte=__import__("django.utils.timezone", fromlist=["now"]).now() - __import__("datetime").timedelta(seconds=15)).first()
    worker_ok = bool(worker_row)
    disk = shutil.disk_usage(settings.BASE_DIR)
    return api_response({"database": database_ok, "ollama": ollama_ok, "worker": worker_ok, "current_model": get_config()["chat_model"], "disk_free_gb": round(disk.free / 1024**3, 1), "local": True}, request=request)

@api_view(["GET"])
def global_search(request):
    keyword = request.query_params.get("q", "").strip()
    if not keyword: return api_response([], request=request)
    data = []
    data += [{"type":"course", "id":x.id, "title":x.name, "route":f"/courses/{x.id}"} for x in Course.objects.filter(is_deleted=False, name__icontains=keyword)[:5]]
    data += [{"type":"file", "id":x.id, "title":x.original_name, "route":f"/knowledge/files/{x.id}"} for x in KnowledgeFile.objects.filter(is_deleted=False, original_name__icontains=keyword)[:5]]
    data += [{"type":"question", "id":x.id, "title":x.stem[:80], "route":f"/questions/{x.id}"} for x in Question.objects.filter(is_deleted=False, stem__icontains=keyword)[:5]]
    data += [{"type":"paper", "id":x.id, "title":x.name, "route":f"/papers/{x.id}/preview"} for x in Paper.objects.filter(is_deleted=False, name__icontains=keyword)[:5]]
    return api_response(data, request=request)
