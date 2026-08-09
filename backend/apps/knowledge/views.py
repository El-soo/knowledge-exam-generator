from pathlib import Path
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.parsers import MultiPartParser, FormParser
from common.file_utils import sha256_file, safe_filename
from common.response import api_response
from common.exceptions import BusinessError
from apps.courses.models import Course
from apps.ai_service.services import OllamaService, get_prompt
from apps.system_settings.models import AITaskResult
from .models import KnowledgeFile, ParseTask, Chapter, TextChunk, KnowledgePoint
from .serializers import KnowledgeFileSerializer, KnowledgeUploadSerializer, ParseTaskSerializer, ChapterSerializer, TextChunkSerializer, KnowledgePointSerializer
from .services import ParserFactory, TextCleaner, VectorService

class KnowledgeFileViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = KnowledgeFileSerializer
    def get_queryset(self):
        qs = KnowledgeFile.objects.filter(is_deleted=False).select_related("course")
        for param, field in [("course", "course_id"), ("status", "parse_status")]:
            if self.request.query_params.get(param): qs = qs.filter(**{field: self.request.query_params[param]})
        keyword = self.request.query_params.get("keyword")
        return qs.filter(Q(original_name__icontains=keyword) | Q(course__name__icontains=keyword)) if keyword else qs
    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        # QueryDict.copy() deep-copies its values. On Windows, large uploads are
        # TemporaryUploadedFile instances backed by an open BufferedRandom handle,
        # which cannot be pickled/deep-copied. Keep file objects by reference and
        # copy only the scalar form fields needed by the serializer.
        data = {
            field: request.data.get(field)
            for field in ["course", "auto_chapter", "auto_knowledge", "chunk_size", "chunk_overlap"]
            if field in request.data
        }
        data["files"] = request.FILES.getlist("files")
        serializer = KnowledgeUploadSerializer(data=data); serializer.is_valid(raise_exception=True)
        course = get_object_or_404(Course, pk=serializer.validated_data["course"], is_deleted=False)
        created = []
        for uploaded in serializer.validated_data["files"]:
            digest = sha256_file(uploaded)
            if KnowledgeFile.objects.filter(course=course, content_hash=digest, is_deleted=False).exists():
                created.append({"file": uploaded.name, "status": "DUPLICATE", "message": "该课程中已存在内容相同的文件"}); continue
            suffix = Path(uploaded.name).suffix.lower().lstrip(".")
            item = KnowledgeFile.objects.create(course=course, name=safe_filename(Path(uploaded.name).stem), original_name=safe_filename(uploaded.name), file=uploaded, file_type=suffix, file_size=uploaded.size, content_hash=digest, parse_config={k: serializer.validated_data[k] for k in ["auto_chapter", "auto_knowledge", "chunk_size", "chunk_overlap"]})
            task = ParseTask.objects.create(knowledge_file=item, current_step="等待后台Worker处理")
            created.append({"file": item.original_name, "status": "WAITING", "id": item.id, "task_id": task.id})
        return api_response(created, "文件已加入解析队列", request=request)
    @action(detail=True, methods=["post"])
    def parse(self, request, pk=None): return self._enqueue(request, self.get_object())
    @action(detail=True, methods=["post"])
    def reparse(self, request, pk=None): return self._enqueue(request, self.get_object())
    def _enqueue(self, request, item):
        if item.parse_tasks.filter(status__in=["WAITING", "RUNNING"]).exists(): raise BusinessError("该文件已有进行中的解析任务。", 40911, 409)
        task = ParseTask.objects.create(knowledge_file=item, current_step="等待后台Worker处理")
        item.parse_status = "WAITING"; item.parse_progress = 0; item.error_message = ""; item.save()
        return api_response(ParseTaskSerializer(task).data, "解析任务已创建", request=request)
    @action(detail=True, methods=["post"])
    def enable(self, request, pk=None):
        item = self.get_object(); item.is_enabled = True; item.parse_status = "SUCCESS" if item.chunk_count else "WAITING"; item.save(); return api_response(None, "文件已启用", request=request)
    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        item = self.get_object(); item.is_enabled = False; item.parse_status = "DISABLED"; item.save(); return api_response(None, "文件已停用", request=request)
    @action(detail=True, methods=["get"])
    def chunks(self, request, pk=None):
        qs = self.get_object().chunks.all(); page = self.paginate_queryset(qs); return self.get_paginated_response(TextChunkSerializer(page, many=True).data)
    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        item = self.get_object(); pages = ParserFactory.create(item.file_type).parse(item.file.path)
        text = "\n\n".join(x["text"] for x in pages)
        return api_response({"text": text[:100000], "truncated": len(text) > 100000}, request=request)
    def destroy(self, request, *args, **kwargs):
        item = self.get_object()
        with transaction.atomic():
            item.is_deleted = True; item.is_enabled = False; item.save(); item.chunks.all().delete()
        VectorService().delete_file(item.id)
        return api_response(None, "知识库文件和关联向量已删除", request=request)

class ParseTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ParseTask.objects.select_related("knowledge_file")
    serializer_class = ParseTaskSerializer
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        task = self.get_object(); task.cancel_requested = True; task.save(); return api_response(None, "已提交取消请求，将在当前处理步骤结束后停止。", request=request)

class ChapterViewSet(viewsets.ModelViewSet):
    serializer_class = ChapterSerializer
    pagination_class = None
    def get_queryset(self):
        qs = Chapter.objects.all()
        if self.request.query_params.get("course"): qs = qs.filter(course_id=self.request.query_params["course"])
        return qs
    def list(self, request, *args, **kwargs):
        roots = self.get_queryset().filter(parent__isnull=True)
        return api_response(ChapterSerializer(roots, many=True).data, request=request)
    @action(detail=False, methods=["post"])
    def reorder(self, request):
        with transaction.atomic():
            for item in request.data.get("items", []): Chapter.objects.filter(pk=item["id"]).update(parent_id=item.get("parent"), sort_order=item.get("sort_order", 0), level=item.get("level", 1))
        return api_response(None, "章节顺序已保存", request=request)
    @action(detail=False, methods=["post"], url_path="ai-extract")
    def ai_extract(self, request):
        file = get_object_or_404(KnowledgeFile, pk=request.data.get("file_id"), is_deleted=False)
        context = "\n".join(file.chunks.values_list("content", flat=True)[:20])
        result = OllamaService().chat_json([{"role": "system", "content": get_prompt("knowledge_point", "根据资料提取章节，输出JSON。")}, {"role": "user", "content": f"仅识别章节树：\n{context}"}], model=OllamaService().config["knowledge_model"], purpose="chapter_extract")
        preview = AITaskResult.objects.create(task_type="CHAPTER_EXTRACT", input_config={"file_id": file.id}, result_json=result)
        return api_response({"preview_id": preview.id, "result": result}, "章节识别完成，请确认后导入", request=request)
    @action(detail=False, methods=["post"], url_path="confirm-import")
    def confirm_import(self, request):
        preview = get_object_or_404(AITaskResult, pk=request.data.get("preview_id"), status="PREVIEW", task_type="CHAPTER_EXTRACT")
        file = get_object_or_404(KnowledgeFile, pk=preview.input_config["file_id"], is_deleted=False)
        result = request.data.get("result") or preview.result_json
        roots = result.get("chapters", result if isinstance(result, list) else [])
        created = []
        def import_nodes(nodes, parent=None, level=1):
            for index, node in enumerate(nodes or []):
                name = str(node.get("name", "")).strip()
                if not name: continue
                chapter, was_created = Chapter.objects.get_or_create(course=file.course, parent=parent, name=name, defaults={"number":node.get("number", ""), "level":level, "sort_order":index, "description":node.get("description", "")})
                if was_created: created.append(chapter.id)
                import_nodes(node.get("children", []), chapter, level + 1)
        with transaction.atomic():
            import_nodes(roots)
            preview.result_json = result; preview.status = "CONFIRMED"; preview.confirmed_at = __import__("django.utils.timezone", fromlist=["now"]).now(); preview.save()
        return api_response({"created_ids": created}, f"已导入{len(created)}个新章节，现有章节未被覆盖", request=request)

class KnowledgePointViewSet(viewsets.ModelViewSet):
    serializer_class = KnowledgePointSerializer
    def get_queryset(self):
        qs = KnowledgePoint.objects.select_related("course", "chapter")
        for key in ["course", "chapter"]:
            if self.request.query_params.get(key): qs = qs.filter(**{f"{key}_id": self.request.query_params[key]})
        if self.request.query_params.get("keyword"): qs = qs.filter(name__icontains=self.request.query_params["keyword"])
        return qs
    @action(detail=False, methods=["post"], url_path="ai-extract")
    def ai_extract(self, request):
        file = get_object_or_404(KnowledgeFile, pk=request.data.get("file_id"), is_deleted=False)
        context = "\n".join(file.chunks.values_list("content", flat=True)[:30])
        result = OllamaService().chat_json([{"role": "system", "content": get_prompt("knowledge_point", "根据资料提取适合教学和命题的知识点，输出严格JSON。")}, {"role": "user", "content": context}], model=OllamaService().config["knowledge_model"], purpose="knowledge_extract")
        preview = AITaskResult.objects.create(task_type="KNOWLEDGE_EXTRACT", input_config={"file_id": file.id, "course_id": file.course_id}, result_json=result)
        return api_response({"preview_id": preview.id, "result": result}, "知识点提取完成，请确认后导入", request=request)
    @action(detail=False, methods=["post"], url_path="confirm-import")
    def confirm_import(self, request):
        preview = get_object_or_404(AITaskResult, pk=request.data.get("preview_id"), status="PREVIEW")
        course = get_object_or_404(Course, pk=preview.input_config["course_id"])
        created = []
        with transaction.atomic():
            for item in preview.result_json.get("knowledge_points", []):
                chapter = Chapter.objects.filter(course=course, name=item.get("chapter_name", "")).first()
                point, _ = KnowledgePoint.objects.get_or_create(course=course, chapter=chapter, name=item["name"], defaults={"description": item.get("description", ""), "keywords": item.get("keywords", []), "importance": item.get("importance", "一般"), "difficulty": item.get("difficulty", "中等"), "source_type": "AI"})
                created.append(point.id)
            preview.status = "CONFIRMED"; preview.confirmed_at = __import__("django.utils.timezone", fromlist=["now"]).now(); preview.save()
        return api_response({"created_ids": created}, f"已导入{len(created)}个知识点", request=request)

@api_view(["POST"])
def knowledge_search(request):
    query = str(request.data.get("query", "")).strip()
    if not query: raise BusinessError("请输入需要检索的问题。", 40011)
    filters = {"course_id": request.data.get("course_id"), "file_id": request.data.get("file_id"), "chapter_id": request.data.get("chapter_id")}
    results = VectorService().search(query, filters, int(request.data.get("top_k", 5)), float(request.data.get("similarity_threshold", 0.25)))
    return api_response(results, request=request)
