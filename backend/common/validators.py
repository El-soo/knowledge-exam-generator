from pathlib import Path
from rest_framework.serializers import ValidationError
from .constants import FILE_TYPES

def validate_knowledge_file(value):
    suffix = Path(value.name).suffix.lower().lstrip(".")
    if suffix not in FILE_TYPES:
        raise ValidationError("仅支持PDF、DOCX、TXT和Markdown文件。")
    if value.size > 50 * 1024 * 1024:
        raise ValidationError("文件超过50MB，请压缩或拆分后上传。")
    return value
