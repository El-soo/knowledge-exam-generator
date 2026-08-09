from django.db import models
from apps.courses.models import Course
from apps.knowledge.models import Chapter, KnowledgePoint

class GenerationTask(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="generation_tasks")
    status = models.CharField(max_length=30, default="WAITING", db_index=True)
    progress = models.PositiveSmallIntegerField(default=0)
    config = models.JSONField(default=dict)
    prompt = models.TextField(blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True)
    retrieved_chunks = models.JSONField(default=list)
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    cancel_requested = models.BooleanField(default=False)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

class Question(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="questions")
    chapter = models.ForeignKey(Chapter, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    knowledge_point = models.ForeignKey(KnowledgePoint, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    generation_task = models.ForeignKey(GenerationTask, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions")
    question_type = models.CharField(max_length=40, db_index=True)
    stem = models.TextField()
    answer = models.JSONField(default=list)
    analysis = models.TextField(blank=True)
    scoring_points = models.JSONField(default=list)
    difficulty = models.CharField(max_length=20, default="中等", db_index=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, default=1)
    source_type = models.CharField(max_length=20, default="MANUAL")
    source_summary = models.TextField(blank=True)
    source_chunk_ids = models.JSONField(default=list)
    grounding_score = models.FloatField(null=True, blank=True)
    generation_model = models.CharField(max_length=120, blank=True)
    review_status = models.CharField(max_length=30, default="PENDING", db_index=True)
    ai_review_score = models.FloatField(null=True, blank=True)
    is_favorite = models.BooleanField(default=False)
    use_count = models.PositiveIntegerField(default=0)
    content_hash = models.CharField(max_length=64, db_index=True)
    is_demo = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["course", "review_status", "question_type", "difficulty"])]

class QuestionOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    label = models.CharField(max_length=10)
    content = models.TextField()
    is_correct = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [models.UniqueConstraint(fields=["question", "label"], name="unique_question_option_label")]

class QuestionReview(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="reviews")
    review_type = models.CharField(max_length=20)
    passed = models.BooleanField(default=False)
    score = models.FloatField(default=0)
    issues = models.JSONField(default=list)
    suggestions = models.JSONField(default=list)
    revised_question = models.JSONField(null=True, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
