from django.db import models
from apps.courses.models import Course

class KnowledgeFile(models.Model):
    PARSE_STATUSES = [(x, x) for x in ["WAITING", "PARSING", "CLEANING", "CHUNKING", "VECTORIZING", "SUCCESS", "FAILED", "DISABLED", "INTERRUPTED"]]
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="knowledge_files")
    name = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="knowledge_files/%Y/%m/")
    file_type = models.CharField(max_length=20)
    file_size = models.PositiveBigIntegerField(default=0)
    content_hash = models.CharField(max_length=64, db_index=True)
    parse_status = models.CharField(max_length=20, choices=PARSE_STATUSES, default="WAITING", db_index=True)
    parse_progress = models.PositiveSmallIntegerField(default=0)
    char_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    parse_config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["course", "content_hash"], condition=models.Q(is_deleted=False), name="unique_active_course_file_hash")]

class ParseTask(models.Model):
    knowledge_file = models.ForeignKey(KnowledgeFile, on_delete=models.CASCADE, related_name="parse_tasks")
    status = models.CharField(max_length=20, default="WAITING", db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    current_step = models.CharField(max_length=120, blank=True)
    cancel_requested = models.BooleanField(default=False)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Chapter(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="chapters")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=180)
    number = models.CharField(max_length=40, blank=True)
    level = models.PositiveSmallIntegerField(default=1)
    sort_order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [models.Index(fields=["course", "parent", "sort_order"])]

class TextChunk(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="text_chunks")
    knowledge_file = models.ForeignKey(KnowledgeFile, on_delete=models.CASCADE, related_name="chunks")
    chapter = models.ForeignKey(Chapter, null=True, blank=True, on_delete=models.SET_NULL, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    content_hash = models.CharField(max_length=64, db_index=True)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    char_count = models.PositiveIntegerField(default=0)
    vector_id = models.CharField(max_length=120, blank=True, db_index=True)
    vector_status = models.CharField(max_length=20, default="PENDING")
    vector_error = models.TextField(blank=True)
    embedding_model = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["chunk_index"]
        constraints = [models.UniqueConstraint(fields=["knowledge_file", "chunk_index"], name="unique_file_chunk_index")]

class KnowledgePoint(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="knowledge_points")
    chapter = models.ForeignKey(Chapter, null=True, blank=True, on_delete=models.SET_NULL, related_name="knowledge_points")
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    keywords = models.JSONField(default=list, blank=True)
    importance = models.CharField(max_length=20, default="一般")
    difficulty = models.CharField(max_length=20, default="中等")
    source_type = models.CharField(max_length=20, default="MANUAL")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["chapter_id", "id"]
        constraints = [models.UniqueConstraint(fields=["course", "name", "chapter"], name="unique_course_chapter_knowledge_point")]

class KnowledgePointChunk(models.Model):
    knowledge_point = models.ForeignKey(KnowledgePoint, on_delete=models.CASCADE, related_name="chunk_links")
    text_chunk = models.ForeignKey(TextChunk, on_delete=models.CASCADE, related_name="knowledge_links")
    relevance_score = models.FloatField(default=1.0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["knowledge_point", "text_chunk"], name="unique_knowledge_chunk")]
