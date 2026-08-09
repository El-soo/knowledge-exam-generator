from rest_framework import serializers
from common.validators import validate_knowledge_file
from .models import KnowledgeFile, ParseTask, Chapter, TextChunk, KnowledgePoint, KnowledgePointChunk

class ParseTaskSerializer(serializers.ModelSerializer):
    class Meta: model = ParseTask; fields = "__all__"

class KnowledgeFileSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source="course.name", read_only=True)
    latest_task_id = serializers.SerializerMethodField()
    class Meta:
        model = KnowledgeFile
        exclude = ["is_deleted"]
        read_only_fields = ["name", "original_name", "file_type", "file_size", "content_hash", "parse_status", "parse_progress", "char_count", "chunk_count", "error_message"]
    def get_latest_task_id(self, obj):
        task = obj.parse_tasks.order_by("-created_at").first(); return task.id if task else None

class KnowledgeUploadSerializer(serializers.Serializer):
    course = serializers.IntegerField()
    files = serializers.ListField(child=serializers.FileField(validators=[validate_knowledge_file]), allow_empty=False)
    auto_chapter = serializers.BooleanField(default=True)
    auto_knowledge = serializers.BooleanField(default=True)
    chunk_size = serializers.IntegerField(default=800, min_value=200, max_value=4000)
    chunk_overlap = serializers.IntegerField(default=120, min_value=0, max_value=1000)
    def validate(self, attrs):
        if attrs["chunk_overlap"] >= attrs["chunk_size"]: raise serializers.ValidationError("重叠长度必须小于分块长度。")
        return attrs

class ChapterSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    class Meta: model = Chapter; fields = "__all__"
    def get_children(self, obj): return ChapterSerializer(obj.children.all(), many=True).data

class TextChunkSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField(source="knowledge_file.original_name", read_only=True)
    chapter_name = serializers.CharField(source="chapter.name", read_only=True, allow_null=True)
    class Meta: model = TextChunk; fields = "__all__"

class KnowledgePointSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source="course.name", read_only=True)
    chapter_name = serializers.CharField(source="chapter.name", read_only=True, allow_null=True)
    question_count = serializers.IntegerField(source="questions.count", read_only=True)
    class Meta: model = KnowledgePoint; fields = "__all__"

class KnowledgePointChunkSerializer(serializers.ModelSerializer):
    class Meta: model = KnowledgePointChunk; fields = "__all__"
