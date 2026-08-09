from django.db import models
from apps.courses.models import Course
from apps.questions.models import Question

class Paper(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="papers")
    name = models.CharField(max_length=180)
    paper_type = models.CharField(max_length=60, blank=True)
    duration = models.PositiveIntegerField(default=90)
    target_score = models.DecimalField(max_digits=7, decimal_places=2, default=100)
    total_score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    status = models.CharField(max_length=20, default="DRAFT", db_index=True)
    instructions = models.TextField(blank=True)
    school_name = models.CharField(max_length=180, blank=True)
    major = models.CharField(max_length=120, blank=True)
    class_name = models.CharField(max_length=120, blank=True)
    config = models.JSONField(default=dict, blank=True)
    quality_score = models.FloatField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["-created_at"]

class PaperSection(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="sections")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    class Meta: ordering = ["sort_order", "id"]

class PaperQuestion(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="paper_questions")
    section = models.ForeignKey(PaperSection, on_delete=models.CASCADE, related_name="paper_questions")
    question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.SET_NULL, related_name="paper_uses")
    sort_order = models.PositiveIntegerField(default=0)
    score = models.DecimalField(max_digits=7, decimal_places=2, default=1)
    question_snapshot = models.JSONField(default=dict)
    class Meta:
        ordering = ["section__sort_order", "sort_order"]
        constraints = [models.UniqueConstraint(fields=["paper", "question"], condition=models.Q(question__isnull=False), name="unique_paper_question")]

class ExportRecord(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="exports")
    export_type = models.CharField(max_length=20)
    file_format = models.CharField(max_length=10)
    file_name = models.CharField(max_length=255, blank=True)
    file_path = models.CharField(max_length=500, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=20, default="WAITING")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
