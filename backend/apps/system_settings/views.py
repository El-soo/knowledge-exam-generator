import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from django.conf import settings
from django.http import FileResponse
from rest_framework.decorators import api_view
from common.response import api_response
from common.exceptions import BusinessError
from apps.ai_service.services import DEFAULT_CONFIG, OllamaService, get_config, get_prompt
from .models import SystemConfig, PromptTemplate

PROMPT_KEYS = ["knowledge_point", "question_generation", "question_review", "paper_rule", "query_rewrite"]

@api_view(["GET", "PUT"])
def settings_view(request):
    if request.method == "GET": return api_response(get_config(), request=request)
    allowed = set(DEFAULT_CONFIG)
    payload = {k: v for k, v in request.data.items() if k in allowed}
    if int(payload.get("chunk_overlap", 0)) >= int(payload.get("chunk_size", 800)): raise BusinessError("默认重叠长度必须小于默认分块长度。", 40061)
    row, _ = SystemConfig.objects.get_or_create(config_key="system", defaults={"description": "系统统一配置"})
    row.config_value = {**(row.config_value or {}), **payload}; row.save()
    return api_response(get_config(), "系统配置已保存", request=request)

@api_view(["GET"])
def ollama_models(request): return api_response(OllamaService().list_models(), request=request)

@api_view(["POST"])
def ollama_test(request):
    models = OllamaService().list_models(); return api_response({"connected": True, "models": models, "base_url": OllamaService().base_url}, "Ollama连接正常", request=request)

@api_view(["POST"])
def model_test(request):
    result = OllamaService().chat_json([{"role": "user", "content": "请只返回JSON：{\"message\":\"模型测试成功\"}"}], request.data.get("model"), "model_test")
    return api_response(result, "模型响应正常", request=request)

@api_view(["GET"])
def prompt_list(request):
    rows = []
    for key in PROMPT_KEYS:
        get_prompt(key)
        active = PromptTemplate.objects.filter(key=key, is_active=True).order_by("-version").first()
        rows.append({"key": key, "version": active.version if active else 0, "content": active.content if active else ""})
    return api_response(rows, request=request)

@api_view(["PUT"])
def prompt_update(request, key):
    if key not in PROMPT_KEYS: raise BusinessError("未知的提示词类型。", 40461, 404)
    content = str(request.data.get("content", "")).strip()
    if not content: raise BusinessError("提示词内容不能为空。", 40062)
    current = PromptTemplate.objects.filter(key=key).order_by("-version").first()
    PromptTemplate.objects.filter(key=key, is_active=True).update(is_active=False)
    row = PromptTemplate.objects.create(key=key, version=(current.version + 1 if current else 1), content=content, is_active=True)
    return api_response({"key": key, "version": row.version, "content": row.content}, "提示词已保存为新版本", request=request)

@api_view(["POST"])
def prompt_reset(request, key):
    # 恢复到系统最新的默认模板，而不是历史上最早的版本。
    get_prompt(key)
    default = PromptTemplate.objects.filter(key=key, is_default=True).order_by("-version").first()
    if not default: raise BusinessError("没有找到默认提示词。", 40462, 404)
    PromptTemplate.objects.filter(key=key, is_active=True).update(is_active=False)
    latest = PromptTemplate.objects.filter(key=key).order_by("-version").first()
    row = PromptTemplate.objects.create(key=key, version=(latest.version + 1 if latest else 1), content=default.content, is_active=True)
    return api_response({"key": key, "version": row.version, "content": row.content}, "已恢复默认提示词", request=request)

@api_view(["POST"])
def create_backup(request):
    backup_dir = settings.MEDIA_ROOT / "exports"; backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"knowledge_exam_backup_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with tempfile.TemporaryDirectory() as temp:
        db_copy = Path(temp) / "db.sqlite3"
        source = sqlite3.connect(settings.DATABASES["default"]["NAME"]); destination = sqlite3.connect(db_copy); source.backup(destination); destination.close(); source.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "db.sqlite3")
            for folder in [settings.MEDIA_ROOT / "knowledge_files", settings.CHROMA_PATH]:
                if folder.exists():
                    for path in folder.rglob("*"):
                        if path.is_file(): zf.write(path, str(path.relative_to(settings.BASE_DIR)))
            checkpoint = settings.LANGGRAPH_CHECKPOINT_PATH
            if checkpoint.exists(): zf.write(checkpoint, str(checkpoint.relative_to(settings.BASE_DIR)))
    return FileResponse(open(target, "rb"), as_attachment=True, filename=target.name)
